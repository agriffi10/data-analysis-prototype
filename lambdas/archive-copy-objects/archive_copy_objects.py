"""copy-objects — the Distributed Map's batch copier.

One invocation copies one BATCH of transfer items into the archive bucket at the class the
manifest names: server-side ``CopyObject``, multipart ``UploadPartCopy`` above S3's single-copy
limit, on a bounded pool. No object bytes pass through the Lambda, so an object far larger than
this function's memory still transfers.

It is ``cpcommon.transfer.copy`` with this plane's reason code and nothing else — the engine is
shared with table-share and file-send deliberately, and this plane is its third caller.
A forked copier here would be a second place for the multipart threshold, the abort-on-failure
rule, the transient/deterministic split and — since SPEC-169 — the storage class's two homes to
drift. It knows nothing about the request: every destination and the class were resolved upstream
and written into the manifest.

**A deterministic failure does not raise.** The batch returns its per-item outcomes and SUCCEEDS,
so one unreadable key never costs its siblings their copy; collect-transfer-results reads those
failures out of the Map Run's export and the commit gate refuses the whole archive on any one of
them. A transient failure does raise, so Step Functions retries the whole idempotent batch.

**No ``@notifies_on_failure``, deliberately.** A batch is a fragment of a request with no actor on
it, so the decorator's emit would resolve to nothing and send nothing — a decoration that reads
like a guarantee while providing none.

The service name is the control plane, not the function, so one archive's invocations and its Map
fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import observability
from cpcommon.transfer import copy as copy_mod

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")

COPY_FAILED = "copy_failed"


@observability.traced("copy-objects")
def handler(event, context) -> dict:
    """Distributed-Map child entry point: copies one batch of transfer items.

    The copy is recorded per BATCH, never per object: an archive can hold tens of thousands of
    objects, each of which would otherwise be an SQS message and a line in a day object the log
    sweep rewrites in full.

    Args:
      event: The batch, ``{"Items": [<transfer item>, …]}`` as the Map's ItemBatcher builds it.
      context: The Lambda context, unused.

    Returns:
      ``{"copied": n, "failures": [{"recipient": None, "kind": None, "reason": "copy_failed"}, …]}``
      — the shape the collector reads back out of the results export. The recipient fields are
      empty here and that is correct rather than a gap: an archive has one destination, so a
      failure needs no attribution and the gate needs only the COUNT. ``copied`` is what lets the
      collector check the export against the manifest rather than trust it.

    Raises:
      TransientError: When any item failed retryably, so the Map retries the whole batch.
    """
    items = event.get("Items") or []
    outcome = copy_mod.copy_batch(items, COPY_FAILED)

    logger.info("copied %d of %d items in this batch", outcome["copied"], len(items))
    observability.info(
        "batch copied",
        items=len(items),
        objects=outcome["copied"],
        failed=len(outcome["failures"]),
    )
    return outcome
