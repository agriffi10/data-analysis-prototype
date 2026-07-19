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

from cpcommon import athena
from cpcommon.errors import TerminalError
from dqcommon import messages

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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


def _check(event):
    out = dict(event)

    profile = _describe(event.get("profile"))
    out["profile"] = profile
    _check_profile(profile)

    for name in _DEGRADABLE:
        block = _describe(event.get(name))
        if block and block.get("status") in _FAILED_STATES:
            block = _degrade(name, block)
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


def handler(event, context) -> dict:
    """Report every query's status; never wait, sleep, or loop."""
    return _check(dict(event) if isinstance(event, dict) else {})
