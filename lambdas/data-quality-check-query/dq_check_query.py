"""data-quality check-query — one describe per query, with no waiting.

The read half of the poll loop. The Step Function does the waiting and this verb only reports.
The poll is not in this Lambda, and that is the whole reason the arc works: polling Athena inside
a Lambda is fine for a create returning in seconds and fatal for a profiling query over hundreds
of gigabytes against Lambda's hard ceiling. A Standard execution can wait for a year.

Where the three queries diverge: a failed or cancelled profile query is a terminal, and one
killed by the account's query-timeout quota is its own terminal. A failed ragged or duplicates
query degrades that figure to not-computed with a reason, and the request still succeeds — a
ragged-row count is not worth losing the null ratios, the type consistency and the row counts
over.

The service name is the control plane, not the function: one data-quality run is nine
invocations, and they are only one queryable set if they share it. The per-verb identity rides as
the ``verb`` field.

Attributes:
  PENDING: The aggregate value the state machine's choice loops on.
  SETTLED: The aggregate value that lets it move on.
  _PENDING_STATES: Athena states meaning the query is still going.
  _FAILED_STATES: Athena states meaning it will not finish.
  _DEGRADABLE: Query keys whose failure degrades the report instead of ending the request.
  _TIMEOUT_MARKERS: Athena's wording when the account-level query-timeout quota kills a query.
    That quota is an account and region service quota, not a workgroup setting: there is no
    workgroup timeout field to raise and no config value to look for, and the limit moves only via
    a support request. Anyone hunting for a Terraform attribute is looking for something that does
    not exist; the infra module carries the same warning beside the workgroup.
"""

import logging

from cpcommon import athena, observability
from cpcommon.errors import TerminalError
from dqcommon import messages, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="data-quality")

PENDING = "RUNNING"
SETTLED = "SUCCEEDED"

_PENDING_STATES = frozenset({"QUEUED", "RUNNING"})
_FAILED_STATES = frozenset({"FAILED", "CANCELLED"})

_DEGRADABLE = ("ragged", "duplicates")

_TIMEOUT_MARKERS = ("timeout", "timed out", "exceeded the limit")


def _is_timeout(reason) -> bool:
    """Reports whether Athena's raw reason indicates the query-timeout quota fired.

    Matched on text because Athena reports the quota kill as a failed query with a reason string
    rather than a distinct state. The consequence of a miss is mild and one-way: the user gets the
    generic failure message instead of the size-specific one — less useful, never a wrong outcome,
    and the raw reason is in the logs either way.

    Args:
      reason: Athena's raw state-change reason, or None.

    Returns:
      True when any known marker appears.

    Raises:
      None.
    """
    lowered = (reason or "").lower()
    return any(marker in lowered for marker in _TIMEOUT_MARKERS)


def _describe(block):
    """Refreshes one query block from Athena, leaving already-settled blocks alone.

    A block that has succeeded, or already degraded, is returned untouched: re-describing would
    burn an API call per poll, and re-deciding a degraded figure could flip it back.

    Args:
      block: The state's block for one query, or None when the query was never submitted.

    Returns:
      The refreshed block, or the input unchanged.

    Raises:
      TerminalError: When the execution cannot be described at all.
      TransientError: On a retryable Athena fault.
    """
    if not block or not block.get("queryExecutionId"):
        return block
    if block.get("status") not in _PENDING_STATES:
        return block

    described = athena.describe_query(
        block["queryExecutionId"], fail_reason=messages.QUERY_FAILED
    )
    refreshed = dict(block)
    refreshed["status"] = described["state"]
    refreshed["reason"] = described["reason"]
    return refreshed


def _degrade(name, block):
    """Turns a failed ragged or duplicates query into a not-computed figure.

    The raw Athena reason is kept on the block for the report to turn into wording and for the
    execution history. It is not a user-facing string.

    Args:
      name: The query's name, for the log line.
      block: The failed block.

    Returns:
      The degraded block.

    Raises:
      None.
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
    """Raises the terminal for a failed profile query, whose failure ends the request.

    The friendly message carries no raw Athena text — the state-change reason stays in CloudWatch
    and the execution history. It goes in the terminal's detail, which is exactly where that
    boundary sits: recorded for an operator, never shown to a user.

    Args:
      block: The profile query's block.

    Returns:
      None, when the query has not failed.

    Raises:
      TerminalError: ``query_timeout`` when the quota fired, ``query_failed`` otherwise.
    """
    status = (block or {}).get("status")
    if status not in _FAILED_STATES:
        return

    reason = block.get("reason")
    if _is_timeout(reason):
        raise TerminalError(messages.QUERY_TIMEOUT, f"profile query timed out: {reason}")
    raise TerminalError(messages.QUERY_FAILED, f"profile query {status}: {reason}")


def _aggregate(blocks):
    """Collapses the three statuses into the one value the state machine's choice branches on.

    An aggregate rather than three choice rules, because the ragged block is null for formats that
    are not line-delimited, and a choice rule reading through a null raises a runtime error a
    choice state cannot catch — so the execution would die without reaching the notify state and
    the user would be told nothing at all, the worst failure mode in this pipeline. Step Functions
    does not document short-circuit evaluation of its boolean combinators, so a null guard is not
    reliably safe either. The "is anything still running" decision is made here, in Python, where
    all three statuses already are and a null is simply a null.

    Args:
      blocks: The three query blocks, any of which may be None.

    Returns:
      The pending or settled value.

    Raises:
      None.
    """
    return PENDING if any(b and b.get("status") in _PENDING_STATES for b in blocks) else SETTLED


def _settled(status) -> bool:
    """Reports whether a query will never be described again.

    Args:
      status: The query's current status.

    Returns:
      True once the query has reached a state the poll will not revisit.

    Raises:
      None.
    """
    return bool(status) and status not in _PENDING_STATES


def _narrate(name, before, after) -> None:
    """Emits at most one event, and only when this poll is the one that settled the query.

    The poll is the hazard, not the query. This verb is invoked from a wait loop for as long as
    the profiling query runs — minutes to tens of minutes by design, since the poll was moved into
    the state machine to escape Lambda's ceiling. Anything said on every poll is multiplied many
    times over, and repeated copies of "still running" are not information: the span pair already
    records that a poll happened. So a transition into a pending state says nothing either, and an
    already-settled block cannot re-emit because the describe step stops describing it.

    Args:
      name: The query's name.
      before: The block as it was before this poll.
      after: The block as it is now.

    Returns:
      None.

    Raises:
      None.
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
    """Refreshes all three blocks as one step.

    One child span per invocation, not one per query: three spans on a poll that repeats many
    times is a large number of extra events for a duration an operator reads as a single number
    anyway — how long Athena took to answer this poll.

    Args:
      event: The task input, carrying the three query blocks.

    Returns:
      The three refreshed blocks.

    Raises:
      TerminalError: When an execution cannot be described at all.
      TransientError: On a retryable Athena fault.
    """
    return {
        "profile": _describe(event.get("profile")),
        "ragged": _describe(event.get("ragged")),
        "duplicates": _describe(event.get("duplicates")),
    }


def _check(event):
    """Refreshes every query, degrades the degradable ones, and aggregates the verdict.

    Args:
      event: The task input.

    Returns:
      The event with the refreshed blocks and the aggregate status attached.

    Raises:
      TerminalError: ``query_failed`` or ``query_timeout`` when the profile query failed.
      TransientError: On a retryable Athena fault.
    """
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


@observability.traced("check-query")
@notify.notifies_on_failure("check-query")
def handler(event, context) -> dict:
    """Reports every query's status. Never waits, sleeps or loops.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The task input, carrying the three query blocks.
      context: The Lambda context, unused.

    Returns:
      The event with the refreshed blocks and the aggregate status attached.

    Raises:
      TerminalError: ``query_failed`` or ``query_timeout`` when the profile query failed.
      TransientError: On a retryable Athena fault.
    """
    return _check(dict(event) if isinstance(event, dict) else {})
