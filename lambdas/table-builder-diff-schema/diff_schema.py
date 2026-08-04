"""diff-schema — the refresh branch's classifier (SPEC-144).

Two schemas exist by this point: the one the table currently declares, threaded forward by
load-table-definition, and the one the data now implies, freshly inferred by infer-schema.
This verb is about the gap between them.

Most of the time it is additive and applies without ceremony. A removal is different: it
breaks every saved query, view and dashboard referencing the column, and it breaks them
somewhere the person who ran the refresh is not looking. So a removal is REFUSED unless the
request opted in — and the refusal IS the warning, naming the columns in a notification and
changing nothing.

This verb also owns the no-change notification. The state machine has no notification
state, every notification on this plane is emitted in-Lambda, and on the unchanged path no
Lambda runs after this one.
"""

import logging

from cpcommon import events, observability
from cpcommon.errors import TerminalError
from tbcommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one table-build is five invocations, and
# they are only one queryable set if they share a service name (SPEC-127 FR-003). The per-verb
# identity rides as the `verb` field.
observability.init(service="table-builder")


def _by_folded_name(columns: list[dict], partition_key_names: set[str]) -> dict:
    """``{folded name: column}``, excluding partition keys (also matched folded)."""
    excluded = {name.casefold() for name in partition_key_names}
    return {
        c["name"].casefold(): c for c in columns if c["name"].casefold() not in excluded
    }


def compute_diff(existing: list[dict], inferred: list[dict], partition_key_names: set[str]) -> dict:
    """Classify the change between two column lists. Pure — no AWS calls.

    MATCHED CASE-INSENSITIVELY, and this reverses SPEC-144 FR-001 as written (amended
    2026-08-04). Its premise — that Athena treats ``Amount`` and ``amount`` as distinct —
    is not what this pipeline sees: the create path issues ``CREATE EXTERNAL TABLE``
    through Athena, whose Hive-backed DDL FOLDS column names, so a CSV header of
    ``Amount`` is stored in Glue as ``amount``. Nothing here normalises them —
    ``infer-schema`` reads the header verbatim and ``load-table-definition`` reads Glue
    verbatim — so a case-sensitive match would report every column of every mixed-case
    table as BOTH added and removed, on a folder where nothing changed. Worse, it would be
    unescapable: opting into the removal rebuilds with ``Amount``, Athena folds it again,
    and the next refresh says the same thing.

    A true rename (``amount`` → ``total``) is still caught; the only thing this cannot see
    is a pure case change, which under those same Hive semantics is not a change at all.
    Names are REPORTED as they appear, so the message names what the user would recognise.

    IT EXCLUDES PARTITION KEYS ITSELF rather than assuming an upstream verb did.
    ``infer-schema`` emits the FULL inferred list, and the partition-collision drop happens
    inside ``build_create_table_ddl``, where it affects only the DDL body — so a data
    column named after a partition key does reach here, and would otherwise be reported as
    added or removed on every single refresh.

    ``unchanged`` is a count rather than a list: it is the one part nobody needs by name,
    and on a wide table it would dominate the state payload.
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


# @traced is OUTERMOST, above @notifies_on_failure: the latter catches on its way out,
# so if it were outermost the span would close status="ok" on an invocation that
# actually failed and notified.
@observability.traced("diff-schema")
@notify.notifies_on_failure("diff")
def handler(event: dict, context) -> dict:
    """SFN entry point: classify the change and enforce the removal opt-in.

    Delegates to ``_diff`` and notifies the actor on a terminal failure (best-effort)
    before the SFN ``Catch`` records it — which on the ``columns_removed`` path is not
    incidental, it IS the warning FR-003 promises.
    """
    return _diff(event)


def _diff(event: dict) -> dict:
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
    # Column NAMES are schema and are permitted; column VALUES and sampled rows are not and
    # appear nowhere (the field rule, decisions.md). `request_id` and `verb` ride as
    # baggage from @traced.
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
        # The refusal IS the warning: it names the columns, and nothing is changed. tokens
        # is what carries them into the notification, and the link built from them is what
        # lets the browser name them back to the user (SPEC-145 FR-005).
        raise TerminalError(
            "columns_removed",
            f"{len(removed_names)} column(s) would be removed and allowRemovals is false",
            notify.removed_tokens(removed_names),
        )

    out = dict(event)
    out["diff"] = diff
    if not diff["changed"]:
        # RecordSuccess reads $.status, and a Pass state's JSONPath raises an UNCATCHABLE
        # States.Runtime on an absent key — so the no-op path must set it here, not rely on
        # a verb that never runs.
        out["status"] = "unchanged"
        # No Lambda runs after this one on the unchanged path, and the state machine has no
        # notification state, so the outcome is emitted here or nowhere.
        notify.emit_refresh_outcome(event, "unchanged")
    return out
