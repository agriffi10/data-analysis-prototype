"""execute-ddl — the table-builder Step Function's fifth and final task.

Runs infer-schema's ``CREATE EXTERNAL TABLE IF NOT EXISTS`` DDL — which already carries the
partition-projection properties for partitioned sources — through Athena against the target
database, polls to a terminal state, and returns the structured success outcome the success
state shapes.

Because partitions are exposed via projection, a partitioned table is queryable the instant
the CREATE succeeds: there is no repair step and no partition-load reason code. ``IF NOT
EXISTS`` plus the pre-check make a replay a no-op success.

The service name is the control plane, not the function, so one build's five invocations stay
one queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  athena_run: The table-builder's DDL runner, with this plane's reason codes bound. Held at
    module level so a timing test can replace its ``_now`` and ``_sleep`` seams, which is the
    whole reason the per-plane wrapper it replaced existed.
"""

import logging

from cpcommon import athena, config, observability
from tbcommon import notify
from tbcommon.results import results_location

athena_run = athena.bound_runner("ddl_execution_failed", "ddl_timeout")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")


@observability.step("athena-run-ddl")
def _run_create_ddl(query: str, database: str, output_location: str) -> None:
    """Runs the CREATE statement through Athena and polls it to a terminal state.

    A wrapper purely so the Athena round trip — which is all of this verb's latency and the only
    part that can hang — gets a child span of its own. The runner it calls is a bound INSTANCE
    shared with data-quality and table-share, so the step goes here rather than on the runner:
    decorating that method would silently instrument two other planes.

    **Call bound: exactly once per invocation**, unconditionally, from this verb alone.

    The span is NOT named ``execute-ddl``. That is already this verb's root span, and a child
    sharing its parent's name means the one query an operator runs — filter on the span name —
    returns the verb's total and the Athena call mixed together, with the durations double
    counted. The name is the operation instead.

    Args:
      query: The rendered CREATE statement.
      database: The target database.
      output_location: Where Athena writes the statement's output.

    Returns:
      None.

    Raises:
      TerminalError: ``ddl_execution_failed`` or ``ddl_timeout``, from the bound runner.
      TransientError: On a throttling or 5xx Athena error.
    """
    athena_run.run_ddl(
        query=query,
        database=database,
        workgroup=config.ATHENA_WORKGROUP,
        output_location=output_location,
    )


@observability.traced("execute-ddl")
@notify.notifies_on_failure("execute")
def handler(event: dict, context) -> dict:
    """Step Functions entry point: runs the CREATE DDL and shapes the success outcome.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    The mode is defaulted on the way out because the success state reads it and a Pass state's
    JSONPath raises an uncatchable runtime error on an absent key. Only a create reaches this
    verb, so defaulting here closes the one window where the key can be missing — an execution
    that starts after the state machine deploys but before validate-authorize's code does,
    since the two run as separate workflows, which would otherwise die after the table was
    created and the actor was told so.

    Args:
      event: The task input, carrying the space, actor, table name and rendered DDL.
      context: The Lambda context, unused.

    Returns:
      The event with a created status, after notifying the actor that the table is ready.

    Raises:
      TerminalError: ``ddl_execution_failed`` when Athena reached FAILED or CANCELLED or the
        statement could not start, carrying Athena's own reason; ``ddl_timeout`` when the poll
        cap was exceeded. Both notify the actor before the SFN Catch records them.
      TransientError: On a throttling or 5xx Athena error, passed through un-notified for the
        SFN Retry.
    """
    space = event["space"]
    actor = event["actor"]
    database = space["database"]

    observability.info(
        "running create ddl",
        database=database,
        table=event.get("tableName"),
        workgroup=config.ATHENA_WORKGROUP,
        actor=actor,
    )
    _run_create_ddl(event["ddl"], database, results_location(space, actor))

    logger.info("created table %s.%s for %s", database, event["tableName"], actor)
    out = dict(event)
    out["status"] = "created"
    out.setdefault("mode", "create")
    notify.emit_created(event)
    return out
