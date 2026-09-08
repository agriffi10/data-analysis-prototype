"""initiate-restore — the Distributed Map child that asks Glacier for the bytes back.

and **the point of no return for the whole arc.** Everything the destination guard does
happens so that this state can be reached safely: a Glacier retrieval is billed the moment it is
requested and cannot be cancelled, so the destination guard runs on the other side of it and
refuses a restore that could not land.

**It is a Map child rather than one long verb**, driven by the same manifest the copy-back reads.
An archive of 20,000 objects is 20,000 ``RestoreObject`` calls, which is not work a single
invocation should be sized for — and the plane already knows how to fan out over a JSONL dataset.

**Its Map tolerates NO item failure**, unlike the copy's. A genuine fault on any object fails the
child, fails the Map Run, and fails the run — at which point nothing has been copied and the
archive is untouched, so the user simply re-submits. That re-submission is free of a second bill
for the objects already asked for, because ``RestoreAlreadyInProgress`` and ``InvalidObjectState``
are tolerated rather than raised.

**No ``@notifies_on_failure``, deliberately.** A batch is a fragment of a request with no actor
on it, so the decorator's emit would resolve to nothing and send nothing — a decoration that
reads like a guarantee while providing none. The same reasoning copy-objects records.

The service name is the control plane, not the function, so one restore's invocations and its Map
fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import retrieval
from cpcommon import observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


@observability.traced("initiate-restore")
def handler(event, context) -> dict:
    """Distributed-Map child entry point: requests retrieval for one batch of archived objects.

    The retrieval is recorded per BATCH, never per object: an archive can hold tens of thousands
    of objects, each of which would otherwise be an SQS message and a line in a day object the
    log sweep rewrites in full.

    Args:
      event: The batch, ``{"BatchInput": {traceparent, requestId}, "Items": [<transfer item>, …]}``
          as the Map's ItemBatcher builds it. The ``BatchInput`` block is how the run's
          trace reaches a child that cannot see the parent state, and
          ``observability._shape_values`` reads it — so the key is load-bearing, not
          decoration.
        Only the source fields are read here; the destinations are the copy-back's business,
        hours later.
      context: The Lambda context, unused.

    Returns:
      ``{"requested": n}`` — how many retrievals this batch asked for. Nothing downstream reads
      it: this Map's ResultWriter export exists to keep the children's output off the state, and
      the only verdict that matters is whether the Map Run succeeded.

    Raises:
      TransientError: When any item failed retryably, so the Map retries the whole batch — safe,
        because asking twice for a retrieval already in progress is one of the two tolerated
        answers.
      Exception: The raw fault on a deterministic one, which fails this child and therefore the
        Map Run and the run.
    """
    items = event.get("Items") or []
    requested = retrieval.request_retrieval(
        [(item["srcBucket"], item["srcKey"]) for item in items]
    )

    logger.info("requested retrieval of %d object(s) in this batch", requested)
    observability.info("batch retrieval requested", items=len(items), objects=requested)
    return {"requested": requested}
