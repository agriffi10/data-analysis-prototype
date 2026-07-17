"""Per-verb Athena runner for execute-ddl (SPEC-070).

Thin wrapper over ``cpcommon.athena.run_ddl`` (SPEC-107, where the shared start+poll
loop lives) that binds the table-builder's terminal reason codes
(``ddl_execution_failed`` / ``ddl_timeout``) and exposes ``_now`` / ``_sleep`` and the
poll bounds as module-level seams so tests drive a fake clock with no real sleeping.
The seams are read at call time, so a test patching ``athena_run._now`` still takes
effect through the shared runner.
"""

import time

from cpcommon import athena

POLL_INTERVAL_SECONDS = 1.0
MAX_POLL_DURATION_SECONDS = 240

# Patchable clock/sleep seams (tests replace them; prod uses real time).
_now = time.monotonic
_sleep = time.sleep


def run_ddl(*, query, database, workgroup, output_location):
    """Run the CREATE DDL to a terminal state; see ``cpcommon.athena.run_ddl``.

    Returns the ``QueryExecutionId`` on ``SUCCEEDED``. Raises ``TerminalError``
    (``ddl_execution_failed`` / ``ddl_timeout``) on a failed or timed-out query, or
    ``TransientError`` on a throttling/5xx error.
    """
    return athena.run_ddl(
        query=query,
        database=database,
        workgroup=workgroup,
        output_location=output_location,
        fail_reason="ddl_execution_failed",
        timeout_reason="ddl_timeout",
        now=_now,
        sleep=_sleep,
        poll_interval_seconds=POLL_INTERVAL_SECONDS,
        max_poll_duration_seconds=MAX_POLL_DURATION_SECONDS,
    )
