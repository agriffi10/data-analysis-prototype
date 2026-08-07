"""data-quality start-profile-query — submits the three checks and waits for none of them.

Starts the three separately-degradable queries and returns their execution ids. It never waits:
the poll lives in the state machine, because a profiling query over a large source routinely
outruns Lambda's ceiling while a Standard execution can wait for up to a year.

The three, and why they are three: the profile query over the typed table is the backbone and its
failure is terminal; the ragged query over the raw-line table is CSV only and degrades on
failure; the duplicates query over the typed table degrades too.

Every submission carries an idempotency token derived from the request id. Without one, a Step
Functions retry after a transient error that arrived post-submission would start a second query,
and the pipeline would poll one execution while another ran unwatched.

The service name is the control plane, not the function: one data-quality run is nine
invocations, and they are only one queryable set if they share it. The per-verb identity rides as
the ``verb`` field.

Attributes:
  _TOKEN_SUFFIX: Per-query token suffixes. Distinct so the three submissions do not collide with
    each other, and still pure functions of the request id so a retry re-attaches to the same
    executions. Athena requires a length range the hex stem plus a suffix sits comfortably inside.
"""

import logging

from cpcommon import athena, events, observability
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError
from cpcommon.results import results_location
from dqcommon import manifest as manifest_store
from dqcommon import messages, notify, sql

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="data-quality")

_TOKEN_SUFFIX = {"profile": "-profile", "ragged": "-ragged", "duplicates": "-dupes"}


def _results_prefix(event: dict) -> str:
    """Resolves the results prefix this request's query output lands in.

    Per query, not per workgroup: the workgroup has exactly one static result location, so routing
    results into the requesting space is impossible any other way.

    A shared-space check lands under the space's own results folder in the shared bucket — a new
    prefix convention introduced deliberately here, where until now that folder existed only under
    a username in the user-space bucket. It is safe because the source listing already excludes
    results folders in both buckets, so these files can never be picked up as source data by a
    later check.

    Args:
      event: The task input, carrying the space and request id.

    Returns:
      The ``s3://`` results prefix.

    Raises:
      TerminalError: ``invalid_request`` when a required field is missing.
    """
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    space_root = events.require(event, "space", "prefix", reason=messages.INVALID_REQUEST).strip("/")
    request_id = events.require(event, "requestId", reason=messages.INVALID_REQUEST)
    return results_location(bucket, space_root, "data-quality", sub=request_id)


def _start(name: str, query: str, event: dict, database: str, results: str) -> str:
    """Submits one query under its own idempotency token.

    Args:
      name: The query's name, which picks the token suffix and the output sub-prefix.
      query: The rendered statement.
      event: The task input, read for the request id.
      database: The database the statement resolves names in.
      results: The request's results prefix.

    Returns:
      The execution id.

    Raises:
      TerminalError: ``query_failed`` when the query cannot be started.
      TransientError: On a retryable Athena fault.
      KeyError: If the event carries no request id.
    """
    request_id = event["requestId"]
    token = f"{sql.hex32(request_id)}{_TOKEN_SUFFIX[name]}"
    return athena.start_query(
        query=query,
        database=database,
        workgroup=cpconfig.ATHENA_WORKGROUP,
        output_location=f"{results}/{name}/",
        fail_reason=messages.QUERY_FAILED,
        client_request_token=token,
    )


def _expected_by_path(bucket: str, files: list[dict]) -> dict[str, int]:
    """Maps each manifest file's full path to its own column count.

    Keyed in the full path form because that is what Athena's path pseudo-column returns; the
    report does the same mapping in reverse for the per-file row counts.

    A file with no probed columns is omitted rather than given a count of zero. Zero would make
    every one of its lines ragged — a fabricated finding of exactly the kind the per-file
    comparison exists to remove — where omission lets the query treat them as unjudgeable, which
    is what they are.

    Args:
      bucket: The source bucket.
      files: The manifest's file entries.

    Returns:
      The path-to-count mapping.

    Raises:
      None.
    """
    return {
        f"s3://{bucket}/{entry['key']}": len(entry["columns"])
        for entry in files
        if entry.get("key") and entry.get("columns")
    }


def _ragged_block(
    event: dict,
    files: list[dict],
    database: str,
    raw_table: str,
    results: str,
    path_filter: str | None,
) -> dict:
    """Starts the ragged query, or returns the degraded block when it cannot be rendered.

    The size guard's refusal is not a terminal: a ragged-row count is not worth losing the null
    ratios, the type consistency and the row counts over. It takes the same degraded shape the
    poll verb produces for a ragged query that failed, so every reader downstream already handles
    it. The code is what the report reads; the reason stays operator-facing text.

    Both file counts are recorded, because they differ whenever a file had no probed columns and
    the error text quotes the mapped one. One field carrying whichever number happened to be in
    scope is how a log stops being evidence.

    Args:
      event: The task input, read for the bucket and request id.
      files: The manifest's file entries.
      database: The target database.
      raw_table: The raw-line temp table.
      results: The request's results prefix.
      path_filter: The single-file predicate, or None for a folder target.

    Returns:
      The ragged block, started or degraded.

    Raises:
      TerminalError: ``query_failed`` when a renderable query cannot be started.
      TransientError: On a retryable Athena fault.
    """
    bucket = event["space"]["bucket"]
    expected = _expected_by_path(bucket, files)
    try:
        query = sql.build_ragged_query(database, raw_table, expected, path_filter)
    except sql.RaggedQueryTooLargeError as err:
        observability.warning(
            "ragged query too large to render",
            step="start-queries",
            reason_code=sql.RAGGED_QUERY_TOO_LARGE,
            detail=str(err),
            files=len(files),
            files_mapped=len(expected),
        )
        return {
            "queryExecutionId": None,
            "status": "not_computed",
            "reasonCode": sql.RAGGED_QUERY_TOO_LARGE,
            "reason": str(err),
            "resultLocation": None,
        }

    return {
        "queryExecutionId": _start("ragged", query, event, database, results),
        "status": "QUEUED",
        "resultLocation": f"{results}/ragged/",
        "reason": None,
    }


@observability.step("start-queries")
def _start_queries(event: dict) -> dict:
    """Renders and submits the three queries, threading their blocks onto the state.

    The profile query is started first and unconditionally. If it cannot even be submitted the
    request is over, and starting the cheap ones first would leave two orphan executions running
    against a request nobody will ever read.

    The unioned columns are right for the external table's schema and for the profile query — a
    column present in only some files still has to be readable. They are not right for the ragged
    comparison, which is per file.

    The path filter is None for a folder target, so every query renders exactly as it did before
    single-file support. For a single-file target it is what makes the report describe the file
    the user picked rather than its parent folder.

    A format with no raw-line table gets a null ragged block rather than a degraded one: rows are
    not line-delimited fields there, so the concept does not apply, and null says "never
    applicable" rather than "we tried and failed" — a distinction the report must not blur. Which
    optional queries were applicable is recorded separately from which were started, because a CSV
    whose ragged query the size guard refused is applicable and not started.

    Args:
      event: The task input.

    Returns:
      The event with the results prefix and the three query blocks attached.

    Raises:
      TerminalError: ``invalid_request`` for a missing field, or ``query_failed`` when a query
        cannot be started.
      TransientError: On a retryable Athena or S3 fault.
    """
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    manifest_key = events.require(event, "manifestKey", reason=messages.INVALID_REQUEST)
    database = events.require(event, "database", reason=messages.INVALID_REQUEST)
    table = events.require(event, "tempTable", reason=messages.INVALID_REQUEST)
    fmt = events.require(event, "format", reason=messages.INVALID_REQUEST)

    manifest = manifest_store.load(bucket, manifest_key)
    files = manifest.get("files") or []
    path_filter = sql.single_file_path(
        bucket, files, events.require(event, "location", reason=messages.INVALID_REQUEST)
    )
    columns = sql.union_columns(files)
    partition_keys = manifest.get("partitionKeys") or []
    results = _results_prefix(event)

    out = dict(event)
    out["resultsPrefix"] = results

    out["profile"] = {
        "queryExecutionId": _start(
            "profile",
            sql.build_profile_query(database, table, columns, fmt, path_filter),
            event,
            database,
            results,
        ),
        "status": "QUEUED",
        "resultLocation": f"{results}/profile/",
        "reason": None,
    }

    raw_table = event.get("tempRawTable")
    if raw_table:
        out["ragged"] = _ragged_block(event, files, database, raw_table, results, path_filter)
    else:
        out["ragged"] = None

    out["duplicates"] = {
        "queryExecutionId": _start(
            "duplicates",
            sql.build_duplicates_query(database, table, columns, partition_keys, path_filter),
            event,
            database,
            results,
        ),
        "status": "QUEUED",
        "resultLocation": f"{results}/duplicates/",
        "reason": None,
    }

    ragged_started = bool((out["ragged"] or {}).get("queryExecutionId"))

    logger.info(
        "started profile=%s ragged=%s duplicates=%s for %s.%s",
        out["profile"]["queryExecutionId"],
        (out["ragged"] or {}).get("queryExecutionId") or "-",
        out["duplicates"]["queryExecutionId"],
        database,
        table,
    )
    started = ["profile", "duplicates"] + (["ragged"] if ragged_started else [])
    observability.info(
        "started queries",
        queries=len(started),
        started=sorted(started),
        ragged_applicable=out["ragged"] is not None,
        ragged_started=ragged_started,
        database=database,
        table=table,
        format=fmt,
    )
    return out


@observability.traced("start-profile-query")
@notify.notifies_on_failure("start-profile-query")
def handler(event, context) -> dict:
    """Starts the three queries and threads their execution ids onward.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    This verb raises no terminal of its own — every one arrives from the field checks or the
    submission. It is recorded anyway, because "which verb stopped the run and why" is the
    question, and a verb that only ever borrows its failures is exactly the one whose silence
    looks like it was never reached.

    Args:
      event: The task input.
      context: The Lambda context, unused.

    Returns:
      The event with the results prefix and the three query blocks attached.

    Raises:
      TerminalError: ``invalid_request`` or ``query_failed``.
      TransientError: On a retryable Athena or S3 fault.
    """
    try:
        return _start_queries(event)
    except TerminalError as err:
        observability.error(
            "start-profile-query failed",
            step="start-queries",
            error_type=type(err).__name__,
            reason=err.reason,
            detail=err.detail,
            tokens=err.tokens or {},
        )
        raise
