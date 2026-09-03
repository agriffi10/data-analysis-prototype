"""copy-objects — the Distributed Map's batch copier.

One invocation copies one BATCH of transfer items, whatever selected items they belong to:
server-side ``CopyObject``, multipart ``UploadPartCopy`` above S3's single-copy limit, on a bounded
pool. No object bytes pass through the Lambda, so an object far larger than this function's memory
still transfers.

It is ``cpcommon.transfer.copy`` with this plane's reason code and its attribution field, and
nothing else — the engine is shared with three other planes deliberately, and a forked copier here
would be a second place for the multipart threshold, the abort-on-failure rule and the
transient/deterministic split to drift. It knows nothing about items, the plan or the request: every
destination was derived and checked upstream and written into the manifest.

**It attributes to the selected ITEM**, where the other three planes attribute to a recipient. That
is the whole reason the engine's attribution key was generalised: an ``itemKey`` on a manifest line
used to ride into the child input and be dropped on the way out.

**A deterministic failure does not raise.** The batch returns its per-item outcomes and SUCCEEDS, so
one unreadable key never costs its siblings their copy; ``collect-transfer-results`` attributes
those failures back from the Map Run's export. A transient failure does raise, so Step Functions
retries the whole idempotent batch.

**No ``@notifies_on_failure``, deliberately.** A batch carries no actor and no single item, so the
decorator's emit would resolve to nothing and send nothing — a decoration that reads like a
guarantee while providing none.

The service name is the control plane, not the function, so one operation's invocations and its Map
fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  COPY_FAILED: This plane's reason code for an object that did not copy. A deliberate twin of
    ``focommon``'s, as the sibling planes' batch verbs carry. **Its original reason has expired:**
    it was declared here because the verb attached ``cpcommon`` alone, so ``focommon`` was not on
    its path, and the image now puts every shared package on ``/opt/python`` for every function.
    Importing it would work. Whether to collapse the twin is a code decision nobody has made, and
    the duplication is recorded here rather than silently kept for a reason that no longer holds.
  ITEM_KEY: The manifest-line field echoed onto every failure record, which is this plane's
    attribution vocabulary. Bounded by construction — one key per line, never a list.
"""

import logging

from cpcommon import observability
from cpcommon.transfer import copy as copy_mod

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-ops")

COPY_FAILED = "copy_failed"

ITEM_KEY = ("itemKey",)


@observability.traced("copy-objects")
def handler(event, context) -> dict:
    """Distributed-Map child entry point: copies one batch of transfer items.

    The copy is recorded per BATCH, never per object: one operation can hold tens of thousands of
    objects, each of which would otherwise be an SQS message and a line in a day object the log
    sweep rewrites in full.

    Args:
      event: The batch, ``{"Items": [<transfer item>, …]}`` as the Map's ItemBatcher builds it.
      context: The Lambda context, unused.

    Returns:
      ``{"copied": n, "failures": [{"itemKey": …, "reason": "copy_failed"}, …]}`` — the shape the
      collector reads back out of the results export. ``copied`` is what lets the collector check
      the export against the manifest rather than trust it.

    Raises:
      TransientError: When any item failed retryably, so the Map retries the whole batch.
    """
    items = event.get("Items") or []
    outcome = copy_mod.copy_batch(items, COPY_FAILED, echo_fields=ITEM_KEY)

    logger.info("copied %d of %d items in this batch", outcome["copied"], len(items))
    observability.info(
        "batch copied",
        items=len(items),
        objects=outcome["copied"],
        failed=len(outcome["failures"]),
    )
    return outcome
