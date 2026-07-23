"""inspect-source — resolve the source table into a copy plan (SPEC-090).

Given the validated request, GetTable the source, confirm it is a shareable shape
(base EXTERNAL_TABLE, flat or partition-projection — views, managed tables, and
catalog-registered partitions are rejected), clone its definition verbatim
(LOCATION stripped), list the source data objects (relative keys + sizes), and
enforce the copy caps. Read-only — no copy/create side effects. Every rejection is
a whole-request TerminalError (Catch → recorded failure; no recipient runs).

Emits the copy plan merged over the threaded request:
{…request, tableDefinition, location: {bucket, prefix}, copyPlanKey, objectCount, partitioned}.
The object LIST goes to S3 and travels by POINTER — see tscommon.copy_plan for the
measured reason (inline, the Map's state reached 95% of the 256 KB payload limit).
"""

import json
import logging

from cpcommon import s3_listing, observability
from cpcommon.errors import TerminalError
from tscommon import config
from tscommon import copy_plan
from tscommon import glue as glue_mod
from tscommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one share is five invocations (plus a
# recipient Map fan-out), and they are only one queryable set if they share a service name
# (SPEC-127 FR-003). The per-verb identity rides as the `verb` field.
observability.init(service="table-share")


# @traced is OUTERMOST, above @notifies_on_failure: the latter catches on its way out,
# so if it were outermost the span would close status="ok" on an invocation that
# actually failed and notified.
@observability.traced("inspect-source")
@notify.notifies_on_failure("inspect")
def handler(event, context) -> dict:
    """SFN entry point: clone the source table definition and cap object count/size.

    Delegates to ``_inspect_source``; a terminal rejection is a whole-request failure (no
    recipient runs), so the sender is notified before the ``Catch`` records it (SPEC-094
    FR-003, best-effort).
    """
    return _inspect_source(event)


def _enforce_definition_cap(definition, database, table) -> None:
    """Reject a definition too large to ride on the Step Functions state.

    The object list travels by pointer now, but the CLONED DEFINITION does not — and it is
    user-controlled: columns (name/type/comment) and the source's Glue table properties are
    copied verbatim, and a user can set both from the query workspace. Measured with the
    plan already by pointer and 50 recipients failing, 1,000 columns carrying 255-char
    comments reached 150% of Step Functions' 256 KB state payload — States.DataLimitExceeded
    on the Map, which destroys every per-recipient outcome.

    Rejected HERE, as a whole-request terminal before any recipient runs, matching the
    object/byte caps rather than failing 50 recipients one at a time.
    """
    size = len(json.dumps(definition, separators=(",", ":")).encode())
    if size > config.SHARE_MAX_DEFINITION_BYTES:
        raise TerminalError(
            "source_definition_too_large",
            f"{database}.{table} definition is {size} bytes "
            f"(cap {config.SHARE_MAX_DEFINITION_BYTES})",
        )


def _inspect_source(event) -> dict:
    source = event.get("source") or {}
    database, table = source.get("database"), source.get("table")

    raw_table = glue_mod.get_table(database, table)
    definition, location, partitioned = glue_mod.clone_definition(raw_table)
    _enforce_definition_cap(definition, database, table)

    objects = []
    total_bytes = 0
    for rel_key, size in s3_listing.list_data_objects(location["bucket"], location["prefix"], relative=True):
        objects.append({"relKey": rel_key, "size": size})
        total_bytes += size
        if len(objects) > config.SHARE_MAX_OBJECTS:
            raise TerminalError(
                "source_too_large",
                f"{database}.{table} has more than {config.SHARE_MAX_OBJECTS} objects "
                "— too large for v1 (S3 Batch Operations is the deferred path)",
            )
    if not objects:
        raise TerminalError("source_empty", f"{database}.{table} has no data objects to share")
    if total_bytes > config.SHARE_MAX_TOTAL_BYTES:
        raise TerminalError(
            "source_too_large",
            f"{database}.{table} is {total_bytes} bytes (cap {config.SHARE_MAX_TOTAL_BYTES}) "
            "— too large for v1 (S3 Batch Operations is the deferred path)",
        )

    logger.info(
        "copy plan for %s.%s: %d objects, %d bytes, partitioned=%s",
        database,
        table,
        len(objects),
        total_bytes,
        partitioned,
    )
    # The plan, not the objects. Counts and totals are what an operator needs to tell a share
    # that was too large from one that was mis-scoped; the object KEYS live in the plan the
    # state machine carries.
    observability.info(
        "copy plan built",
        database=database,
        table=table,
        objects=len(objects),
        bytes=total_bytes,
        partitioned=partitioned,
    )
    return {
        **event,
        "tableDefinition": definition,
        "location": location,
        # The KEY, not the list: inline this reached 95% of Step Functions' 256 KB state
        # payload at the shipped caps, because the Map's ItemSelector copies the whole
        # state into every item. objectCount is the summary the state keeps so a reader of
        # the execution can see the size of the share without fetching the plan; nothing
        # consumes it yet (SPEC-094's messages carry no count).
        "copyPlanKey": copy_plan.write(event, objects),
        "objectCount": len(objects),
        "partitioned": partitioned,
    }
