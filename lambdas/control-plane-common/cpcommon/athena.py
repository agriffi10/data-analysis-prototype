"""Shared Athena start+poll DDL runner for control-plane verbs (SPEC-107).

Consolidates the byte-identical start→poll loop that table-builder's ``execute-ddl``
(SPEC-070) and table-share's ``create-table`` (SPEC-092) each carried. Submit the
statement via ``StartQueryExecution``, then poll ``GetQueryExecution`` to a terminal
state under a wall-clock cap. Outcome mapping:

  - ``SUCCEEDED``              → return the ``QueryExecutionId``.
  - ``FAILED`` / ``CANCELLED`` → ``TerminalError(fail_reason, <StateChangeReason>)``.
  - throttling / 5xx          → ``TransientError`` so the caller's Step Function
                                ``Retry`` re-runs the whole verb (the create hasn't
                                failed).
  - cap exceeded              → ``TerminalError(timeout_reason, …)`` (the query may
                                still finish in Athena — recorded, not silently lost).

Each verb records different reason codes and drives its own fake clock in tests, so
``run_ddl`` takes ``fail_reason`` / ``timeout_reason`` plus injectable clock/sleep and
poll bounds. The per-verb wrappers (``table-builder-execute-ddl/athena_run.py``,
``tscommon.athena``) bind those and keep their patchable ``_now`` / ``_sleep`` seams.
"""

import logging
import time

from cpcommon import clients, errors
from cpcommon.errors import TerminalError

logger = logging.getLogger()

DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_MAX_POLL_DURATION_SECONDS = 240

_TERMINAL_OK = "SUCCEEDED"
_TERMINAL_FAIL = frozenset({"FAILED", "CANCELLED"})


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
):
    """Run a DDL statement to a terminal state.

    Args:
        query: The DDL statement (e.g. ``CREATE EXTERNAL TABLE IF NOT EXISTS …``).
        database: The target Athena/Glue database.
        workgroup: The Athena workgroup to run in.
        output_location: ``s3://…`` result prefix (a DDL create returns no rows).
        fail_reason: Terminal reason code for a FAILED/CANCELLED/unstartable/unpollable
            query (the verbs use e.g. ``ddl_execution_failed`` vs ``create_failed``).
        timeout_reason: Terminal reason code when the wall-clock poll cap is exceeded.
        now: Monotonic-clock seam (tests inject a fake clock; prod ``time.monotonic``).
        sleep: Sleep seam (tests inject a no-op advancing the fake clock).
        poll_interval_seconds: Delay between ``GetQueryExecution`` polls.
        max_poll_duration_seconds: Wall-clock cap before raising ``timeout_reason``.

    Returns:
        The ``QueryExecutionId`` on ``SUCCEEDED``.

    Raises:
        TerminalError: ``fail_reason`` on a failed/unstartable query; ``timeout_reason``
            when the poll cap is exceeded.
        TransientError: on a throttling/5xx Athena error (for the SFN ``Retry``).
    """
    athena = clients.athena()
    try:
        started = athena.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": database},
            WorkGroup=workgroup,
            ResultConfiguration={"OutputLocation": output_location},
        )
    except Exception as exc:  # noqa: BLE001 - classify: transient → retry, else terminal
        errors.raise_if_transient(exc, "Athena")
        raise TerminalError(fail_reason, f"could not start query: {exc}") from exc

    qid = started["QueryExecutionId"]
    deadline = now() + max_poll_duration_seconds
    while True:
        try:
            resp = athena.get_query_execution(QueryExecutionId=qid)
        except Exception as exc:  # noqa: BLE001 - transient poll error → retry the verb
            errors.raise_if_transient(exc, "Athena")
            raise TerminalError(fail_reason, f"could not poll query {qid}: {exc}") from exc

        status = (resp.get("QueryExecution") or {}).get("Status") or {}
        state = status.get("State")
        if state == _TERMINAL_OK:
            logger.info("query %s SUCCEEDED", qid)
            return qid
        if state in _TERMINAL_FAIL:
            reason = status.get("StateChangeReason") or state
            raise TerminalError(fail_reason, reason)
        if now() >= deadline:
            raise TerminalError(
                timeout_reason,
                f"query {qid} did not reach a terminal state within {max_poll_duration_seconds}s",
            )
        sleep(poll_interval_seconds)
