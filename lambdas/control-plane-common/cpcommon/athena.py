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


def start_query(
    *,
    query,
    database,
    workgroup,
    output_location,
    fail_reason,
    client_request_token=None,
):
    """Submit a query and return its ``QueryExecutionId`` WITHOUT polling (SPEC-111).

    The counterpart to ``run_ddl`` for work that can outlast a Lambda. ``run_ddl`` holds a
    poll open, which is correct for a ``CREATE TABLE`` returning in seconds and FATAL for
    a profiling query over 250 GB: Lambda's ceiling is 900 seconds and no amount of tuning
    moves it. Those callers submit here and let a Step Functions ``Wait``/``Choice`` loop
    do the waiting, which a Standard execution can do for up to a year.

    Args:
        query: The statement to submit.
        database: The Athena/Glue database the statement resolves names in.
        workgroup: The Athena workgroup to run in.
        output_location: ``s3://…`` prefix for THIS query's results. Passed per query
            because a workgroup has exactly one static result location, so per-space
            routing is impossible any other way (SPEC-108 FR-003).
        fail_reason: Terminal reason code for an unstartable query.
        client_request_token: Athena's idempotency key (32-128 chars). SUPPLY IT.
            Without one, a Step Functions ``Retry`` after a transient error that arrived
            AFTER submission starts a SECOND query: the pipeline then polls one execution
            while another runs unwatched, and on the sibling file-converter's ``UNLOAD``
            path the same bug silently DOUBLES every row of the output. Athena returns the
            original execution id for a repeated token, so a retry re-attaches instead.

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
    except Exception as exc:  # noqa: BLE001 - classify: transient → retry, else terminal
        errors.raise_if_transient(exc, "Athena")
        raise TerminalError(fail_reason, f"could not start query: {exc}") from exc

    qid = started["QueryExecutionId"]
    logger.info("started query %s", qid)
    return qid


def describe_query(query_execution_id, *, fail_reason):
    """Return one query's ``{state, reason}`` — one ``GetQueryExecution``, no polling.

    The read half of the state-machine-driven poll loop (SPEC-111 FR-004). It does not
    wait, sleep, or loop; the ``Wait`` state does that.

    Args:
        query_execution_id: The execution to describe.
        fail_reason: Terminal reason code when the execution cannot be described at all.

    Returns:
        ``{"state": <Athena state>, "reason": <StateChangeReason or None>}``. The reason is
        RAW ATHENA TEXT — it belongs in logs and the SFN execution history, never in a
        user-facing message (SPEC-106 FR-008).

    Raises:
        TerminalError: ``fail_reason`` when the describe fails non-transiently.
        TransientError: on a throttling/5xx Athena error.
    """
    try:
        resp = clients.athena().get_query_execution(QueryExecutionId=query_execution_id)
    except Exception as exc:  # noqa: BLE001 - transient poll error → retry the verb
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
            # LOG IN FULL — TerminalError bounds the detail it carries, so this log is the
            # ONLY place the whole Athena reason survives. It can echo a large fragment of
            # the statement, and this arc generates wide DDL.
            logger.error("query %s %s: %s", qid, state, reason)
            raise TerminalError(fail_reason, reason)
        if now() >= deadline:
            raise TerminalError(
                timeout_reason,
                f"query {qid} did not reach a terminal state within {max_poll_duration_seconds}s",
            )
        sleep(poll_interval_seconds)
