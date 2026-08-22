"""copy-objects — the Distributed Map's batch copier.

One invocation copies one BATCH of transfer items, whatever recipients they belong to:
server-side ``CopyObject``, multipart ``UploadPartCopy`` above S3's single-copy limit, on a
bounded pool. No object bytes pass through the Lambda. This verb once copied a
whole recipient's table inside one invocation, which is why the share caps were the shape of
its 900-second timeout.

It knows nothing about recipients, the copy plan, or the request. Every destination was
resolved upstream and written into the manifest, and this verb copies what it is handed —
which is what lets the same code serve the file-send and archive planes later.

**A deterministic failure does not raise.** The batch returns its per-item outcomes and
succeeds, so one unreadable key never costs its siblings their copy; ``collect-transfer-results``
attributes those failures to their recipients from the Map Run's export. A transient failure
does raise, so Step Functions retries the whole idempotent batch.

**No ``@notifies_on_failure``, deliberately.** A batch carries no actor and no single
recipient, so the decorator's emit would resolve to nothing and send nothing — a decoration
that reads like a guarantee while providing none. The sender hears about a copy failure from
the collector, which is the first place a failure has a recipient again.

The service name is the control plane, not the function, so one share's invocations and its
Map fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import observability
from cpcommon.transfer import copy as copy_mod

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-share")

COPY_FAILED = "copy_failed"


@observability.traced("copy-objects")
def handler(event, context) -> dict:
    """Distributed-Map child entry point: copies one batch of transfer items.

    The copy is recorded per BATCH, never per object: a share can hold thousands of objects,
    each of which would otherwise be an SQS message and a line in a day object the sweep
    rewrites in full.

    Args:
      event: The batch, ``{"Items": [<transfer item>, …]}`` as the Map's ItemBatcher builds it.
      context: The Lambda context, unused.

    Returns:
      ``{"copied": n, "failures": [{"recipient": …, "reason": "copy_failed"}, …]}`` — the
      shape the collector reads back out of the results export.

    Raises:
      TransientError: When any item failed retryably, so the Map retries the whole batch.
    """
    items = event.get("Items") or []
    outcome = copy_mod.copy_batch(items, COPY_FAILED, echo_fields=("recipient", "kind"))

    logger.info("copied %d of %d items in this batch", outcome["copied"], len(items))
    observability.info(
        "batch copied",
        items=len(items),
        objects=outcome["copied"],
        failed=len(outcome["failures"]),
    )
    return outcome
