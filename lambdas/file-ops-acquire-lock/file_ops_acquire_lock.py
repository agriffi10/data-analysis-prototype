"""acquire-lock — claims the space (or spaces) this request operates on.

FIFO orders DELIVERY per space, but the Pipe starts the machine ``FIRE_AND_FORGET`` and returns,
so two operations in one space can run at once. On this plane that is not a raced schema: a
delete removing objects a concurrent move has already relocated is silent, unrecoverable data
loss, because the buckets have versioning off.

**THIS VERB IS CALLED IN A LOOP AND MUST ECHO WHAT IT WAS GIVEN.** The machine threads the running
object through ``Payload.$ = "$"`` with ``OutputPath = "$.Payload"``, so a Task's result REPLACES
the whole state. A verb returning only its own fields would destroy the request, the actor and the
outcome list on the first pass — before the ``Wait`` had even run — and every later state would
then read paths that are gone.

**BOTH LOCKS OR NEITHER.** A copy or move into a different space takes two, in digest-sorted
order, and on failing to claim the second this verb releases the first before reporting "not yet".
Sorted order is what makes two locks safe: unordered acquisition deadlocks when two requests cross
in opposite directions. Releasing the first is what keeps a waiter from holding a lock across the
``Wait`` — so at give-up the request holds nothing, and the machine's give-up release is a no-op
in every case it can reach.

The one case that CAN strand a lock is a fault inside this verb between the two claims: the
invocation returns nothing, no tag reaches the state, and the first lock is held with nobody able
to name it. That is an accepted second staleness case beside the machine-ceiling one, recovered by
the steal, and it is recorded rather than solved — splitting the claims into two states would
double the loop and reintroduce the partial hold this design avoids.

Attributes:
  _ATTEMPT: Where the running attempt count lives on the state.
"""

import logging

from cpcommon import observability
from focommon import lock, notify
from focommon.config import LOCK_MAX_ATTEMPTS

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-ops")

_ATTEMPT = "attempt"


def _targets(event: dict) -> list:
    """Returns the spaces this request must hold, in digest-sorted order.

    Sorted by DIGEST rather than by name, because the digest is what the lock key is built from —
    sorting by anything else would let two requests that cross in opposite directions order their
    claims differently and deadlock.

    A copy or move whose destination resolves to the same space as its source yields ONE target,
    not two: claiming the same lock twice would take it, then re-claim it, and the second tag
    would be the only one the release could use — correct by luck rather than by construction.

    Args:
      event: The running request object.

    Returns:
      A list of ``(bucket, root)`` pairs, sorted by their digest.

    Raises:
      None.
    """
    source = event.get("source") or {}
    targets = {(source.get("bucket"), source.get("root"))}
    destination = event.get("destination")
    if isinstance(destination, dict):
        targets.add((destination.get("bucket"), destination.get("root")))
    usable = [pair for pair in targets if pair[0] and pair[1]]
    return sorted(usable, key=lambda pair: lock.space_digest(*pair))


@observability.traced("acquire-lock")
@notify.notifies_on_failure("acquire-lock")
def handler(event, context) -> dict:
    """Claims every space this request touches, or reports that it must wait.

    Returns the whole event with a ``lock`` record merged in, never a bare result — see the module
    docstring. The record carries the attempt count, the two booleans the machine's ``Choice``
    reads, and the tags the release must present.

    **The tags are REPLACED on every attempt, never accumulated.** A re-claim rewrites the lock
    object and so returns a new tag; releasing against an earlier one is a silent no-op that
    leaves the space locked until the staleness rule recovers it, which is hours. Each tag rides
    beside the space it belongs to in ``spaces``, which is the only shape the release reads —
    a parallel list of bare tags would be a second place for the pairing to drift.

    Args:
      event: The running request object, carrying the resolved source, the optional destination
        and the execution ARN.
      context: The Lambda context, unused.

    Returns:
      The event with its ``lock`` record replaced.

    Raises:
      ValueError: If the execution ARN is missing, which would write a lock every later reader
        correctly interprets as unheld; or if no space on the event can be identified, which
        would otherwise report a successful claim while holding nothing and let the machine
        proceed unlocked. Failing closed here matches the machine's own third Choice clause,
        which exists to route an acquire output that lost its shape to the give-up rather than
        to let it look like progress.
    """
    holder = (event.get("execution") or {}).get("arn")
    attempt = int((event.get("lock") or {}).get(_ATTEMPT, 0)) + 1

    targets = _targets(event)
    if not targets:
        raise ValueError("no identifiable space to lock")

    held: list = []
    for bucket, root in targets:
        acquired, etag = lock.acquire(bucket, root, holder)
        if not acquired:
            for prior_bucket, prior_root, prior_etag in held:
                lock.release(prior_bucket, prior_root, prior_etag)
            observability.info(
                "space lock not yet available",
                attempt=attempt,
                exhausted=attempt >= LOCK_MAX_ATTEMPTS,
                released_partial=len(held),
            )
            return {
                **event,
                "lock": {
                    _ATTEMPT: attempt,
                    "acquired": False,
                    "exhausted": attempt >= LOCK_MAX_ATTEMPTS,
                },
            }
        held.append((bucket, root, etag))

    logger.info("holding %d space lock(s) after %d attempt(s)", len(held), attempt)
    return {
        **event,
        "lock": {
            _ATTEMPT: attempt,
            "acquired": True,
            "exhausted": False,
            "spaces": [{"bucket": b, "root": r, "etag": e} for b, r, e in held],
        },
    }
