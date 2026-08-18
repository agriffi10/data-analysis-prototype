"""poll-restore — the only wait loop in this repo, and the one thing GLACIER makes unavoidable.

Every other control plane here finishes in seconds and reports; this one sits
between a billed request and a copy that cannot start until S3 has finished, which at the
``Standard`` tier is 3-5 hours. So the machine grows ``Wait`` -> this verb -> ``Choice``, and this
verb answers one question: **is every archived object readable yet.**

**Completion is the ``Restore`` header and nothing else.** The archived object stays ``GLACIER``
throughout — what a retrieval produces is a temporary readable copy the header describes — so
neither the storage class nor the object's presence moves when the wait ends.
``arcommon.retrieval.classify`` holds the three-way rule, including the case that distinguishes a
slow restore from a dropped one: no header at all, on an object still in a Glacier class, means
nothing ever asked for it, and reading that as "not yet" would burn every remaining iteration
before reporting a timeout for something that was never going to complete.

**It samples, and the progress record is an S3 POINTER.** The loop runs for hours; a per-object
status list on the state is the 256 KB failure whose overflow escapes every ``Catch``, which on
this plane is a run that tells the user nothing at all. What rides is the small scalar block the
``Choice`` branches on, and the index it reached lives beside the plan in the admin bucket.

**The iteration cap lives in Python, not in the ASL ``Choice``.** A literal in the rendered
machine and a constant in ``config`` would be two homes for one number, and they would only
disagree on a restore that was already going badly.

The service name is the control plane, not the function, so one restore's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import notify, plan, retrieval
from cpcommon import observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


@observability.traced("poll-restore")
@notify.notifies_on_failure("poll")
def handler(event, context) -> dict:
    """Step Functions entry point: reports how far the retrieval has got.

    Args:
      event: The validated restore request, carrying the archive location and the restore plan's
        key.
      context: The Lambda context, unused.

    Returns:
      The request with a ``restorePoll`` block — the iteration count, how far the sweep reached,
      and the two booleans the ``Choice`` branches on. ``complete`` and ``exhausted`` are
      computed here rather than compared in ASL so the cap has one home.

    Raises:
      TerminalError: ``restore_never_requested`` when an archived object carries no ``Restore``
        header and is still in a Glacier class, or cannot be read back at all;
        ``plan_unreadable`` or ``plan_superseded`` when the plan is not this run's.
      TransientError: On a retryable S3 fault — a poll that cannot see the archive retries rather
        than reporting progress it did not observe.
    """
    return _poll_restore(event)


def _poll_restore(event) -> dict:
    """Reads the recorded progress, sweeps forward from it, and records where it got to.

    The progress is written even when the sweep found pending objects — that is the ordinary case
    and it is the whole point, because the next iteration then re-heads one page rather than the
    archive.

    Args:
      event: The validated restore request.

    Returns:
      The request with its ``restorePoll`` block.

    Raises:
      TerminalError: ``restore_never_requested``, ``plan_unreadable`` or ``plan_superseded``.
      TransientError: On a retryable S3 fault.
    """
    archive = event.get("archive") or {}
    bucket = archive.get("bucket")

    loaded = plan.load_restore_plan(event.get("planKey"), event)
    keys = [entry["archiveKey"] for entry in loaded["objects"]]

    progress_key = plan.restore_progress_key(event)
    progress = retrieval.read_progress(progress_key, len(keys))
    polls = progress["pollCount"] + 1

    through, done = retrieval.advance(bucket, keys, progress["completedThrough"])
    retrieval.write_progress(progress_key, event.get("requestId"), polls, through, len(keys))

    logger.info(
        "poll %d of the retrieval: %d of %d object(s) ready", polls, through, len(keys)
    )
    observability.info(
        "retrieval polled",
        actor=(event.get("actor") or {}).get("username"),
        archive_id=archive.get("archiveId"),
        poll_count=polls,
        objects=through,
        expected=len(keys),
        complete=done,
    )
    return {
        **event,
        "restorePoll": {
            "pollCount": polls,
            "completedThrough": through,
            "objectCount": len(keys),
            "complete": done,
            "exhausted": not done and retrieval.exhausted(polls),
        },
    }
