"""Shared Athena start+poll helper for execute-ddl (SPEC-070).

Mirrors the app's Athena polling (SPEC-034 ``query.service``): submit the statement
via ``StartQueryExecution``, then poll ``GetQueryExecution`` to a terminal state under
a wall-clock cap. Outcome mapping:

  - ``SUCCEEDED``            → return the queryExecutionId (the caller records success).
  - ``FAILED`` / ``CANCELLED`` → ``TerminalError("ddl_execution_failed", <reason>)``
                              carrying Athena's ``StateChangeReason``.
  - throttling / 5xx        → ``TransientError`` so the Step Function ``Retry`` re-runs
                              the whole verb (NOT terminal — the create hasn't failed).
  - cap exceeded            → ``TerminalError("ddl_timeout", …)`` (the query may still
                              finish in Athena — recorded, not silently lost).

``_now`` / ``_sleep`` are module-level seams so tests can drive a fake clock (no real
sleeping); prod uses ``time.monotonic`` / ``time.sleep``.
"""

import logging
import time

from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError

logger = logging.getLogger()

# Poll cadence + cap. A CREATE EXTERNAL TABLE is fast, but keep generous headroom
# under the Lambda's 300s timeout (locals.tf) — the query may queue behind others in
# the shared workgroup. (SPEC-034's app poller uses a similar interval + max-duration.)
POLL_INTERVAL_SECONDS = 1.0
MAX_POLL_DURATION_SECONDS = 240

_TERMINAL_OK = "SUCCEEDED"
_TERMINAL_FAIL = frozenset({"FAILED", "CANCELLED"})

# Athena/S3 error codes worth a retry (throttling + transient service faults). boto3
# already retries these a few times internally; this is the backstop that hands a
# still-failing transient error to the SFN Retry instead of recording it as terminal.
_TRANSIENT_CODES = frozenset({
    "ThrottlingException",
    "TooManyRequestsException",
    "RequestLimitExceeded",
    "SlowDown",
    "InternalServerException",
    "InternalErrorException",
    "ServiceUnavailable",
    "ServiceUnavailableException",
})

# Patchable clock/sleep seams (tests replace them; prod uses real time).
_now = time.monotonic
_sleep = time.sleep


def _error_code(exc):
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        return (resp.get("Error") or {}).get("Code")
    return None


def _raise_if_transient(exc):
    """Re-raise a throttling/5xx boto error as ``TransientError`` (for the SFN Retry);
    otherwise return so the caller can treat it as a terminal DDL failure."""
    if _error_code(exc) in _TRANSIENT_CODES:
        raise TransientError(f"transient Athena error {_error_code(exc)}") from exc


def run_ddl(*, query, database, workgroup, output_location):
    """Run a DDL statement to a terminal state.

    Returns the queryExecutionId on ``SUCCEEDED``. Raises ``TerminalError``
    (``ddl_execution_failed`` / ``ddl_timeout``) on a failed or timed-out query, or
    ``TransientError`` on a throttling/5xx error.
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
        _raise_if_transient(exc)
        raise TerminalError("ddl_execution_failed", f"could not start query: {exc}") from exc

    qid = started["QueryExecutionId"]
    deadline = _now() + MAX_POLL_DURATION_SECONDS
    while True:
        try:
            resp = athena.get_query_execution(QueryExecutionId=qid)
        except Exception as exc:  # noqa: BLE001 - transient poll error → retry the verb
            _raise_if_transient(exc)
            raise TerminalError("ddl_execution_failed", f"could not poll query {qid}: {exc}") from exc

        status = (resp.get("QueryExecution") or {}).get("Status") or {}
        state = status.get("State")
        if state == _TERMINAL_OK:
            logger.info("query %s SUCCEEDED", qid)
            return qid
        if state in _TERMINAL_FAIL:
            reason = status.get("StateChangeReason") or state
            raise TerminalError("ddl_execution_failed", reason)
        if _now() >= deadline:
            raise TerminalError("ddl_timeout", f"query {qid} did not reach a terminal state within {MAX_POLL_DURATION_SECONDS}s")
        _sleep(POLL_INTERVAL_SECONDS)
