"""execute-ddl — the table-builder Step Function's fifth and final task.

Runs infer-schema's ``CREATE EXTERNAL TABLE IF NOT EXISTS`` DDL — which already carries the
partition-projection properties for partitioned sources — through Athena against the target
database, polls to a terminal state, confirms the table now standing is the one this request
declared, and returns the structured success outcome the success state shapes.

Because partitions are exposed via projection, a partitioned table is queryable the instant
the CREATE succeeds: there is no repair step and no partition-load reason code.

``IF NOT EXISTS`` MAKES A REPLAY A NO-OP SUCCESS, AND THAT IS ALSO WHAT HID A LOST RACE.
A create takes no lock and the Pipe starts executions ``FIRE_AND_FORGET``, so two creates of
one name in one database can both pass check-table-absent — a point-in-time ``GetTable`` with
inspect-source and infer-schema between it and this verb. The second statement is then a no-op
over the first run's table, which this verb reported as created: its requester was told the
table was ready to query over columns and a LOCATION someone else's request chose. The
post-condition below is what separates the two cases that statement cannot: it reads the table
back and refuses ``table_exists`` unless the catalog agrees with what THIS run declared. A
replay of this run's own request still matches its own table, so the property ``IF NOT EXISTS``
exists for survives.

The service name is the control plane, not the function, so one build's five invocations stay
one queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  athena_run: The table-builder's DDL runner, with this plane's reason codes bound. Held at
    module level so a timing test can replace its ``_now`` and ``_sleep`` seams, which is the
    whole reason the per-plane wrapper it replaced existed.
"""

import logging

from cpcommon import athena, clients, config, errors, events, observability
from cpcommon import columns as columns_mod
from cpcommon import ddl as ddl_mod
from cpcommon.errors import TerminalError, TransientError
from tbcommon import glue, notify
from tbcommon.results import results_location

athena_run = athena.bound_runner("ddl_execution_failed", "ddl_timeout")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")


@observability.step("athena-run-ddl")
def _run_create_ddl(query: str, database: str, output_location: str) -> None:
    """Runs the CREATE statement through Athena and polls it to a terminal state.

    A wrapper purely so the Athena round trip — which is most of this verb's latency and the only
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


@observability.step("glue-read-back-table")
def _read_back(database: str, table: str) -> dict:
    """Reads the table the statement was supposed to create.

    **Call bound: exactly once per invocation** — one call in ``_confirm_this_run_built_it``,
    which the handler calls once. The span shares apply-refresh's read-back name deliberately:
    it is the same operation asking the same question of the same catalog, and an operator
    filtering on it wants both. It is not named ``execute-ddl``, which is this verb's root span.

    **An absent table is TRANSIENT, not terminal, and that direction is the whole care here.**
    AWS publishes no read-after-write guarantee for a Glue read following a catalog create, so a
    table missing on the first look is not evidence the create failed — and calling it a failure
    would tell a user their create did not happen while their table sits in the catalog, an
    outcome strictly worse than the misreport this post-condition exists to close. Raising
    ``TransientError`` hands it to ``ExecuteDdl``'s Retry, whose re-invocation costs a no-op
    ``IF NOT EXISTS`` statement and another read. A table that is genuinely absent — this plane's
    canonical incident, LF admin status silently not granting ``CREATE_TABLE`` — still fails the
    request once the Retry budget is spent, which is the right answer arrived at slowly rather
    than the wrong one arrived at fast.

    Args:
      database: The target database.
      table: The target table name.

    Returns:
      The live Glue table dict.

    Raises:
      TransientError: When the table is absent, or on a retryable Glue fault.
      TerminalError: ``ddl_execution_failed`` on any deterministic Glue fault. The statement is
        already committed, so a success that cannot be confirmed is reported as a failure.
    """
    client = clients.glue()
    try:
        return dict(client.get_table(DatabaseName=database, Name=table)["Table"])
    except Exception as err:
        code = errors.error_code(err)
        if code == "EntityNotFoundException":
            raise TransientError(
                f"glue get_table {database}.{table}: absent after a CREATE that reported success"
            ) from err
        errors.raise_if_transient(err, f"glue get_table {database}.{table}")
        raise TerminalError(
            "ddl_execution_failed",
            f"{database}.{table} is not readable after the create: {err}",
        ) from err


def _lost_the_race(database: str, table: str, disagreement: str) -> TerminalError:
    """Builds the refusal for a statement that turned out to be a no-op over someone else's table.

    ``table_exists`` rather than a new code: from the requester's side the outcome is the one
    check-table-absent already speaks for — a table of that name already exists in that
    database, and theirs was not created. Reusing it keeps the sentence the user reads and the
    reason the machine records the same on both sides of the race.

    Args:
      database: The target database.
      table: The target table name.
      disagreement: Which declared fact the catalog does not match, for the operator's record.
        The field name only — the values ride as event fields at the call site.

    Returns:
      The error to raise.

    Raises:
      None.
    """
    return TerminalError(
        "table_exists",
        f"table {table!r} in database {database!r} was built by another request: its "
        f"{disagreement} is not this one's. Nothing was created.",
    )


def _confirm_this_run_built_it(event: dict, database: str, table: str) -> None:
    """Refuses unless the table now standing is the one this request declared.

    **Three facts are compared, and they are the three the REQUEST declares** — the LOCATION, the
    partition keys, and the projection each key was declared with. The data columns are not among
    them: they are INFERRED from the LOCATION, so two runs that agree on the location read the
    same folder seconds apart, and a difference between them is a file that changed in between or
    — for JSON — a different sample file, which is behaviour the plane already carries for a
    single create. Deriving the columns a create renders would also mean a second copy of
    ``build_create_table_ddl``'s partition-collision drop rule, in a verb that would then be
    wrong the next time that rule moves.

    The LOCATION is compared through the parser the refresh path resolves one with, so "same
    folder" is decided in one place: two strings naming one folder differ by a trailing slash. A
    catalog LOCATION this parser refuses is not this run's either — this run's own parses, since
    it was built from a portal bucket and the space's prefix — so it takes the same refusal.

    The projection comparison is CONTAINMENT, not equality: every property this run would render
    must be present with this run's value, and a property the run did not declare is ignored.
    Equality over the ``projection.`` namespace would refuse an ordinary create the first time
    AWS wrote a property of its own there, and nothing enumerates what those could be — an
    unexpected refusal of a correct create is a worse outcome than the residual, which is a
    losing run whose own declaration is a strict subset of the winner's.

    Partition key names are folded because ``columns.fold`` is this repo's one answer to "are
    these two names one column to Athena". On this path it cannot change a name: every declared
    key already matched ``CATALOG_IDENTIFIER_RE`` at validate-authorize, which is lowercase-only.
    It is the shared normaliser rather than a case this path can produce.

    Args:
      event: The task input, carrying the location and the declared partition keys.
      database: The target database.
      table: The target table name.

    Returns:
      None.

    Raises:
      TerminalError: ``table_exists`` when the catalog disagrees with this run's declaration;
        ``malformed_event`` when this run's own location does not resolve;
        ``ddl_execution_failed`` when the table cannot be read back.
      TransientError: When the table is absent, or on a retryable Glue fault.
      KeyError: If a declared partition key is missing a field the projection needs. Unlike the
        above it is not a classified outcome — but infer-schema rendered the very same keys
        through the very same renderer to build the statement this verb just ran, so a key that
        could raise here failed the build before this verb was reached.
    """
    declared_location = events.require(event, "location")
    try:
        expected = glue.parse_location(declared_location)
    except TerminalError as err:
        raise TerminalError(
            "malformed_event", f"unresolvable request location {declared_location!r}"
        ) from err

    live = _read_back(database, table)
    catalog_location = (live.get("StorageDescriptor") or {}).get("Location")

    try:
        actual = glue.parse_location(catalog_location)
    except TerminalError:
        actual = None
    if actual != expected:
        observability.warning(
            "the catalog's table is not this request's",
            database=database,
            table=table,
            disagreement="location",
            expected_location=f"s3://{expected['bucket']}/{expected['prefix']}",
            catalog_location=catalog_location,
        )
        raise _lost_the_race(database, table, "LOCATION")

    partition_keys = event.get("partitionKeys") or []
    declared_keys = [columns_mod.fold(key["name"]) for key in partition_keys]
    live_keys = [columns_mod.fold(key.get("Name") or "") for key in live.get("PartitionKeys") or []]
    if live_keys != declared_keys:
        observability.warning(
            "the catalog's table is not this request's",
            database=database,
            table=table,
            disagreement="partition_keys",
            declared_partition_keys=declared_keys,
            catalog_partition_keys=live_keys,
        )
        raise _lost_the_race(database, table, "partition keys")

    parameters = live.get("Parameters") or {}
    for key in partition_keys:
        for name, value in ddl_mod.projection_properties(key).items():
            if parameters.get(name) != value:
                observability.warning(
                    "the catalog's table is not this request's",
                    database=database,
                    table=table,
                    disagreement="projection",
                    projection_property=name,
                )
                raise _lost_the_race(database, table, f"projection property {name!r}")

    observability.info(
        "the created table matches this request",
        database=database,
        table=table,
        partition_key_count=len(declared_keys),
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
      event: The task input, carrying the space, actor, table name, location, declared
        partition keys and rendered DDL.
      context: The Lambda context, unused.

    Returns:
      The event with a created status, after notifying the actor that the table is ready.

    Raises:
      TerminalError: ``ddl_execution_failed`` when Athena reached FAILED or CANCELLED, the
        statement could not start, or the table could not be read back, carrying Athena's own
        reason where there is one; ``ddl_timeout`` when the poll cap was exceeded;
        ``table_exists`` when the statement was a no-op over a table another request built.
        All notify the actor before the SFN Catch records them.
      TransientError: On a throttling or 5xx Athena error, a retryable Glue fault, or a table
        not yet visible in the catalog — passed through un-notified for the SFN Retry.
    """
    space = event["space"]
    actor = event["actor"]
    database = space["database"]
    table = event["tableName"]

    observability.info(
        "running create ddl",
        database=database,
        table=table,
        workgroup=config.ATHENA_WORKGROUP,
        actor=actor,
    )
    _run_create_ddl(event["ddl"], database, results_location(space, actor))
    _confirm_this_run_built_it(event, database, table)

    logger.info("created table %s.%s for %s", database, table, actor)
    out = dict(event)
    out["status"] = "created"
    out.setdefault("mode", "create")
    notify.emit_created(event)
    return out
