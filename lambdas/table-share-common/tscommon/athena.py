"""Per-verb Athena runner for table-share's recipient CREATE.

A thin wrapper over ``cpcommon.athena.run_ddl`` that binds table-share's terminal reason codes
and exposes the clock, sleep and poll bounds as module-level seams so tests drive a fake clock
with no real sleeping. The seams are read at call time, so a test patching them still takes
effect through the shared runner.

Attributes:
  POLL_INTERVAL_SECONDS: Delay between polls.
  MAX_POLL_DURATION_SECONDS: Wall-clock poll cap.
  _now: Monotonic-clock seam; tests replace it.
  _sleep: Sleep seam; tests replace it.
"""

import time

from cpcommon import athena

POLL_INTERVAL_SECONDS = 1.0
MAX_POLL_DURATION_SECONDS = 240

_now = time.monotonic
_sleep = time.sleep


def run_ddl(*, query, database, workgroup, output_location):
    """Runs the recipient CREATE DDL to a terminal state under table-share's reason codes.

    Args:
      query: The DDL statement.
      database: The recipient's Athena/Glue database.
      workgroup: The Athena workgroup to run in.
      output_location: The ``s3://`` results prefix.

    Returns:
      The ``QueryExecutionId`` on success.

    Raises:
      TerminalError: ``create_failed`` on a failed query, ``create_timeout`` when the poll cap
        is exceeded.
      TransientError: On a throttling or 5xx Athena error.
    """
    return athena.run_ddl(
        query=query,
        database=database,
        workgroup=workgroup,
        output_location=output_location,
        fail_reason="create_failed",
        timeout_reason="create_timeout",
        now=_now,
        sleep=_sleep,
        poll_interval_seconds=POLL_INTERVAL_SECONDS,
        max_poll_duration_seconds=MAX_POLL_DURATION_SECONDS,
    )
