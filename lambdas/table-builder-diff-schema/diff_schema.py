"""diff-schema — the refresh branch's classifier.

Two schemas exist by this point: the one the table currently declares, threaded forward by
load-table-definition, and the one the data now implies, freshly inferred by infer-schema.
This verb is about the gap between them.

Most of the time it is additive and applies without ceremony. A removal is different: it
breaks every saved query, view and dashboard referencing the column, somewhere the person who
ran the refresh is not looking. So a removal is refused unless the request opted in — and the
refusal is the warning, naming the columns in a notification and changing nothing.

This verb also owns the no-change notification. The state machine has no notification state,
every notification on this plane is emitted in-Lambda, and on the unchanged path no Lambda
runs after this one.
"""

import logging

from cpcommon import events, observability
from cpcommon.errors import TerminalError
from tbcommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")


def _by_folded_name(columns: list[dict], partition_key_names: set[str]) -> dict:
    """Indexes columns by case-folded name, excluding the partition keys.

    Args:
      columns: Column dicts, each carrying at least a name.
      partition_key_names: Partition key names to exclude; matched case-folded too.

    Returns:
      A mapping of case-folded column name to the original column dict.

    Raises:
      KeyError: If a column has no name.
    """
    excluded = {name.casefold() for name in partition_key_names}
    return {
        c["name"].casefold(): c for c in columns if c["name"].casefold() not in excluded
    }


def compute_diff(existing: list[dict], inferred: list[dict], partition_key_names: set[str]) -> dict:
    """Classifies the change between a table's declared columns and its freshly inferred ones.

    Pure — no AWS calls. Names are matched case-insensitively, because the create path issues
    CREATE EXTERNAL TABLE through Athena, whose Hive-backed DDL folds column names: a CSV
    header of ``Amount`` is stored in Glue as ``amount``. Nothing here normalises them, so a
    case-sensitive match would report every column of every mixed-case table as both added and
    removed on a folder where nothing changed — and it would be inescapable, since opting into
    the removal rebuilds with the original casing, Athena folds it again, and the next refresh
    says the same thing. A true rename is still caught; the only thing this cannot see is a
    pure case change, which under those semantics is not a change at all.

    Partition keys are excluded here rather than assumed excluded upstream: infer-schema emits
    the full inferred list and the partition-collision drop happens inside the DDL builder,
    where it affects only the DDL body, so a data column named after a partition key does reach
    here and would otherwise be reported on every single refresh.

    Args:
      existing: The columns the table currently declares.
      inferred: The columns the data now implies.
      partition_key_names: Declared partition key names, excluded from the comparison.

    Returns:
      ``{"changed", "added", "removed", "retyped", "unchanged"}``. Names are reported as they
      appear, so the message names what the user would recognise. ``unchanged`` is a count
      rather than a list — it is the one part nobody needs by name, and on a wide table it
      would dominate the state payload.

    Raises:
      KeyError: If a column is missing its name or type.
    """
    old = _by_folded_name(existing, partition_key_names)
    new = _by_folded_name(inferred, partition_key_names)

    added = [{"name": new[k]["name"], "type": new[k]["type"]} for k in new if k not in old]
    removed = [{"name": old[k]["name"], "type": old[k]["type"]} for k in old if k not in new]
    retyped = [
        {"name": new[k]["name"], "from": old[k]["type"], "to": new[k]["type"]}
        for k in new
        if k in old and old[k]["type"] != new[k]["type"]
    ]
    unchanged = sum(1 for k in new if k in old and old[k]["type"] == new[k]["type"])

    return {
        "changed": bool(added or removed or retyped),
        "added": added,
        "removed": removed,
        "retyped": retyped,
        "unchanged": unchanged,
    }


@observability.traced("diff-schema")
@notify.notifies_on_failure("diff")
def handler(event: dict, context) -> dict:
    """Step Functions entry point: classifies the change and enforces the removal opt-in.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified. On the removal path that notification is not incidental —
    it is the warning.

    Args:
      event: The task input, carrying both column lists and the removal opt-in.
      context: The Lambda context, unused.

    Returns:
      The event with the classified diff attached, and a status of unchanged when nothing
      differs.

    Raises:
      TerminalError: ``columns_removed`` when a removal was not opted into, or
        ``malformed_event`` when a required field is missing.
    """
    return _diff(event)


def _diff(event: dict) -> dict:
    """Classifies the change, refuses an un-opted-into removal, and notifies a no-op.

    Column names are schema and are permitted in the record; column values and sampled rows
    are not and appear nowhere. The request id and verb ride as baggage from the span.

    Args:
      event: The task input.

    Returns:
      The event with the diff attached. On the unchanged path it also sets a status, because
      the success state reads that field and a Pass state's JSONPath raises an uncatchable
      runtime error on an absent key, so the no-op path must set it here rather than rely on a
      verb that never runs.

    Raises:
      TerminalError: ``columns_removed`` when a removal was not opted into. Nothing is changed,
        and the tokens are what carry the column names into the notification and the link the
        browser names them back from.
    """
    existing = events.require(event, "existingColumns")
    inferred = events.require(event, "columns")
    partition_key_names = {k["name"] for k in (event.get("partitionKeys") or [])}

    diff = compute_diff(existing, inferred, partition_key_names)
    removed_names = [c["name"] for c in diff["removed"]]

    logger.info(
        "diffed %s: +%d -%d ~%d",
        event.get("tableName"),
        len(diff["added"]),
        len(removed_names),
        len(diff["retyped"]),
    )
    observability.info(
        "diffed schema",
        database=(event.get("space") or {}).get("database"),
        table=event.get("tableName"),
        added_count=len(diff["added"]),
        removed_count=len(removed_names),
        retyped_count=len(diff["retyped"]),
        unchanged_count=diff["unchanged"],
        added_names=[c["name"] for c in diff["added"]],
        removed_names=removed_names,
        allow_removals=bool(event.get("allowRemovals")),
        changed=diff["changed"],
    )

    if removed_names and not event.get("allowRemovals"):
        raise TerminalError(
            "columns_removed",
            f"{len(removed_names)} column(s) would be removed and allowRemovals is false",
            notify.removed_tokens(removed_names),
        )

    out = dict(event)
    out["diff"] = diff
    if not diff["changed"]:
        out["status"] = "unchanged"
        notify.emit_refresh_outcome(event, "unchanged")
    return out
