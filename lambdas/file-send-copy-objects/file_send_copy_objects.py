"""copy-objects — the Distributed Map's batch copier.

One invocation copies one BATCH of transfer items, whatever recipients they belong to:
server-side ``CopyObject``, multipart ``UploadPartCopy`` above S3's single-copy limit, on a
bounded pool. No object bytes pass through the Lambda, so an object far larger than this
function's memory still transfers.

It is ``cpcommon.transfer.copy`` with this plane's reason code and nothing else — the engine is
shared with table-share deliberately, and a forked copier here would be a second
place for the multipart threshold, the abort-on-failure rule and the transient/deterministic
split to drift. It knows nothing about recipients, the copy plan or the request: every
destination was resolved upstream and written into the manifest.

**A deterministic failure does not raise.** The batch returns its per-item outcomes and
SUCCEEDS, so one unreadable key never costs its siblings their copy; ``collect-transfer-results``
attributes those failures to their recipients from the Map Run's export. A transient failure
does raise, so Step Functions retries the whole idempotent batch.

**No ``@notifies_on_failure``, deliberately.** A batch carries no actor and no single recipient,
so the decorator's emit would resolve to nothing and send nothing — a decoration that reads like
a guarantee while providing none.

The service name is the control plane, not the function, so one send's invocations and its Map
fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import observability
from cpcommon.transfer import copy as copy_mod

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-send")

COPY_FAILED = "copy_failed"


@observability.traced("copy-objects")
def handler(event, context) -> dict:
    """Distributed-Map child entry point: copies one batch of transfer items.

    The copy is recorded per BATCH, never per object: a send can hold tens of thousands of
    objects, each of which would otherwise be an SQS message and a line in a day object the log
    sweep rewrites in full.

    Args:
      event: The batch, ``{"Items": [<transfer item>, …]}`` as the Map's ItemBatcher builds it.
      context: The Lambda context, unused.

    Returns:
      ``{"copied": n, "failures": [{"recipient": …, "kind": …, "reason": "copy_failed"}, …]}`` —
      the shape the collector reads back out of the results export. ``copied`` is what lets the
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
