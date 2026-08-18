"""inspect-source — resolves the source table into a copy plan.

Given the validated request: reads the source table, confirms it is a shareable shape, clones
its definition verbatim, lists the source data objects, and enforces the copy caps. Read-only,
with no copy or create side effects. Every rejection is a whole-request terminal failure, so no
recipient runs.

Neither of the two things it produces rides on the state. The object list went to S3 first
(inline, the Map's state reached 95% of the payload limit at the shipped caps); the pointer sent
the cloned definition the same way, because it was the last user-controlled term left and a
wide commented table breached the limit on its own.

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
      The request merged with the definition key, source location, copy plan key, object count
      and partitioned flag.

    Raises:
      TerminalError: Any source shape or cap rejection. It is a whole-request failure, so no
        recipient runs, and the sender is notified before the Catch records it.
      TransientError: On a retryable Glue or S3 fault.
    """
    return _inspect_source(event)


def _enforce_definition_cap(definition, database, table) -> None:
    """Rejects a cloned definition too large for Athena to accept as one statement.

    The definition travels by pointer , so this is no longer about the Step
    Functions state — it is about what create-table will do with it. The whole definition is
    rendered into a single CREATE EXTERNAL TABLE, and Athena refuses a query string over
    262,144 bytes. Rejected here as a whole-request terminal before the write and before any
    recipient runs, matching the object and byte caps rather than failing 50 recipients one at
    a time with an Athena error each.

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


def _enforce_transfer_caps(event, object_count: int, total_bytes: int) -> None:
    """Rejects a share whose ``recipients x source`` would overrun the transfer.

    **Two caps, one idea, and it is the idea the per-source caps cannot express.** The manifest
    carries one item per (recipient, object) pair and every item is a full copy, so both what
    the Map lists and what it moves scale with the recipient count. 20,000 objects is fine and
    50 recipients is fine and together they are a million manifest lines; 1 TiB is fine and 50
    recipients is fine and together they are 50 TiB, which no plausible throughput moves inside
    the state machine's timeout. The item product bounds the manifest write and the collector's
    read-back; the byte product bounds the Map Run's wall clock.

    Both count the REQUESTED recipients, not the ones the guard Map will go on to accept. That
    is deliberately the conservative reading: refusing on the upper bound is a decision the
    sender can predict from what they asked for, where refusing on the accepted count would
    make an identical request succeed or fail depending on which recipients happened to
    already hold a table of that name. It also fails here, before the guard, so a share too
    large to transfer costs no Glue reads and no destination listings.

    Args:
      event: The validated request, carrying the recipient list.
      object_count: How many source objects the listing found.
      total_bytes: How many bytes those objects hold.

    Returns:
      None.

    Raises:
      TerminalError: ``too_many_transfer_items`` when the item product exceeds its cap, or
        ``transfer_too_large`` when the byte product exceeds its own.
    """
    recipients = len(event.get("recipients") or [])
    items = recipients * object_count
    if items > config.SHARE_MAX_TRANSFER_ITEMS:
        raise TerminalError(
            "too_many_transfer_items",
            f"{recipients} recipients x {object_count} objects is {items} transfer items "
            f"(cap {config.SHARE_MAX_TRANSFER_ITEMS})",
        )

    transfer_bytes = recipients * total_bytes
    if transfer_bytes > config.SHARE_MAX_TRANSFER_BYTES:
        raise TerminalError(
            "transfer_too_large",
            f"{recipients} recipients x {total_bytes} bytes is {transfer_bytes} bytes to copy "
            f"(cap {config.SHARE_MAX_TRANSFER_BYTES})",
        )


def _inspect_source(event) -> dict:
    """Clones the source, lists its objects, enforces the caps and writes both artifacts.

    The record carries the keys, not the contents: counts and totals are what an operator needs
    to tell a share that was too large from one that was mis-scoped, and the object keys and
    the column list live in the objects the state machine points at. The object count stays on
    the state so a reader of the execution can see the size of the share without fetching them.

    Every cap is enforced before either write, so a refused share leaves nothing behind.

    Args:
      event: The validated request.

    Returns:
      The request merged with the definition key, location, plan key, object count and
      partitioned flag.

    Raises:
      TerminalError: ``source_not_found`` or ``source_not_readable`` from the catalog read, a
        shape refusal from the clone, ``source_definition_too_large``, ``source_empty``,
        ``source_too_large`` when either source cap is exceeded, or
        ``too_many_transfer_items``/``transfer_too_large`` when a recipient product is.
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
        if size > config.SHARE_MAX_OBJECT_BYTES:
            raise TerminalError(
                "source_object_too_large",
                f"{database}.{table} has an object of {size} bytes "
                f"(per-object cap {config.SHARE_MAX_OBJECT_BYTES})",
            )
        if len(objects) > config.SHARE_MAX_OBJECTS:
            raise TerminalError(
                "source_too_large",
                f"{database}.{table} has more than {config.SHARE_MAX_OBJECTS} objects "
                f"(cap {config.SHARE_MAX_OBJECTS})",
            )
    if not objects:
        raise TerminalError("source_empty", f"{database}.{table} has no data objects to share")
    if total_bytes > config.SHARE_MAX_TOTAL_BYTES:
        raise TerminalError(
            "source_too_large",
            f"{database}.{table} is {total_bytes} bytes (cap {config.SHARE_MAX_TOTAL_BYTES})",
        )
    _enforce_transfer_caps(event, len(objects), total_bytes)

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
        "definitionKey": copy_plan.write_definition(event, definition),
        "location": location,
        "copyPlanKey": copy_plan.write(event, objects),
        "objectCount": len(objects),
        "partitioned": partitioned,
    }
