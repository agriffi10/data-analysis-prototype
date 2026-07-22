"""data-quality create-temp-tables — build the throwaway tables Athena profiles through.

The verb that turns "a folder of files" into "something SQL can read". It creates:

  - the TYPED table ``dq_tmp_{hex32}`` over the source, whose column list comes from
    SPEC-110's per-file probes. The explicit list is not optional: Athena does NOT
    auto-detect a Parquet schema, so a CREATE EXTERNAL TABLE over Parquet or JSON must
    name every column and type — which is exactly why inspect-source carries a Parquet
    reader (SPEC-108 FR-003 / SPEC-110 FR-005).
  - for CSV only, the single-column RAW-LINE table ``dq_tmp_raw_{hex32}`` over the same
    location, which is what makes ragged-row detection possible at 250 GB (see
    ``dqcommon.sql.RAW_LINE_SERDE`` for why it exists and why the delimiter is written as
    an escape sequence).

Both live in the USER'S OWN Glue database (personal) or the shared space's (shared) —
which is exactly why every failure path in the state machine must reach drop-temp-tables.
A leaked dq_tmp_ table is visible in the Query workspace's schema rail and eventually
collides with a real table name.
"""

import logging

from cpcommon import athena, config as cpconfig, events
from cpcommon import observability
from cpcommon.errors import TerminalError
from dqcommon import manifest as manifest_store, messages, notify, sql

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one data-quality run is nine
# invocations, and they are only one queryable set if they share a service name
# (SPEC-127 FR-003). The per-verb identity rides as the `verb` field on each span.
observability.init(service="data-quality")


def _database(event: dict) -> str:
    """Return the Glue database the temp tables are created in.

    The database IS the space: a personal check uses the actor's own database (username =
    database name, SPEC-033), a shared check uses the space's. Both are re-derived from
    the state validate-authorize already proved the actor may use — the request body never
    carried a database, and it must not start being trusted for one here.
    """
    space = event.get("space") or {}
    kind = space.get("kind")
    if kind == "personal":
        return events.require(event, "actor", reason=messages.INVALID_REQUEST)
    if kind == "shared":
        prefix = events.require(event, "space", "prefix", reason=messages.INVALID_REQUEST)
        return prefix.strip("/")
    raise TerminalError(messages.INVALID_REQUEST, f"unknown space kind {kind!r}")


def _location(bucket: str, manifest: dict, location: str) -> str:
    """Return the ``s3://`` FOLDER URI the external tables read.

    Always a folder with a trailing slash, even when the user targeted a single file: an
    Athena external table's LOCATION is a PREFIX, so pointing it at an object key yields a
    table over nothing — a check that reports zero rows and looks like a clean result. A
    one-file target therefore becomes a table over the file's parent folder, which is
    still correct here because the manifest listed exactly that one object.
    """
    keys = [entry["key"] for entry in manifest.get("files") or []]
    if not keys:
        # inspect-source raises no_data_files long before this, so an empty manifest means
        # something else wrote it. Refuse rather than build a table over the space root.
        raise TerminalError(messages.INVALID_REQUEST, "manifest carries no files")

    prefix = location.rstrip("/")
    if keys == [prefix]:
        prefix = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
    return f"s3://{bucket}/{prefix}/" if prefix else f"s3://{bucket}/"


def _run_ddl(query: str, database: str, output_location: str) -> None:
    """Run one catalog DDL statement to completion.

    The shared start+poll runner is the right tool HERE and the wrong tool for the profile
    query: a CREATE returns in seconds, whereas a profiling query over 250 GB can outlast
    Lambda's 900-second ceiling — which is why that poll lives in the state machine
    instead (SPEC-108 FR-004 / SPEC-111 FR-004).
    """
    athena.run_ddl(
        query=query,
        database=database,
        workgroup=cpconfig.ATHENA_WORKGROUP,
        output_location=output_location,
        fail_reason=messages.QUERY_FAILED,
        timeout_reason=messages.QUERY_TIMEOUT,
    )


def _create(event: dict) -> dict:
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    request_id = events.require(event, "requestId", reason=messages.INVALID_REQUEST)
    manifest_key = events.require(event, "manifestKey", reason=messages.INVALID_REQUEST)
    report_prefix = events.require(event, "reportPrefix", reason=messages.INVALID_REQUEST)
    location = events.require(event, "location", reason=messages.INVALID_REQUEST)
    fmt = events.require(event, "format", reason=messages.INVALID_REQUEST)

    database = _database(event)
    manifest = manifest_store.load(bucket, manifest_key)

    columns = sql.union_columns(manifest.get("files") or [])
    try:
        sql.check_column_count(columns)
    except sql.TooManyColumnsError as exc:
        # The count comes from `columns`, not from parsing str(exc): the exception's text is
        # log prose, and a token that reaches a user must never be scraped out of a message.
        raise TerminalError(
            messages.TOO_MANY_COLUMNS, str(exc), tokens={"count": f"{len(columns):,}"}
        ) from exc

    table = sql.temp_table_name(request_id)
    raw_table = sql.raw_table_name(request_id) if fmt == "csv" else None
    table_location = _location(bucket, manifest, location)

    # THE NAMES GO INTO THE STATE BEFORE ANY CREATE RUNS (FR-001). If the second create
    # fails, or the verb dies after creating and before returning, drop-temp-tables still
    # receives both names and cleans up. They are pure functions of requestId so they
    # COULD be re-derived downstream — but only for as long as two verbs agree on the
    # derivation, and a leaked table in the user's own database is not a bug worth
    # risking on that.
    out = dict(event)
    out["database"] = database
    out["tempTable"] = table
    out["tempRawTable"] = raw_table
    out["columnCount"] = len(columns)

    # A DDL statement's "results" are an empty metadata file, but Athena still demands an
    # output location. It goes under the request's own report prefix rather than the
    # space's athenaresults/, so it inherits whatever retention the reports get and never
    # clutters a folder the user browses.
    ddl_output = f"s3://{bucket}/{report_prefix.rstrip('/')}/ddl/"

    _run_ddl(
        sql.build_temp_table_ddl(
            database, table, columns, manifest.get("partitionKeys") or [], fmt, table_location
        ),
        database,
        ddl_output,
    )
    if raw_table:
        _run_ddl(sql.build_raw_table_ddl(database, raw_table, table_location), database, ddl_output)

    logger.info(
        "created %s.%s (%d columns, format=%s, raw=%s) over %s",
        database,
        table,
        len(columns),
        fmt,
        raw_table or "-",
        table_location,
    )
    return out


# @traced is OUTERMOST, above @notifies_on_failure, deliberately: notifies_on_failure
# catches on its way out, so if it were outermost the span would close status="ok" on an
# invocation that actually failed and notified. Outermost traced sees the exception the
# handler really raised.
@observability.traced("create-temp-tables")
@notify.notifies_on_failure("create-temp-tables")
def handler(event, context) -> dict:
    """Create the temp table(s) and thread their names onward."""
    return _create(event)
