"""release-lock — frees every space this request held.

Reached on every terminal path the machine's graph can walk, which is why it must never be the
reason a request reports failure: a request that did its work and then failed on its own
bookkeeping would be a worse outcome than a lock the staleness rule recovers anyway.

**IT RELEASES BY OVERWRITING, NEVER BY DELETING.** "Free" is a STATE of the lock object rather
than its absence, which is what keeps a stolen lock detectable by compare-and-set — and the
execution role carries a Deny on ``s3:DeleteObject`` for the admin bucket, so the property is
enforced rather than merely intended.

A release with nothing to release is a no-op, not an error. Three paths reach this verb and one of
them — the give-up — holds nothing by construction, because the acquire releases its first lock
before reporting that it must wait.
"""

import logging

from cpcommon import observability
from focommon import lock

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-ops")


@observability.traced("release-lock")
def handler(event, context) -> dict:
    """Frees every lock the acquire recorded, against the tag it recorded.

    No ``@notifies_on_failure``: this verb has no user-facing failure to report. Its own errors
    are swallowed by the lock module, and the machine's Catch routes onward regardless.

    Args:
      event: The running request object, carrying the ``lock`` record when one was taken.
      context: The Lambda context, unused.

    Returns:
      A count of what was released, for the log and the trace.

    Raises:
      None.
    """
    spaces = (event.get("lock") or {}).get("spaces") or []
    if not spaces:
        logger.info("nothing to release")
        return {"released": 0}

    for space in spaces:
        lock.release(space.get("bucket"), space.get("root"), space.get("etag"))

    observability.info("space locks released", released=len(spaces))
    return {"released": len(spaces)}
