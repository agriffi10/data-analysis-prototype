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

It is also where a refresh refuses a header two of whose columns Athena would give one name.
The write can land only one of them, so the refusal belongs before the classification, where
a collision would otherwise read as no change at all.
"""

import logging

from cpcommon import columns as columns_mod
from cpcommon import ddl, events, observability
from cpcommon.errors import TerminalError
from tbcommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")


def _by_folded_name(columns: list[dict], partition_keys: list[dict], fmt: str) -> dict:
    """Indexes the columns a table declares by the name Athena gives each.

    The columns are ``ddl.body_columns``, the create path's own rule for a column naming a
    partition key: renamed in a CSV, left out otherwise. Apply-refresh writes the same list, so
    what this verb compares and refuses is what the write would land, and a CSV table built with
    ``year_in_file`` compares its live column with the header's ``year`` rather than reporting it
    removed on every refresh.

    Args:
      columns: Column dicts, each carrying at least a name.
      partition_keys: Declared partition keys, each carrying a name.
      fmt: The source format.

    Returns:
      A mapping of folded column name to the declared column dict.

    Raises:
      KeyError: If a column or partition key has no name.
    """
    return {
        columns_mod.fold(c["name"]): c for c in ddl.body_columns(columns, partition_keys, fmt)
    }


def _refuse_fold_collisions(inferred: list[dict], partition_keys: list[dict], fmt: str) -> None:
    """Refuses a header two of whose data columns Athena would give one name.

    A create gets this refusal from the column-name rule. A refresh skips that rule, or it would
    strand tables built before it, but refusing a collision strands nothing: the write already
    refuses any definition carrying one, so while a header collides a refresh could only ever
    report no change. Left to the classification, ``Amount,region,amount`` against a live
    ``amount,region`` indexes to the live table and reports exactly that, and with anything
    else changed the write refuses with a message that says to try again, which cannot help.
    Refused here, the user is told which names to change, in the words a create uses.

    The names checked are the FILE's names of the columns the table declares, before a column
    naming a partition key is renamed. Renamed, ``Year`` and ``year`` beside the key ``year``
    would become two distinct columns and pass, where a create and a data-quality check both
    refuse that header.

    Args:
      inferred: The columns the data now implies.
      partition_keys: Declared partition keys. A column naming one that the write leaves out,
        in JSON or Parquet, collides with nothing.
      fmt: The source format.

    Returns:
      None.

    Raises:
      TerminalError: ``invalid_column_names``, naming every name in a collision.
    """
    names = [
        pair.source["name"]
        for pair in ddl.declare_columns(inferred, partition_keys, fmt)
        if pair.declared is not None
    ]
    colliding = list(dict.fromkeys(columns_mod.folded_duplicates(names)))
    if colliding:
        summary = columns_mod.describe(colliding)
        raise TerminalError("invalid_column_names", summary, tokens={"columns": summary})


def compute_diff(
    existing: list[dict], inferred: list[dict], partition_keys: list[dict], fmt: str
) -> dict:
    """Classifies the change between a table's declared columns and its freshly inferred ones.

    Pure — no AWS calls. Names are matched on ``columns.fold``, the name Athena gives a column,
    because the create path issues CREATE EXTERNAL TABLE through Athena, whose Hive-backed DDL
    lowercases column names: a CSV header of ``Amount`` is stored in Glue as ``amount``. A
    case-sensitive match would report every column of every mixed-case table as both added and
    removed on a folder where nothing changed — and it would be inescapable, since opting into
    the removal rebuilds with the original casing, Athena folds it again, and the next refresh
    says the same thing. A true rename is still caught; the only thing this cannot see is a
    pure case change, which under those semantics is not a change at all.

    The fold is the write's fold, not ``casefold()``. Full case folding matches ``Straße`` to a
    live ``strasse``, while the write lowercases it to ``straße`` and lands a column this
    classification never reported. Whenever something else changed, so that the write ran, it
    replaced ``strasse`` without the removal opt-in.

    A column naming a partition key is mapped here rather than assumed mapped upstream:
    infer-schema emits the full inferred list and the rename or drop happens inside the DDL
    builder, where it affects only the DDL body, so a data column named after a partition key
    does reach here and would otherwise be reported on every single refresh.

    A header two of whose columns fold to one name is refused before anything is classified.
    The index below would keep only the last of the pair, so no classification of such a header
    is true, and a refusal that depended on one would miss the collision that changes nothing
    else. It also puts the refusal ahead of the removal check, which opting in cannot satisfy.

    Args:
      existing: The columns the table currently declares.
      inferred: The columns the data now implies.
      partition_keys: Declared partition keys, which decide what a column naming one becomes.
      fmt: The source format.

    Returns:
      ``{"changed", "added", "removed", "retyped", "unchanged"}``. Names are reported as they
      appear, so the message names what the user would recognise. ``unchanged`` is a count
      rather than a list — it is the one part nobody needs by name, and on a wide table it
      would dominate the state payload.

    Raises:
      KeyError: If a column is missing its name or type.
      TerminalError: ``invalid_column_names`` when two inferred data columns fold to one name.
    """
    _refuse_fold_collisions(inferred, partition_keys, fmt)
    old = _by_folded_name(existing, partition_keys, fmt)
    new = _by_folded_name(inferred, partition_keys, fmt)

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
      TerminalError: ``invalid_column_names`` when two columns fold to one name,
        ``columns_removed`` when a removal was not opted into, or ``malformed_event`` when a
        required field, the format included, is missing.
    """
    return _diff(event)


def _diff(event: dict) -> dict:
    """Classifies the change, refuses a collision or an un-opted-into removal, and notifies a no-op.

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
      TerminalError: ``invalid_column_names`` when two columns fold to one name, from
        ``compute_diff`` and so always ahead of a removal, which opting in cannot fix.
        ``columns_removed`` when a removal was not opted into. Either way nothing is changed,
        and the tokens are what carry the column names into the notification and, for a
        removal, the link the browser names them back from.
    """
    existing = events.require(event, "existingColumns")
    inferred = events.require(event, "columns")
    fmt = events.require(event, "format")
    partition_keys = event.get("partitionKeys") or []

    diff = compute_diff(existing, inferred, partition_keys, fmt)
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
