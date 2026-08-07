"""Shared Athena submit-and-poll runner for control-plane verbs.

Consolidates the byte-identical start-then-poll loop that table-builder's ``execute-ddl``
and table-share's ``create-table`` each carried. Each verb records different reason codes
and drives its own fake clock in tests, so the reason codes, clock, sleep and poll bounds
are all injectable; the per-verb wrappers bind them and keep their patchable seams.

Attributes:
  DEFAULT_POLL_INTERVAL_SECONDS: Delay between polls when a caller supplies none.
  DEFAULT_MAX_POLL_DURATION_SECONDS: Wall-clock poll cap when a caller supplies none.
  _TERMINAL_OK: The Athena state meaning the query finished successfully.
  _TERMINAL_FAIL: The Athena states meaning it will not finish.
"""

import logging
import time

from cpcommon import clients, errors, observability
from cpcommon.errors import TerminalError

logger = logging.getLogger()

DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_MAX_POLL_DURATION_SECONDS = 240

_TERMINAL_OK = "SUCCEEDED"
_TERMINAL_FAIL = frozenset({"FAILED", "CANCELLED"})


def start_query(
    *,
    query,
    database,
    workgroup,
    output_location,
    fail_reason,
    client_request_token=None,
):
    """Submits a query and returns its execution id without polling.

    The counterpart to ``run_ddl`` for work that can outlast a Lambda. ``run_ddl`` holds a
    poll open, which is correct for a CREATE TABLE returning in seconds and fatal for a
    profiling query over 250 GB, since Lambda's ceiling is 900 seconds and no tuning moves
    it. Those callers submit here and let a Step Functions Wait/Choice loop do the waiting,
    which a Standard execution can do for up to a year.

    Args:
      query: The statement to submit.
      database: The Athena/Glue database the statement resolves names in.
      workgroup: The Athena workgroup to run in.
      output_location: ``s3://…`` prefix for THIS query's results. Passed per query
          because a workgroup has exactly one static result location, so per-space
          routing is impossible any other way.
      fail_reason: Terminal reason code for an unstartable query.
      client_request_token: Athena's idempotency key (32-128 chars). SUPPLY IT.
          Without one, a Step Functions ``Retry`` after a transient error that arrived
          AFTER submission starts a SECOND query: the pipeline then polls one execution
          while another runs unwatched, and on an ``UNLOAD`` path the same bug silently
          DOUBLES every row of the output. Athena returns the original execution id for a
          repeated token, so a retry re-attaches instead.

    Returns:
      The ``QueryExecutionId``.

    Raises:
      TerminalError: ``fail_reason`` when the query cannot be started.
      TransientError: on a throttling/5xx Athena error (for the caller's SFN ``Retry``).
    """
    params = {
        "QueryString": query,
        "QueryExecutionContext": {"Database": database},
        "WorkGroup": workgroup,
        "ResultConfiguration": {"OutputLocation": output_location},
    }
    if client_request_token:
        params["ClientRequestToken"] = client_request_token

    try:
        started = clients.athena().start_query_execution(**params)
    except Exception as exc:
        errors.raise_if_transient(exc, "Athena")
        raise TerminalError(fail_reason, f"could not start query: {exc}") from exc

    qid = started["QueryExecutionId"]
    logger.info("started query %s", qid)
    return qid


def describe_query(query_execution_id, *, fail_reason):
    """Reads one query's state in a single call, without waiting, sleeping or looping.

    The read half of the state-machine-driven poll loop; the ``Wait`` state does the waiting.

    Args:
      query_execution_id: The execution to describe.
      fail_reason: Terminal reason code when the execution cannot be described at all.

    Returns:
      ``{"state": <Athena state>, "reason": <StateChangeReason or None>}``. The reason is
      RAW ATHENA TEXT — it belongs in logs and the SFN execution history, never in a
      user-facing message.

    Raises:
      TerminalError: ``fail_reason`` when the describe fails non-transiently.
      TransientError: on a throttling/5xx Athena error.
    """
    try:
        resp = clients.athena().get_query_execution(QueryExecutionId=query_execution_id)
    except Exception as exc:
        errors.raise_if_transient(exc, "Athena")
        raise TerminalError(
            fail_reason, f"could not poll query {query_execution_id}: {exc}"
        ) from exc

    status = (resp.get("QueryExecution") or {}).get("Status") or {}
    return {"state": status.get("State"), "reason": status.get("StateChangeReason")}


def run_ddl(
    *,
    query,
    database,
    workgroup,
    output_location,
    fail_reason,
    timeout_reason,
    now=time.monotonic,
    sleep=time.sleep,
    poll_interval_seconds=DEFAULT_POLL_INTERVAL_SECONDS,
    max_poll_duration_seconds=DEFAULT_MAX_POLL_DURATION_SECONDS,
    client_request_token=None,
):
    """Runs a DDL statement to a terminal state, holding a poll loop open until it settles.

    A state change is observed, never every poll: this loop runs inside one invocation, so
    an event per iteration multiplies within a single span, and consecutive RUNNING
    observations carry nothing. A failure's raw ``StateChangeReason`` is logged in full and
    recorded verbatim as a field — ``TerminalError`` bounds the detail it carries, so the log
    is the only place the whole reason survives, and that text is what names a missing grant.
    It is service text about a statement: schema, never a row of anyone's data.

    Args:
      query: The DDL statement, e.g. ``CREATE EXTERNAL TABLE IF NOT EXISTS …``.
      database: The target Athena/Glue database.
      workgroup: The Athena workgroup to run in.
      output_location: ``s3://…`` result prefix (a DDL create returns no rows).
      fail_reason: Terminal reason code for a FAILED, CANCELLED, unstartable or unpollable
          query.
      timeout_reason: Terminal reason code when the wall-clock poll cap is exceeded. A
          CREATE that runs long enough to hit the cap is a real signal, and would
          otherwise be indistinguishable from a plain Lambda timeout.
      now: Monotonic-clock seam; tests inject a fake clock.
      sleep: Sleep seam; tests inject a no-op that advances the fake clock.
      poll_interval_seconds: Delay between ``GetQueryExecution`` polls.
      max_poll_duration_seconds: Wall-clock cap before raising ``timeout_reason``.
      client_request_token: Athena's idempotency key (32-128 chars). SUPPLY IT for any
          statement whose re-execution is not free. Without one, a Step Functions ``Retry``
          after a transient error that arrived AFTER submission runs the statement a
          SECOND time; with one, Athena returns the original execution id and the retry
          re-attaches. On a DROP + CREATE pair that is the difference between a retry
          re-reading its own work and a retry dropping the table it just rebuilt.

    Returns:
      The ``QueryExecutionId`` on ``SUCCEEDED``.

    Raises:
      TerminalError: ``fail_reason`` on a failed or unstartable query; ``timeout_reason``
          when the poll cap is exceeded. The query may still finish in Athena, so the
          timeout is recorded rather than silently lost.
      TransientError: on a throttling/5xx Athena error (for the SFN ``Retry``).
    """
    athena = clients.athena()
    try:
        params = {
            "QueryString": query,
            "QueryExecutionContext": {"Database": database},
            "WorkGroup": workgroup,
            "ResultConfiguration": {"OutputLocation": output_location},
        }
        if client_request_token:
            params["ClientRequestToken"] = client_request_token
        started = athena.start_query_execution(**params)
    except Exception as exc:
        errors.raise_if_transient(exc, "Athena")
        raise TerminalError(fail_reason, f"could not start query: {exc}") from exc

    qid = started["QueryExecutionId"]
    deadline = now() + max_poll_duration_seconds
    previous_state = None
    polls = 0
    started_at = now()
    while True:
        polls += 1
        try:
            resp = athena.get_query_execution(QueryExecutionId=qid)
        except Exception as exc:
            errors.raise_if_transient(exc, "Athena")
            raise TerminalError(fail_reason, f"could not poll query {qid}: {exc}") from exc

        status = (resp.get("QueryExecution") or {}).get("Status") or {}
        state = status.get("State")
        if state == _TERMINAL_OK:
            logger.info("query %s SUCCEEDED", qid)
            observability.info(
                "query succeeded",
                query_id=qid,
                database=database,
                state=state,
                polls=polls,
                elapsed_ms=(now() - started_at) * 1000.0,
            )
            return qid
        if state in _TERMINAL_FAIL:
            reason = status.get("StateChangeReason") or state
            logger.error("query %s %s: %s", qid, state, reason)
            observability.error(
                "query failed",
                query_id=qid,
                database=database,
                state=state,
                state_change_reason=reason,
                reason=fail_reason,
                polls=polls,
            )
            raise TerminalError(fail_reason, reason)
        if now() >= deadline:
            observability.error(
                "query poll budget exhausted",
                query_id=qid,
                database=database,
                state=state,
                polls=polls,
                budget_seconds=max_poll_duration_seconds,
                reason=timeout_reason,
            )
            raise TerminalError(
                timeout_reason,
                f"query {qid} did not reach a terminal state within {max_poll_duration_seconds}s",
            )
        if state != previous_state:
            observability.info("query state changed", query_id=qid, state=state, polls=polls)
            previous_state = state
        sleep(poll_interval_seconds)
