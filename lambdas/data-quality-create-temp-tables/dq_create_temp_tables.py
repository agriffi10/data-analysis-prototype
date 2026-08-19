"""data-quality create-temp-tables — builds the throwaway tables Athena profiles through.

The verb that turns a folder of files into something SQL can read. It creates the typed table
over the source, whose column list comes from the per-file probes — the explicit list is not
optional, since Athena does not auto-detect a Parquet schema, which is exactly why inspect-source
carries a Parquet reader. For CSV it also creates the single-column raw-line table over the same
location, which is what makes ragged-row detection possible at scale.

Both live in the user's own Glue database, or the shared space's, which is exactly why every
failure path in the state machine must reach the cleanup verb: a leaked temp table is visible in
the Query workspace's schema rail and eventually collides with a real table name.

The service name is the control plane, not the function: one data-quality run is nine
invocations, and they are only one queryable set if they share it. The per-verb identity rides as
the ``verb`` field.
"""

import logging

from cpcommon import athena, events, observability, results
from cpcommon import columns as columns_mod
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError
from dqcommon import manifest as manifest_store
from dqcommon import messages, notify, sql

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="data-quality")


def _database(event: dict) -> str:
    """Resolves the Glue database the temp tables are created in.

    The database is the space: a personal check uses the actor's own database, since a username is
    a database name, and a shared check uses the space's. Both are re-derived from the state the
    validate verb already proved the actor may use — the request body never carried a database,
    and it must not start being trusted for one here.

    Args:
      event: The task input, carrying the space and actor.

    Returns:
      The database name.

    Raises:
      TerminalError: ``invalid_request`` on an unknown space kind or a missing field.
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
    """Resolves the folder URI the external tables read.

    Always a folder with a trailing slash, even when the user targeted a single file: an external
    table's location is a prefix, so pointing it at an object key yields a table over nothing — a
    check that reports zero rows and looks like a clean result. A one-file target therefore
    becomes a table over the file's parent folder.

    That promotion is not sufficient on its own. Athena reads a location recursively, so the table
    covers every file in the parent folder rather than the one that was listed. What makes a
    single-file check correct is the path predicate the queries carry, decided by the one shared
    definition both this verb and the query builder consult.

    Args:
      bucket: The source bucket.
      manifest: The source manifest.
      location: The request's target location.

    Returns:
      The ``s3://`` folder URI, slash-terminated.

    Raises:
      TerminalError: ``invalid_request`` when the manifest carries no files. inspect-source raises
        a no-data terminal long before this, so an empty manifest means something else wrote it —
        refuse rather than build a table over the space root.
    """
    files = manifest.get("files") or []
    if not files:
        raise TerminalError(messages.INVALID_REQUEST, "manifest carries no files")

    prefix = location.rstrip("/")
    if sql.single_file_path(bucket, files, location):
        prefix = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
    return f"s3://{bucket}/{prefix}/" if prefix else f"s3://{bucket}/"


@observability.step("run-ddl")
def _run_ddl(query: str, database: str, output_location: str) -> None:
    """Runs one catalog DDL statement to completion.

    The shared submit-and-poll runner is the right tool here and the wrong tool for the profile
    query: a create returns in seconds, whereas a profiling query over a large source can outlast
    Lambda's ceiling, which is why that poll lives in the state machine instead.

    Args:
      query: The DDL statement.
      database: The target database.
      output_location: The ``s3://`` results prefix.

    Returns:
      None.

    Raises:
      TerminalError: ``query_failed`` or ``query_timeout``.
      TransientError: On a retryable Athena fault.
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
    """Reads the manifest, names the temp tables, and creates them.

    The names go into the state before any create runs. If the second create fails, or the verb
    dies after creating and before returning, the cleanup verb still receives both names. They are
    pure functions of the request id so they could be re-derived downstream — but only for as long
    as two verbs agree on the derivation, and a leaked table in the user's own database is not a
    bug worth risking on that.

    The DDL results location goes under the request's own report prefix rather than the space's
    results folder, so it inherits whatever retention the reports get and never clutters a folder
    the user browses. A DDL statement's results are an empty metadata file, but Athena still
    demands a location.

    Whether the raw-line table exists is recorded, because it decides whether the ragged check can
    run at all — so a missing ragged finding downstream reads as designed rather than as a bug.

    The column names are judged before either create runs, and their refusal is this check's
    answer rather than a gap in it: a name Athena will not accept makes the temp table
    unbuildable, so the alternative to naming the columns here is a raw engine error about a
    statement the user never wrote. The width cap is checked first because it is the cheaper
    question and its refusal is about the whole source rather than about particular columns.

    Args:
      event: The task input.

    Returns:
      The event with the database, table names and column count attached.

    Raises:
      TerminalError: ``invalid_request`` for a missing field or an empty manifest,
        ``too_many_columns`` when the source is too wide — the count comes from the column list
        rather than from parsing the exception's text, because a token that reaches a user must
        never be scraped out of a log message — ``invalid_column_names`` when a header carries a
        name Athena cannot use, or a query failure from the creates.
      TransientError: On a retryable Athena or S3 fault.
    """
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
        raise TerminalError(
            messages.TOO_MANY_COLUMNS, str(exc), tokens={"count": f"{len(columns):,}"}
        ) from exc
    try:
        columns_mod.check(columns)
    except columns_mod.InvalidColumnNamesError as exc:
        raise TerminalError(
            messages.INVALID_COLUMN_NAMES, exc.summary, tokens={"columns": exc.summary}
        ) from exc

    table = sql.temp_table_name(request_id)
    raw_table = sql.raw_table_name(request_id) if fmt == "csv" else None
    table_location = _location(bucket, manifest, location)

    out = dict(event)
    out["database"] = database
    out["tempTable"] = table
    out["tempRawTable"] = raw_table
    out["columnCount"] = len(columns)

    ddl_output = results.ddl_output(bucket, report_prefix)

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
    observability.info(
        "created temp tables",
        database=database,
        table=table,
        raw_table=raw_table,
        columns=len(columns),
        format=fmt,
        location=table_location,
    )
    return out


@observability.traced("create-temp-tables")
@notify.notifies_on_failure("create-temp-tables")
def handler(event, context) -> dict:
    """Creates the temp tables and threads their names onward.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    The failure is recorded in one place rather than at each raise site. The detail is safe to
    record here: every raise in this module interpolates a space kind, a count, or a literal —
    never anything read from a file.

    Args:
      event: The task input.
      context: The Lambda context, unused.

    Returns:
      The event with the database, table names and column count attached.

    Raises:
      TerminalError: ``invalid_request``, ``too_many_columns``, ``query_failed`` or
        ``query_timeout``.
      TransientError: On a retryable Athena or S3 fault.
    """
    try:
        return _create(event)
    except TerminalError as err:
        observability.error(
            "create-temp-tables failed",
            step="run-ddl",
            error_type=type(err).__name__,
            reason=err.reason,
            detail=err.detail,
            tokens=err.tokens or {},
        )
        raise
