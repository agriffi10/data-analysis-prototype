"""data-quality check-query — one GetQueryExecution per query, no waiting.

The read half of the poll loop. The Step Function does the waiting
(``StartProfileQuery -> WaitForQuery(30s) -> CheckQuery -> Choice``), and this verb only
reports. THE POLL IS NOT IN THIS LAMBDA, and that is the whole reason the arc works:
table-builder's execute-ddl polls Athena inside a 300-second Lambda, which is fine for a
CREATE TABLE returning in seconds and fatal for a profiling query over 250 GB against
Lambda's hard 900-second ceiling. A Standard Step Functions execution can wait for a year.

WHERE THE THREE QUERIES DIVERGE (FR-004):

  - **profile** — FAILED/CANCELLED is a TERMINAL ``query_failed``; a query killed by the
    account's DML query-timeout quota is a terminal ``query_timeout``.
  - **ragged** and **duplicates** — failure or timeout DEGRADES that figure to
    ``not_computed`` with a reason, and the request still SUCCEEDS. A ragged-row count is
    not worth losing the null ratios, the type consistency and the row counts over.
"""

import logging

from cpcommon import athena, observability
from cpcommon.errors import TerminalError
from dqcommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one data-quality run is nine
# invocations, and they are only one queryable set if they share a service name
# (SPEC-127 FR-003). The per-verb identity rides as the `verb` field on each span.
observability.init(service="data-quality")

#: The state-machine Choice loops while this is RUNNING (see ``_aggregate``).
PENDING = "RUNNING"
SETTLED = "SUCCEEDED"

_PENDING_STATES = frozenset({"QUEUED", "RUNNING"})
_FAILED_STATES = frozenset({"FAILED", "CANCELLED"})

#: Query keys whose failure degrades the report instead of ending the request.
_DEGRADABLE = ("ragged", "duplicates")

# Athena's wording when the account-level DML query-timeout Service Quota kills a query.
#
# THE QUOTA IS AN ACCOUNT/REGION SERVICE QUOTA, NOT A WORKGROUP SETTING. There is no
# workgroup timeout field to raise and no config value to look for — the limit (30 minutes
# by default, raisable to 240) moves only via a support request. Anyone hunting for a
# Terraform attribute is looking for something that does not exist; the infra module's
# athena.tf carries the same warning beside the workgroup.
_TIMEOUT_MARKERS = ("timeout", "timed out", "exceeded the limit")


def _is_timeout(reason) -> bool:
    """True when Athena's raw reason indicates the DML query-timeout quota fired.

    Matched on TEXT because Athena reports the quota kill as a FAILED query with a reason
    string rather than a distinct state. The consequence of a miss is mild and one-way:
    the user gets ``query_failed`` ("contact the Administrator") instead of
    ``query_timeout`` ("that source is too large") — a less useful message, never a wrong
    outcome, and the raw reason is in the logs either way.
    """
    lowered = (reason or "").lower()
    return any(marker in lowered for marker in _TIMEOUT_MARKERS)


def _describe(block):
    """Refresh one query block from Athena, leaving already-settled blocks alone."""
    if not block or not block.get("queryExecutionId"):
        return block
    if block.get("status") not in _PENDING_STATES:
        # Already SUCCEEDED, or already degraded to not_computed. Re-describing would burn
        # an API call per poll, and re-deciding a not_computed could flip it back.
        return block

    described = athena.describe_query(
        block["queryExecutionId"], fail_reason=messages.QUERY_FAILED
    )
    refreshed = dict(block)
    refreshed["status"] = described["state"]
    refreshed["reason"] = described["reason"]
    return refreshed


def _degrade(name, block):
    """Turn a failed ragged/duplicates query into a not_computed figure.

    The raw Athena reason is kept ON THE BLOCK for SPEC-112 to turn into report wording
    and for the execution history. It is not a user-facing string (SPEC-106 FR-008).
    """
    logger.warning(
        "%s query %s did not complete (%s) — degrading to not_computed",
        name,
        block.get("queryExecutionId"),
        block.get("reason") or block.get("status"),
    )
    degraded = dict(block)
    degraded["status"] = "not_computed"
    degraded["reason"] = block.get("reason") or block.get("status")
    return degraded


def _check_profile(block):
    """Raise the terminal for a failed profile query. Its failure ends the request."""
    status = (block or {}).get("status")
    if status not in _FAILED_STATES:
        return

    reason = block.get("reason")
    # The friendly message carries NO raw Athena text — the StateChangeReason stays in
    # CloudWatch and the SFN execution history. It goes in the TerminalError DETAIL, which
    # is exactly where that boundary sits: recorded for an operator, never shown to a user
    # (SPEC-106 FR-008; dqcommon.messages owns the wording they do see).
    if _is_timeout(reason):
        raise TerminalError(messages.QUERY_TIMEOUT, f"profile query timed out: {reason}")
    raise TerminalError(messages.QUERY_FAILED, f"profile query {status}: {reason}")


def _aggregate(blocks):
    """Collapse the three statuses into the ONE value the Choice branches on.

    WHY AN AGGREGATE RATHER THAN THREE CHOICE RULES: ``ragged`` is null for JSON/Parquet,
    and a Choice rule reading ``$.ragged.status`` on a null raises States.Runtime — which
    a Choice state CANNOT Catch, so the execution would die without reaching NotifyFailure
    and the user would be told nothing at all, the worst failure mode in this pipeline.
    Step Functions does not document short-circuit evaluation of ``And``, so an ``IsNull``
    guard is not reliably safe either. The "is anything still running" decision is made
    here, in Python, where all three statuses already are and a null is simply a null.
    """
    return PENDING if any(b and b.get("status") in _PENDING_STATES for b in blocks) else SETTLED


def _settled(status) -> bool:
    """True once a query will never be described again — the only time worth narrating."""
    return bool(status) and status not in _PENDING_STATES


def _narrate(name, before, after) -> None:
    """Emit AT MOST ONE event, and only when this poll is the one that settled the query.

    THE POLL IS THE HAZARD, not the query (SPEC-132 FR-005). This verb is invoked from a
    30-second Wait loop for as long as the profiling query runs — minutes to tens of minutes
    by design, since the poll was moved into the state machine to escape Lambda's 900-second
    ceiling. Anything said on every poll is multiplied by fifty, and fifty copies of "still
    running" is not information: the span.start/span.end pair already records that a poll
    happened.

    So a transition into a PENDING state (QUEUED -> RUNNING) says nothing either, and an
    already-settled block cannot re-emit because :func:`_describe` stops describing it.

    ``reason`` is Athena's ``StateChangeReason`` — permitted, and the thing an operator
    actually needs (FR-004). It is schema-and-service text, never a result row.
    """
    before_status = (before or {}).get("status")
    after_status = (after or {}).get("status")
    if after_status == before_status or not _settled(after_status):
        return

    reason = (after or {}).get("reason")
    fields = {
        "query": name,
        "query_id": (after or {}).get("queryExecutionId"),
        "status": after_status,
        "reason": reason,
    }
    if after_status == "not_computed":
        # Degraded, not failed: the request still succeeds, and losing a ragged-row count is
        # not worth losing the null ratios and row counts over.
        observability.warning("query degraded", **fields)
    elif after_status in _FAILED_STATES:
        if name == "profile" and _is_timeout(reason):
            observability.error("query timed out", **{**fields, "status": "query_timeout"})
        else:
            observability.error("query failed", **fields)
    else:
        observability.info("query settled", **fields)


@observability.step("describe-queries")
def _describe_all(event):
    """Refresh all three blocks as ONE step.

    One child span per invocation, not one per query: three spans on a poll that repeats
    fifty times is a hundred and fifty extra events for a duration an operator reads as a
    single number anyway — "how long did Athena take to answer this poll".
    """
    return {
        "profile": _describe(event.get("profile")),
        "ragged": _describe(event.get("ragged")),
        "duplicates": _describe(event.get("duplicates")),
    }


def _check(event):
    out = dict(event)
    described = _describe_all(event)

    profile = described["profile"]
    out["profile"] = profile
    _narrate("profile", event.get("profile"), profile)
    _check_profile(profile)

    for name in _DEGRADABLE:
        block = described[name]
        if block and block.get("status") in _FAILED_STATES:
            block = _degrade(name, block)
        _narrate(name, event.get(name), block)
        out[name] = block

    out["queryStatus"] = _aggregate([out["profile"], out.get("ragged"), out.get("duplicates")])
    logger.info(
        "poll: profile=%s ragged=%s duplicates=%s -> %s",
        (out["profile"] or {}).get("status"),
        (out.get("ragged") or {}).get("status", "n/a"),
        (out.get("duplicates") or {}).get("status"),
        out["queryStatus"],
    )
    return out


# @traced is OUTERMOST, above @notifies_on_failure, deliberately: notifies_on_failure
# catches on its way out, so if it were outermost the span would close status="ok" on an
# invocation that actually failed and notified. Outermost traced sees the exception the
# handler really raised.
@observability.traced("check-query")
@notify.notifies_on_failure("check-query")
def handler(event, context) -> dict:
    """Report every query's status; never wait, sleep, or loop."""
    return _check(dict(event) if isinstance(event, dict) else {})
