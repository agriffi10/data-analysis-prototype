"""rollback — removes a partial archive copy, then fails the run.

Reached on the one branch of the commit gate that does not lead to a deletion. Some objects made
it into the vault and some did not, so the archive is not an archive: it is a partial copy of a
folder the user still has. This verb removes it and then raises, which is the outcome the whole
spec exists to guarantee — **the source is intact, and it was never in doubt.**

**What it deletes is what is THERE, listed from the archive prefix, rather than a list of keys
carried from the collector.** Two reasons, and the first is not the interesting one: keys are the
unbounded term, and a list of tens of thousands of them cannot ride a 256 KB state. The second is
that the listing is a strictly better answer to the question. The prefix is this request's alone —
``{kind}/{name}/archive/{uuid}/`` — so everything under it was put there by this archive and by
nothing else, including anything a batch copied before it died and never reported. A
collector-supplied list would omit exactly those.

**A rollback that itself fails partially does NOT change the outcome**, and the failure it raises
says so. The property that matters is that the source is intact; the residue is billed at the
GLACIER 90-day minimum, is unreachable by the user (the browser has no relationship with this
bucket), and is swept by the bucket's own 7-year expiry. Reporting it and carrying on is the
honest handling; retrying it forever is not.

**The copied and total it names are the collector's ``shown`` counts, in files**, where a folder
placeholder counts only when it is one of the things that did not copy. The residue it names is
every object that could not be removed, placeholders included, for the same reason: each one is a
thing left behind.

The service name is the control plane, not the function, so one archive's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import counts, delete, notify
from cpcommon import observability
from cpcommon.errors import TerminalError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


@observability.traced("rollback")
@notify.notifies_on_failure("rollback")
def handler(event, context) -> dict:
    """Step Functions entry point: removes the partial archive copy and fails the run.

    It ALWAYS raises. That is not an error path within the verb — it is the verb's purpose: the
    commit gate has already decided this archive did not happen, and the only question left is
    whether the vault was left clean.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The request, carrying the archive destination and the transfer's verdict.
      context: The Lambda context, unused.

    Returns:
      Never — the annotation is the shared handler shape, and every path raises.

    Raises:
      TerminalError: ``archive_incomplete`` when the partial copy was removed cleanly, or
        ``archive_rollback_incomplete`` when some of it could not be. Both name how many files
        copied out of how many, and both say plainly that nothing was deleted.
      TransientError: On a retryable S3 fault, so the state's Retry re-runs the verb — safe,
        because deleting an already-absent key is not an error.
    """
    return _rollback(event)


def _rollback(event) -> dict:
    """Lists the archive prefix, deletes what is under it and raises the gate's failure.

    Args:
      event: The request with its archive destination and transfer verdict.

    Returns:
      Never.

    Raises:
      TerminalError: ``archive_incomplete`` or ``archive_rollback_incomplete``.
      TransientError: On a retryable S3 fault.
    """
    archive = event.get("archive") or {}
    bucket, root = archive.get("bucket"), archive.get("root")
    outcome = event.get("transferOutcome") or {}
    copied = outcome.get("copied") or 0
    expected = outcome.get("expected") or 0

    removed = delete.delete_prefix(bucket, root)

    logger.info(
        "rolled back %d of %d archived object(s) after %d of %d copied",
        removed["deleted"],
        removed["listed"],
        copied,
        expected,
    )
    observability.info(
        "archive rolled back",
        objects=copied,
        failed=outcome.get("failed"),
        expected=expected,
        removed=removed["deleted"],
        residue=removed["failed"],
    )

    shown_copied, shown_total, _ = counts.shown_outcome(outcome)
    tokens = {"copied": str(shown_copied), "total": str(shown_total)}
    if removed["failed"]:
        raise TerminalError(
            "archive_rollback_incomplete",
            f"{copied} of {expected} objects copied; {removed['failed']} archived object(s) "
            "could not be removed. The source was not touched.",
            tokens={**tokens, "residue": str(removed["failed"])},
        )
    raise TerminalError(
        "archive_incomplete",
        f"{copied} of {expected} objects copied, so the archive copy was removed and the source "
        "was not touched.",
        tokens=tokens,
    )
