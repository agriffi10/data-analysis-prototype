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

from cpcommon import athena, config as cpconfig, events
from cpcommon import observability
from dqcommon import manifest as manifest_store, messages, notify, sql

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


def _start_queries(event: dict) -> dict:
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    manifest_key = events.require(event, "manifestKey", reason=messages.INVALID_REQUEST)
    database = events.require(event, "database", reason=messages.INVALID_REQUEST)
    table = events.require(event, "tempTable", reason=messages.INVALID_REQUEST)
    fmt = events.require(event, "format", reason=messages.INVALID_REQUEST)

    manifest = manifest_store.load(bucket, manifest_key)
    columns = sql.union_columns(manifest.get("files") or [])
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
        out["ragged"] = {
            "queryExecutionId": _start(
                "ragged",
                sql.build_ragged_query(database, raw_table, len(columns)),
                event,
                database,
                results,
            ),
            "status": "QUEUED",
            "resultLocation": f"{results}/ragged/",
            "reason": None,
        }
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

    logger.info(
        "started profile=%s ragged=%s duplicates=%s for %s.%s",
        out["profile"]["queryExecutionId"],
        (out["ragged"] or {}).get("queryExecutionId", "-"),
        out["duplicates"]["queryExecutionId"],
        database,
        table,
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
    return _start_queries(event)
