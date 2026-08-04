"""apply-refresh — the refresh branch's terminal task (SPEC-144).

Rebuilds the table from the definition SPEC-143 captured plus the columns infer-schema
just derived: ``DROP TABLE IF EXISTS`` then ``CREATE EXTERNAL TABLE``, both through
Athena, polled to a terminal state in that order.

THE STATEMENT IS REGENERATED, NOT PATCHED. ``ALTER TABLE ADD COLUMNS`` cannot retype,
cannot remove, and behaves inconsistently across the three SerDes in play, so it would be
a fourth code path covering only the easiest case.

**The data is never touched.** These tables are EXTERNAL, so a drop removes a catalog
entry and nothing else — which is the property the whole design rests on, and why the
execution role's explicit ``Deny s3:DeleteObject`` stays exactly where it is. If a
table-builder table ever stops being external, this verb becomes destructive.

There is a window, typically a second or two, in which the table does not exist.

**THE FIFO QUEUE DOES NOT CLOSE THAT WINDOW, despite what SPEC-144 FR-006 AC1 claims.**
The ``MessageGroupId`` is the target database, which serializes DELIVERY — but the Pipe
invokes ``StartExecution`` as ``FIRE_AND_FORGET`` (``infra/modules/table-builder/pipe.tf``),
so the message is done as soon as the execution STARTS, not when it finishes. Two requests
on one database therefore run concurrently, and a second refresh reaching ``GetTable``
inside this window sees ``table_not_found``.

What actually bounds the damage is narrower and worth stating honestly: the drop and the
create are issued back to back with nothing between them, both carry an idempotency token
so a retry re-attaches rather than re-drops, and a create that fails after a successful
drop says so in its own words rather than reporting a generic failure.
"""

import logging

import refresh_athena
from cpcommon import clients, config, ddl, events, observability
from cpcommon.errors import TerminalError
from tbcommon import notify
from tbcommon.results import results_location

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one table-build is five invocations, and
# they are only one queryable set if they share a service name (SPEC-127 FR-003). The per-verb
# identity rides as the `verb` field.
observability.init(service="table-builder")


def _with_carried_comments(columns: list[dict], existing: list[dict]) -> list[dict]:
    """Re-attach each surviving column's COMMENT from the table being replaced.

    A rebuild takes its names and types from fresh inference, which has nothing to say
    about what a column MEANS — so a comment a user wrote is metadata only the old table
    holds, and a DROP + CREATE is exactly where it would silently disappear. Matched on the
    folded name, like every other comparison on this path, because Athena's Hive-backed DDL
    stores what it creates in lower case.

    A column that is new, or whose comment was never set, is returned untouched.
    """
    comments = {
        c["name"].casefold(): c["comment"] for c in existing if c.get("comment")
    }
    return [
        {**c, "comment": comments[c["name"].casefold()]}
        if c["name"].casefold() in comments
        else c
        for c in columns
    ]


def _carried_properties(table_properties: dict) -> dict:
    """The captured properties worth writing back, minus the ones we regenerate.

    ``projection.*`` and ``projection.enabled`` are STRIPPED because
    ``build_create_table_ddl`` regenerates them from the reconstructed partition keys —
    ``clone_definition`` copies every Glue parameter, so a partitioned table's capture
    always carries them, and a naive merge would emit each key twice inside one
    ``TBLPROPERTIES (…)``.
    """
    return {
        key: value
        for key, value in (table_properties or {}).items()
        if not key.startswith("projection.")
    }


def _expected_column_names(columns: list[dict], partition_keys: list[dict]) -> set:
    """The column names the generated statement actually DECLARES, case-folded.

    NOT simply ``columns``: ``build_create_table_ddl`` drops a data column whose name
    collides with a partition key (the key wins, so the DDL stays valid), and
    ``infer-schema`` emits the FULL inferred list — so a partitioned folder whose files
    carry a column named after a partition key would otherwise make a perfectly good
    rebuild look short by one. Folded for the same reason the diff folds: Athena's
    Hive-backed DDL stores what it creates in lower case.
    """
    partition_names = {k["name"].casefold() for k in partition_keys}
    return {c["name"].casefold() for c in columns} - partition_names


def _post_condition(database: str, table: str, expected: set) -> int:
    """Read the table back and confirm the rebuild actually landed.

    CHECKED RATHER THAN ASSUMED because this plane's canonical failure was a verb that
    COMPLETED while the table was not created (SPEC-135, PRs #243-246). A create that
    reports SUCCEEDED and leaves nothing behind is the shape that cost four PRs to find.

    Compares the NAME SET rather than a count: same cost, and a count cannot tell a
    rebuild that landed from one that landed against a stale catalog entry with the same
    number of columns.

    A read failure here is TERMINAL, never transient — including a throttle. The drop and
    the create are already committed, so re-invoking the verb would re-run the pair, and a
    verification failing is not a reason to repeat the work it was verifying.
    """
    glue = clients.glue()
    try:
        table_def = glue.get_table(DatabaseName=database, Name=table)["Table"]
    except Exception as err:
        raise TerminalError(
            "recreate_failed", f"{database}.{table} is not readable after the create: {err}"
        ) from err

    actual = {
        (c.get("Name") or "").casefold()
        for c in (table_def.get("StorageDescriptor") or {}).get("Columns") or []
    }
    if actual != expected:
        raise TerminalError(
            "recreate_failed",
            f"{database}.{table} has {len(actual)} columns after the create, "
            f"expected {len(expected)} (missing {sorted(expected - actual)}, "
            f"unexpected {sorted(actual - expected)})",
        )
    return len(actual)


# @traced is OUTERMOST, above @notifies_on_failure: the latter catches on its way out,
# so if it were outermost the span would close status="ok" on an invocation that
# actually failed and notified.
@observability.traced("apply-refresh")
@notify.notifies_on_failure("apply")
def handler(event: dict, context) -> dict:
    """SFN entry point: drop the table and recreate it from the captured definition.

    Delegates to ``_apply``. A terminal failure notifies the actor before the SFN
    ``Catch`` records it — and on ``recreate_failed`` that notification is the only thing
    telling them their table is gone.
    """
    return _apply(event)


def _apply(event: dict) -> dict:
    space = events.require(event, "space")
    actor = events.require(event, "actor")
    database = events.require(event, "space", "database")
    table = events.require(event, "tableName")
    columns = events.require(event, "columns")
    location = events.require(event, "location")
    fmt = events.require(event, "format")

    partition_keys = event.get("partitionKeys") or []
    columns = _with_carried_comments(columns, event.get("existingColumns") or [])
    storage = ddl.storage_from_definition(event.get("storage") or {})
    statement = ddl.build_create_table_ddl(
        database,
        table,
        columns,
        partition_keys,
        fmt,
        location,
        storage=storage,
        # NOT `IF NOT EXISTS`: after a drop that silently did not take, it would turn the
        # recreate into a successful no-op and report a refresh that did not happen.
        if_not_exists=False,
        table_properties=_carried_properties(event.get("tableProperties")),
    )

    output = results_location(space, actor)
    observability.info(
        "applying refresh",
        database=database,
        table=table,
        column_count=len(columns),
        partition_key_count=len(partition_keys),
        # Schema, not file contents — permitted by the field rule, and the one field an
        # operator needs to reproduce a failed rebuild by hand (FR-006).
        ddl=statement,
    )

    # ONE budget across BOTH statements, so a slow pair cannot run past the function
    # timeout and be killed between them — which would leave the table dropped with no
    # notification at all (the process is gone, so @notifies_on_failure never runs).
    request_id = event.get("requestId") or ""
    started = refresh_athena._now()

    def _remaining():
        left = refresh_athena.TOTAL_POLL_BUDGET_SECONDS - (refresh_athena._now() - started)
        return max(left, 1)

    drop_id = refresh_athena.run_ddl(
        query=f"DROP TABLE IF EXISTS {ddl.quote(database)}.{ddl.quote(table)}",
        database=database,
        workgroup=config.ATHENA_WORKGROUP,
        output_location=output,
        fail_reason="drop_failed",
        # Derived from the requestId, so a Retry re-attaches to the SAME execution rather
        # than issuing a second one — on this pair that is the difference between a retry
        # re-reading its own work and a retry dropping the table it just rebuilt.
        token=f"{request_id}-refresh-drop",
        budget=_remaining(),
    )
    # NOTHING BETWEEN THE TWO STATEMENTS. Every S3, Glue or SQS call here would widen the
    # window in which the user's table does not exist (FR-006).
    create_id = refresh_athena.run_ddl(
        query=statement,
        database=database,
        workgroup=config.ATHENA_WORKGROUP,
        output_location=output,
        fail_reason="recreate_failed",
        token=f"{request_id}-refresh-create",
        budget=_remaining(),
    )

    applied = _post_condition(database, table, _expected_column_names(columns, partition_keys))

    out = dict(event)
    out["status"] = "refreshed"
    out["appliedColumnCount"] = applied
    out["ddl"] = statement
    logger.info("refreshed %s.%s: %d columns", database, table, applied)
    observability.info(
        "refresh applied",
        database=database,
        table=table,
        applied_column_count=applied,
        drop_query_execution_id=drop_id,
        create_query_execution_id=create_id,
        post_condition_ok=True,
    )
    notify.emit_refresh_outcome(event, "refreshed", event.get("diff"))
    return out
