"""data-quality start-profile-query — submit the three checks, wait for none of them.

Starts the three separately-degradable queries (SPEC-111 FR-003) and returns their
execution ids. It NEVER WAITS: the poll lives in the state machine, because a profiling
query over 250 GB routinely outruns Lambda's 900-second ceiling while a Standard Step
Functions execution can wait for up to a year.

The three, and why they are three:

  - **profile** over the typed table — the backbone. Failure is terminal.
  - **ragged** over the raw-line table — CSV only. Failure degrades to `not_computed`.
  - **duplicates** over the typed table — failure degrades to `not_computed`.

Every submission carries a ``ClientRequestToken`` derived from the requestId. Without one,
a Step Functions Retry after a transient error that arrived POST-SUBMISSION would start a
SECOND query, and the pipeline would poll one execution while another ran unwatched.
"""

import logging

from cpcommon import athena, events, observability
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError
from dqcommon import manifest as manifest_store
from dqcommon import messages, notify, sql

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one data-quality run is nine
# invocations, and they are only one queryable set if they share a service name
# (SPEC-127 FR-003). The per-verb identity rides as the `verb` field on each span.
observability.init(service="data-quality")

#: Per-query token suffixes. Distinct so the three submissions do not collide with each
#: other, still pure functions of requestId so a retry re-attaches to the SAME executions.
#: Athena requires 32-128 characters; hex32 + a suffix sits comfortably inside that.
_TOKEN_SUFFIX = {"profile": "-profile", "ragged": "-ragged", "duplicates": "-dupes"}


def _results_prefix(event: dict) -> str:
    """Return the ``s3://…/athenaresults/`` prefix THIS request's results land in.

    Per query, not per workgroup: the workgroup has exactly one static result location, so
    routing results into the requesting space is impossible any other way (SPEC-108 FR-003).

    A SHARED-SPACE check lands under ``{spaceName}/athenaresults/`` in the shared bucket —
    a NEW prefix convention introduced deliberately here, where until now athenaresults/
    existed only as ``{username}/athenaresults/`` in the user-space bucket. It is safe
    because SPEC-110's listing exclusion already covers ``athenaresults/`` in BOTH buckets,
    so these result files can never be picked up as source data by a later check.
    """
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    space_root = events.require(event, "space", "prefix", reason=messages.INVALID_REQUEST).strip("/")
    request_id = events.require(event, "requestId", reason=messages.INVALID_REQUEST)
    return f"s3://{bucket}/{space_root}/athenaresults/data-quality/{request_id}"


def _start(name: str, query: str, event: dict, database: str, results: str) -> str:
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
    """Manifest files -> ``{"s3://bucket/key": that file's own column count}`` (SPEC-142).

    Keyed in the full ``s3://`` form because that is what Athena's ``"$path"``
    pseudo-column returns; ``report._strip_scheme`` does the same mapping in reverse for
    the per-file row counts.

    A FILE WITH NO PROBED COLUMNS IS OMITTED rather than given a count of zero. Zero would
    make every one of its lines ragged — a fabricated finding of exactly the kind this spec
    exists to remove — where omission lets the query's ELSE branch treat them as
    unjudgeable, which is what they are.
    """
    return {
        f"s3://{bucket}/{entry['key']}": len(entry["columns"])
        for entry in files
        if entry.get("key") and entry.get("columns")
    }


def _ragged_block(
    event: dict, files: list[dict], database: str, raw_table: str, results: str
) -> dict:
    """Start the ragged query, or return the degraded block when it cannot be rendered.

    The guard's refusal is NOT a terminal (SPEC-111 FR-003): a ragged-row count is not
    worth losing the null ratios, the type consistency and the row counts over. It takes
    the same ``not_computed`` shape check-query produces for a ragged query that failed,
    so every reader downstream — the poll's ``_describe``, assemble-report's result fetch,
    the report's wording — already handles it.
    """
    bucket = event["space"]["bucket"]
    try:
        query = sql.build_ragged_query(database, raw_table, _expected_by_path(bucket, files))
    except sql.RaggedQueryTooLargeError as err:
        observability.warning(
            "ragged query too large to render",
            step="start-queries",
            reason_code=sql.RAGGED_QUERY_TOO_LARGE,
            detail=str(err),
            files=len(files),
        )
        return {
            "queryExecutionId": None,
            "status": "not_computed",
            # The code the report reads; `reason` stays operator-facing text, as it does on
            # a degraded block from check-query.
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
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    manifest_key = events.require(event, "manifestKey", reason=messages.INVALID_REQUEST)
    database = events.require(event, "database", reason=messages.INVALID_REQUEST)
    table = events.require(event, "tempTable", reason=messages.INVALID_REQUEST)
    fmt = events.require(event, "format", reason=messages.INVALID_REQUEST)

    manifest = manifest_store.load(bucket, manifest_key)
    files = manifest.get("files") or []
    # The UNION is right for the external table's schema and for the profile query — a
    # column present in only some files still has to be readable. It is NOT right for the
    # ragged comparison, which is per file (SPEC-142).
    columns = sql.union_columns(files)
    partition_keys = manifest.get("partitionKeys") or []
    results = _results_prefix(event)

    out = dict(event)
    out["resultsPrefix"] = results

    # The profile query is started FIRST and unconditionally. If it cannot even be
    # submitted the request is over, and starting the cheap ones first would leave two
    # orphan executions running against a request nobody will ever read.
    out["profile"] = {
        "queryExecutionId": _start(
            "profile",
            sql.build_profile_query(database, table, columns, fmt),
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
        out["ragged"] = _ragged_block(event, files, database, raw_table, results)
    else:
        # JSON/Parquet have no raw-line table: rows are not line-delimited fields, so the
        # concept does not apply. null (not a not_computed block) says "never applicable"
        # rather than "we tried and failed" — a distinction the report must not blur.
        out["ragged"] = None

    out["duplicates"] = {
        "queryExecutionId": _start(
            "duplicates",
            sql.build_duplicates_query(database, table, columns, partition_keys),
            event,
            database,
            results,
        ),
        "status": "QUEUED",
        "resultLocation": f"{results}/duplicates/",
        "reason": None,
    }

    # A ragged block exists but carries no execution id when the size guard refused to
    # render the query (SPEC-142 FR-003) — applicable, but never submitted.
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
        # WHICH of the optional ones were applicable, not merely how many ran: `ragged` is
        # null for JSON/Parquet because the concept does not apply there, and that is a
        # different thing from a ragged check that was attempted and degraded. Applicable
        # and started are separate fields for the same reason — a CSV whose ragged query
        # the size guard refused is applicable and not started.
        started=sorted(started),
        ragged_applicable=out["ragged"] is not None,
        ragged_started=ragged_started,
        database=database,
        table=table,
        format=fmt,
    )
    return out


# @traced is OUTERMOST, above @notifies_on_failure, deliberately: notifies_on_failure
# catches on its way out, so if it were outermost the span would close status="ok" on an
# invocation that actually failed and notified. Outermost traced sees the exception the
# handler really raised.
@observability.traced("start-profile-query")
@notify.notifies_on_failure("start-profile-query")
def handler(event, context) -> dict:
    """Start the three queries and thread their execution ids onward."""
    try:
        return _start_queries(event)
    except TerminalError as err:
        # This verb raises no terminal of its own — every one arrives from `events.require`
        # or `athena.start_query`. It is narrated anyway, because "which verb stopped the run
        # and why" is the question, and a verb that only ever borrows its failures is exactly
        # the one whose silence looks like it was never reached.
        observability.error(
            "start-profile-query failed",
            step="start-queries",
            error_type=type(err).__name__,
            reason=err.reason,
            detail=err.detail,
            tokens=err.tokens or {},
        )
        raise
