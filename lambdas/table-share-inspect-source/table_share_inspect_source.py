"""inspect-source — resolves the source table into a copy plan.

Given the validated request: reads the source table, confirms it is a shareable shape, clones
its definition verbatim, lists the source data objects, and enforces the copy caps. Read-only,
with no copy or create side effects. Every rejection is a whole-request terminal failure, so no
recipient runs.

The object list goes to S3 and travels by pointer rather than on the state — inline, the Map's
state reached 95% of the payload limit at the shipped caps.

The service name is the control plane, not the function, so one share's invocations and its
Map fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import json
import logging

from cpcommon import observability, s3_listing
from cpcommon.errors import TerminalError
from tscommon import config, copy_plan, notify
from tscommon import glue as glue_mod

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-share")


@observability.traced("inspect-source")
@notify.notifies_on_failure("inspect")
def handler(event, context) -> dict:
    """Step Functions entry point: clones the source definition and caps the copy.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    Args:
      event: The validated request, carrying the source database and table.
      context: The Lambda context, unused.

    Returns:
      The request merged with the cloned definition, source location, copy plan key, object
      count and partitioned flag.

    Raises:
      TerminalError: Any source shape or cap rejection. It is a whole-request failure, so no
        recipient runs, and the sender is notified before the Catch records it.
      TransientError: On a retryable Glue or S3 fault.
    """
    return _inspect_source(event)


def _enforce_definition_cap(definition, database, table) -> None:
    """Rejects a cloned definition too large to ride on the Step Functions state.

    The object list travels by pointer now, but the cloned definition does not — and it is
    user-controlled, since the columns and the source's table properties are copied verbatim
    and a user can set both from the query workspace. Rejected here as a whole-request terminal
    before any recipient runs, matching the object and byte caps rather than failing 50
    recipients one at a time.

    Args:
      definition: The cloned definition.
      database: The source database, for the failure detail.
      table: The source table, for the failure detail.

    Returns:
      None.

    Raises:
      TerminalError: ``source_definition_too_large`` when the serialised definition exceeds the
        cap.
    """
    size = len(json.dumps(definition, separators=(",", ":")).encode())
    if size > config.SHARE_MAX_DEFINITION_BYTES:
        raise TerminalError(
            "source_definition_too_large",
            f"{database}.{table} definition is {size} bytes "
            f"(cap {config.SHARE_MAX_DEFINITION_BYTES})",
        )


def _inspect_source(event) -> dict:
    """Clones the source, lists its objects, enforces the caps and writes the plan.

    The record carries the plan, not the objects: counts and totals are what an operator needs
    to tell a share that was too large from one that was mis-scoped, and the object keys live
    in the plan the state machine carries. The object count stays on the state so a reader of
    the execution can see the size of the share without fetching the plan.

    Args:
      event: The validated request.

    Returns:
      The request merged with the cloned definition, location, plan key, object count and
      partitioned flag.

    Raises:
      TerminalError: ``source_not_found`` or ``source_not_readable`` from the catalog read, a
        shape refusal from the clone, ``source_definition_too_large``, ``source_empty``, or
        ``source_too_large`` when either copy cap is exceeded.
      TransientError: On a retryable Glue or S3 fault.
    """
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
        "copyPlanKey": copy_plan.write(event, objects),
        "objectCount": len(objects),
        "partitioned": partitioned,
    }
