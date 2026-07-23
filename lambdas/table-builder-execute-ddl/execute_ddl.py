"""execute-ddl — the table-builder Step Function's fifth and final task (SPEC-070).

Run the ``infer-schema`` ``CREATE EXTERNAL TABLE IF NOT EXISTS`` DDL (which already
carries the partition-**projection** ``TBLPROPERTIES`` for partitioned sources,
SPEC-069) through **Athena** against the target database, poll to a terminal state,
and return the structured success outcome the SFN ``RecordSuccess`` state shapes.

Because partitions are exposed via **projection**, a partitioned table is queryable
the instant the ``CREATE`` succeeds — there is **NO ``MSCK REPAIR TABLE``** and no
partition-load step (the arc has no ``partition_load_failed`` reason). ``IF NOT
EXISTS`` + the SPEC-068 pre-check make a replay a **no-op success**.

Terminal reasons (recorded by the SFN ``Catch`` → recorded-failure state):
  - ``ddl_execution_failed`` — Athena reached ``FAILED``/``CANCELLED`` or the statement
    couldn't start (carries Athena's ``StateChangeReason``).
  - ``ddl_timeout`` — the poll cap was exceeded (the query may still finish in Athena;
    recorded, not silently lost).
A throttling / 5xx Athena error is raised as ``TransientError`` for the SFN ``Retry``.
"""

import logging

from cpcommon import config, observability
from tbcommon import notify

import athena_run

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one table-build is five invocations, and
# they are only one queryable set if they share a service name (SPEC-127 FR-003). The per-verb
# identity rides as the `verb` field.
observability.init(service="table-builder")


def _results_location(space, actor):
    """The actor's Athena results prefix within the target space (SPEC-070 FR-001 /
    architecture §5): ``s3://{bucket}/{database}/athenaresults/{actor}/``. Personal ⇒
    the user's own prefix; shared ⇒ under the space's DB root, consistent with the
    SPEC-055 shared-results routing (``{database}/athenaresults/{username}/``)."""
    return f"s3://{space['bucket']}/{space['database']}/athenaresults/{actor}/"


# @traced is OUTERMOST, above @notifies_on_failure: the latter catches on its way out,
# so if it were outermost the span would close status="ok" on an invocation that
# actually failed and notified.
@observability.traced("execute-ddl")
@notify.notifies_on_failure("execute")
def handler(event: dict, context) -> dict:
    """SFN entry point: run the CREATE DDL via Athena and shape the success outcome.

    Returns the event with ``status="created"`` on success and notifies the actor the
    table is ready (SPEC-072). A failed/timed-out query raises ``TerminalError`` (the
    actor is notified before the SFN ``Catch`` records it); a throttling error raises
    ``TransientError`` for the SFN ``Retry`` and is not notified.
    """
    space = event["space"]
    actor = event["actor"]
    database = space["database"]

    # One CREATE, idempotent via IF NOT EXISTS; projection ⇒ no MSCK REPAIR. A terminal
    # DDL failure notifies the actor via @notifies_on_failure before the SFN Catch.
    observability.info(
        "running create ddl",
        database=database,
        table=event.get("tableName"),
        workgroup=config.ATHENA_WORKGROUP,
        actor=actor,
    )
    athena_run.run_ddl(
        query=event["ddl"],
        database=database,
        workgroup=config.ATHENA_WORKGROUP,
        output_location=_results_location(space, actor),
    )

    logger.info("created table %s.%s for %s", database, event["tableName"], actor)
    out = dict(event)
    out["status"] = "created"
    # Terminal success — tell the actor the table is ready (SPEC-072 FR-004).
    notify.emit_created(event)
    return out
