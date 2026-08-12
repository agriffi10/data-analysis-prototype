"""build-restore-manifest — the dataset BOTH of the restore's Distributed Maps read.

SPEC-171. Takes the restore plan inspect-archive wrote and turns it into one JSON Lines item per
object, in the shape ``cpcommon.transfer`` copies: the archived object as the source, its
reconstructed origin as the destination, the size the listing measured, and the destination
storage class.

**One manifest, two Maps.** The retrieval Map reads each item's source fields to ask for the
bytes back; the copy-back Map, hours later, reads the same items whole. They run over the same
object set in the same order, so a second dataset would be a second thing that could disagree
with the plan — and the disagreement would surface as a restore that retrieved one set of
objects and copied another.

**The destination keys are the PLAN's and are not recomputed here.** inspect-archive built them
through ``arcommon.paths.origin_key``, the exact inverse of the function that wrote the archive
key, and it is the plan the destination guard cleared. Rebuilding them here would be a second
construction of a string that has already been checked — and a builder that disagreed would put
a user's files somewhere the guard never looked.

**The storage class is ``config.RESTORE_STORAGE_CLASS`` and is passed rather than omitted.** The
copy is what actually changes the class: the object a retrieval materialises is temporary, so
without an explicit ``STANDARD`` the restored object is still ``GLACIER`` and expires back to
unreadable.

The service name is the control plane, not the function, so one restore's invocations and its
Map fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import notify, plan
from arcommon.config import RESTORE_STORAGE_CLASS
from cpcommon import config, observability
from cpcommon.transfer import manifest as manifest_writer

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


def _items(loaded: dict) -> list:
    """Expands the restore plan into the Maps' transfer items.

    Args:
      loaded: The restore plan, carrying its archive and space locations and its objects.

    Returns:
      One transfer item per planned object.

    Raises:
      None.
    """
    archive, space = loaded["archive"], loaded["space"]
    return [
        {
            "srcBucket": archive["bucket"],
            "srcKey": entry["archiveKey"],
            "destBucket": space["bucket"],
            "destKey": entry["destKey"],
            "size": entry.get("bytes") or 0,
            "storageClass": RESTORE_STORAGE_CLASS,
        }
        for entry in loaded["objects"]
    ]


@observability.traced("build-restore-manifest")
@notify.notifies_on_failure("restore-manifest")
def handler(event, context) -> dict:
    """Step Functions entry point: writes the restore manifest and reports its item count.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The validated restore request, carrying the restore plan's key and the stamped
        execution context.
      context: The Lambda context, unused.

    Returns:
      The request with a ``transfer`` block naming the manifest, both Maps' results prefixes and
      the item count the Choice gates the retrieval on.

    Raises:
      TerminalError: ``plan_unreadable`` or ``plan_superseded`` when the restore plan cannot be
        read or is not this run's, or ``malformed_event`` when the execution name was not
        stamped. Whole-request either way — a manifest short of its plan would retrieve and copy
        fewer objects than the guard cleared, and the collector compares it against the same
        plan, so both counts would agree and be wrong.
      TransientError: On a retryable S3 fault writing the manifest.
    """
    return _build_restore_manifest(event)


def _build_restore_manifest(event) -> dict:
    """Loads the restore plan, builds the items and writes them as JSON Lines.

    Args:
      event: The request with its restore plan key.

    Returns:
      The request with its ``transfer`` block.

    Raises:
      TerminalError: ``plan_unreadable``, ``plan_superseded`` or ``malformed_event``.
      TransientError: On a retryable S3 fault.
    """
    loaded = plan.load_restore_plan(event.get("planKey"), event)
    items = _items(loaded)
    key = plan.restore_manifest_key(event, (event.get("execution") or {}).get("name"))
    count = manifest_writer.write_manifest(config.ADMIN_BUCKET, key, items)

    logger.info("restore manifest %s: %d items", key, count)
    observability.info(
        "restore manifest built",
        items=count,
        bytes=loaded.get("totalBytes"),
        storage_class=RESTORE_STORAGE_CLASS,
    )
    return {
        **event,
        "transfer": {
            "manifestBucket": config.ADMIN_BUCKET,
            "manifestKey": key,
            "resultsBucket": config.ADMIN_BUCKET,
            "retrievalResultsPrefix": plan.retrieval_results_prefix(event),
            "resultsPrefix": plan.restore_results_prefix(event),
            "itemCount": count,
        },
    }
