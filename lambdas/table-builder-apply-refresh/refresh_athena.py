"""Per-verb Athena runner for apply-refresh (SPEC-144).

The sibling of ``table-builder-execute-ddl/athena_run.py``, and separate from it for one
reason: this verb runs TWO statements whose failures mean different things. A failed drop
leaves the table intact and nothing changed; a failed create leaves the table GONE. They
cannot share a reason code, so the reason is bound per call rather than per module.

NAMED ``refresh_athena`` RATHER THAN ``athena_run`` DELIBERATELY. Each verb ships as its
own zip, so the name would be free in Lambda — but ``pytest lambdas/`` imports every verb
into ONE interpreter, where two top-level modules called ``athena_run`` collide and the
first import wins. The second verb then silently calls the first one's runner, with a
different signature. Same reason ``cpcommon`` is a package rather than flat modules.

Exposes the same ``_now`` / ``_sleep`` seams so tests drive a fake clock with no real
sleeping; they are read at call time, so patching them still reaches the shared runner.
"""

import time

from cpcommon import athena

POLL_INTERVAL_SECONDS = 1.0

#: TOTAL poll budget for BOTH statements, not each. execute-ddl's sibling caps one
#: statement at 240 s inside a 300 s function; this verb runs TWO, so inheriting that
#: number would allow 480 s and let Lambda kill the invocation BETWEEN the drop and the
#: create — with the table gone, no notification (the process is dead, so
#: @notifies_on_failure never runs) and only Lambda.Unknown in the record. The caller
#: shares this budget across the pair and keeps room for the post-condition read.
TOTAL_POLL_BUDGET_SECONDS = 200

# Patchable clock/sleep seams (tests replace them; prod uses real time).
_now = time.monotonic
_sleep = time.sleep


def run_ddl(*, query, database, workgroup, output_location, fail_reason, token, budget):
    """Run one DDL statement to a terminal state; see ``cpcommon.athena.run_ddl``.

    ``fail_reason`` is per call — ``drop_failed`` and ``recreate_failed`` describe
    materially different states of the world. The timeout reason stays ``ddl_timeout``
    for both: a timed-out statement may still be running in Athena, so which one it was
    tells the user nothing they can act on, and the record carries the detail.

    ``token`` is Athena's idempotency key and is what makes a Step Functions Retry SAFE on
    a destructive pair: a re-invocation recomputes the same token, so Athena re-attaches to
    the original execution instead of dropping the table a second time. ``budget`` is what
    remains of the shared poll allowance.
    """
    return athena.run_ddl(
        query=query,
        database=database,
        workgroup=workgroup,
        output_location=output_location,
        fail_reason=fail_reason,
        timeout_reason="ddl_timeout",
        now=_now,
        sleep=_sleep,
        poll_interval_seconds=POLL_INTERVAL_SECONDS,
        max_poll_duration_seconds=budget,
        client_request_token=token,
    )
