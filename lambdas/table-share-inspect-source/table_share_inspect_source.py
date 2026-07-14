"""inspect-source — resolve the source table into a copy plan (SPEC-090).

Given the validated request, GetTable the source, confirm it is a shareable shape
(base EXTERNAL_TABLE, flat or partition-projection — views, managed tables, and
catalog-registered partitions are rejected), clone its definition verbatim
(LOCATION stripped), list the source data objects (relative keys + sizes), and
enforce the copy caps. Read-only — no copy/create side effects. Every rejection is
a whole-request TerminalError (Catch → recorded failure; no recipient runs).

Emits the copy plan merged over the threaded request:
{…request, tableDefinition, location: {bucket, prefix}, objects: [{relKey, size}], partitioned}.
"""

import logging

from cpcommon import s3_listing
from cpcommon.errors import TerminalError
from tscommon import config
from tscommon import glue as glue_mod
from tscommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)


@notify.notifies_on_failure("inspect")
def handler(event, context) -> dict:
    # A terminal rejection is a WHOLE-REQUEST failure (no recipient runs) —
    # notify the sender before the Catch records it (SPEC-094 FR-003, best-effort).
    try:
        return _inspect_source(event)
    except TerminalError as err:
        notify.emit_failure(event, err, "inspect")
        raise


def _inspect_source(event) -> dict:
    source = event.get("source") or {}
    database, table = source.get("database"), source.get("table")

    raw_table = glue_mod.get_table(database, table)
    definition, location, partitioned = glue_mod.clone_definition(raw_table)

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
    return {
        **event,
        "tableDefinition": definition,
        "location": location,
        "objects": objects,
        "partitioned": partitioned,
    }
