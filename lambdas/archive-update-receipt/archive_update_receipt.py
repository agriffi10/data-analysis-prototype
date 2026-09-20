"""update-receipt — the archive's receipt, rewritten to say what the restore did.

The receipt at ``{spaceRoot}system_settings/archive/{archiveId}/receipt.txt`` is the only
artifact of an archive the user can see, and it carries two fields that have been placeholders
 wrote it. This verb fills them in. **It rewrites; it never deletes and never
re-renders the whole document** — the archive lines record the archive RUN, and its start time
is the one field no restore can recompute, so a fresh render would silently blank it.

**One function, three states, and the state says which.** The ASL seeds ``$.restore.status``
before each invocation rather than the verb inferring it from what else is lying on the state:

  ``requested``    written immediately BEFORE the retrieval Map. The user is about to wait
                   hours and the receipt is the only durable place that says a restore is in
                   flight. A failure here is a whole-request failure, which it can afford to be
                   because nothing has been billed yet — which is also why it runs before the
                   Map and not after it.
  ``restored``     the data is back. A failure here does NOT fail the run: the outcome the user
                   asked for has already happened, and the ASL Catch carries on to the success
                   terminal. Most durable to least — data restored, then receipt, then
                   notification.
  ``incomplete``   some of it is back and the rest is not. This branch **always raises** after
                   writing what it can, which is the rollback verb's shape on the archive arm:
                   record the outcome, then fail the run deliberately. Its receipt write is
                   best-effort for the ``restored`` branch's reason — the data that landed has
                   landed either way.

**WHICH failure it raises is decided by COUNTING THE VAULT, never by what this run did.** Two
restores of one archive can run at once, and the first to finish sweeps the vault — so "the
archive is still there" cannot be inferred from this run having deleted nothing, and a user who
acts on a wrong version of that sentence can lose the only copy of their files. So the incomplete
branch counts the archived objects under the prefix and says only what the count proves: a full
count earns a body that calls the archive complete AS OF THIS MOMENT, and anything else — short,
empty, or a listing that would not answer — selects the cleared outcome, which claims nothing.
The count runs once, before the receipt is written, and rides on the state so the receipt line and
the notification cannot tell the user two different things.

The service name is the control plane, not the function, so one restore's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import notify, receipt, restore
from cpcommon import observability
from cpcommon.errors import TerminalError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")

REQUESTED = "requested"
RESTORED = "restored"
INCOMPLETE = "incomplete"


def _fallback_record(event) -> dict:
    """Composes the archive half of a receipt when there is no existing document to rewrite.

    Reachable only when S3 proved the receipt is absent — every other read fault raises, so a
    document this run merely failed to READ is never overwritten. Every field comes from what the
    restore already knows and is exact, with one exception: **the archive's own start time cannot
    be recovered**, so ``Requested`` renders as a placeholder. That is the whole reason the
    ordinary path rewrites rather than re-renders.

    ``Request ID`` is the ARCHIVE's id and not this restore's. They are deliberately different
    values, and the one that belongs on this document is the one that opened it.

    Args:
      event: The validated restore request.

    Returns:
      The record ``receipt.render`` describes.

    Raises:
      None.
    """
    archive = event.get("archive") or {}
    space = event.get("source") or {}
    return {
        "requestId": archive.get("archiveId"),
        "startedAt": None,
        "source": {"bucket": space.get("bucket"), "root": space.get("root")},
        "archive": {"bucket": archive.get("bucket"), "root": archive.get("root")},
        "objectCount": event.get("objectCount"),
        "totalBytes": event.get("totalBytes"),
    }


def _restore_state(event) -> dict:
    """Builds what the two restore lines render from.

    **The COUNTS come from the collector's verdict and the STAGE comes from the seed**, which is
    the split that matters: the seed says what this invocation is recording, and the run says
    what happened. An earlier version let the seed carry the counts too, so the sentence written
    on the receipt and the numbers in the failure message had two sources and could disagree —
    a receipt reading "40 of 100" beside a notification reading something else, with nothing to
    say which was right.

    Args:
      event: The validated restore request, carrying the seeded ``restore`` block and the
        collector's ``transferOutcome``.

    Returns:
      The restore's state, with the destination path composed from the authorized space and the
      counts taken from the run.

    Raises:
      None.
    """
    space = event.get("source") or {}
    restored, expected = _counts(event)
    return {
        **(event.get("restore") or {}),
        "destination": f"s3://{space.get('bucket')}/{space.get('root')}",
        "restored": restored,
        "expected": expected,
    }


def _archive_is_intact(event) -> bool:
    """Counts the vault, so the outcome this verb raises is earned rather than assumed.

    Args:
      event: The validated restore request, carrying the archive's location and the object count
        the restore plan recorded.

    Returns:
      True only when the prefix still holds every object the plan counted.

    Raises:
      None.
    """
    archive = event.get("archive") or {}
    return restore.archive_is_intact(
        archive.get("bucket"), archive.get("root"), event.get("objectCount")
    )


def _occupied(event) -> int:
    """Reads how many items were left alone because a file had appeared at their path.

    Read with a default rather than indexed: a verb rolled out ahead of the collector that
    supplies the field would otherwise fail a run whose only remaining work is telling the user
    what happened, and the absent case is the one this field was added to distinguish.

    Args:
      event: The validated restore request, carrying the collector's verdict.

    Returns:
      The occupied count, or zero when the collector reported none.

    Raises:
      None.
    """
    return (event.get("transferOutcome") or {}).get("occupied") or 0


def _counts(event) -> tuple[int, int]:
    """Reads how many objects came back and how many were planned, from the one place that knows.

    Args:
      event: The validated restore request, carrying the collector's verdict.

    Returns:
      ``(restored, expected)``.

    Raises:
      None.
    """
    outcome = event.get("transferOutcome") or {}
    return outcome.get("copied") or 0, outcome.get("expected") or 0


def _rewrite(event) -> str:
    """Reads the receipt back, replaces its two restore lines and writes it.

    Args:
      event: The validated restore request.

    Returns:
      The key the receipt was written to.

    Raises:
      TransientError: On a retryable S3 fault reading or writing.
      ClientError: On any other read fault, including a 403 — an ambiguous answer must not take
        the compose-a-fresh-one branch.
    """
    archive = event.get("archive") or {}
    bucket, key = archive.get("receiptBucket"), archive.get("receiptKey")
    existing = receipt.read(bucket, key)
    if existing is None:
        existing = receipt.render(_fallback_record(event))
    return receipt.write_text(bucket, key, receipt.rewrite(existing, _restore_state(event)))


@observability.traced("update-receipt")
@notify.notifies_on_failure("receipt")
def handler(event, context) -> dict:
    """Step Functions entry point: records the restore's stage on the archive's receipt.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The validated restore request, carrying the seeded ``restore`` block that says which
        stage this invocation is recording.
      context: The Lambda context, unused.

    Returns:
      The request with ``receiptKey`` on the paths that return at all.

    Raises:
      TerminalError: always, on the incomplete branch — one of ``restore_archive_cleared``,
        ``restore_incomplete_occupied`` and ``restore_incomplete``, chosen by counting the vault
        and by how many items were left alone rather than failed.
      TransientError: On a retryable S3 fault, so the state's Retry re-runs the verb. Safe: the
        key is a pure function of the request and the write is a whole-object PUT.
    """
    return _update_receipt(event)


def _update_receipt(event) -> dict:
    """Branches on the seeded stage, writes what it can, and fails the run when it must.

    Args:
      event: The validated restore request.

    Returns:
      The request with ``receiptKey``, on the ``requested`` and ``restored`` branches.

    Raises:
      TerminalError: one of the three partial-restore outcomes, on the incomplete branch.
      TransientError: On a retryable S3 fault, on the branches that do not swallow.
    """
    status = (event.get("restore") or {}).get("status")
    outcome = event.get("transferOutcome") or {}
    restored, expected = _counts(event)

    if status != INCOMPLETE:
        key = _rewrite(event)
        logger.info("receipt %s updated: restore %s", key, status)
        observability.info(
            "receipt updated",
            actor=(event.get("actor") or {}).get("username"),
            archive_id=(event.get("archive") or {}).get("archiveId"),
            objects=event.get("objectCount"),
            bytes=event.get("totalBytes"),
            status=status,
        )
        return {**event, "receiptKey": key}

    intact = _archive_is_intact(event)
    occupied = _occupied(event)
    counted = {**event, "restore": {**(event.get("restore") or {}), "archiveIntact": intact}}

    try:
        _rewrite(counted)
    except Exception as err:  # noqa: BLE001 - the data that landed has landed; the raise below stands
        logger.warning("the receipt could not record the partial restore: %s", err)

    observability.info(
        "restore incomplete",
        actor=(event.get("actor") or {}).get("username"),
        archive_id=(event.get("archive") or {}).get("archiveId"),
        objects=restored,
        failed=outcome.get("failed"),
        occupied=occupied,
        expected=expected,
        archive_intact=intact,
    )
    raise _incomplete_failure(restored, expected, occupied, intact=intact)


def _incomplete_failure(
    restored: int, expected: int, occupied: int, *, intact: bool
) -> TerminalError:
    """Chooses which of the three partial-restore outcomes this run earned.

    **The vault count takes precedence over everything**, because it is the only one of the three
    that is about the user's remaining copy rather than about this run's tidiness. Without a full
    count neither of the other two may be raised at all: both of their bodies say the archive was
    complete when the restore stopped, and a body that says so on an archive a sibling has already
    swept is the sentence that can cost the only copy.

    With the count in hand the occupied arm is the more specific of the two remaining, and it
    exists because "we could not copy your file" and "your own newer file was in the way and we
    left it alone" are different things to be told.

    Args:
      restored: How many objects landed.
      expected: How many the plan held.
      occupied: How many were left alone because a file had appeared at their path.
      intact: Whether the vault count found every archived object still there.

    Returns:
      The terminal error to raise, carrying the tokens its body fills.

    Raises:
      None.
    """
    if not intact:
        return TerminalError(
            "restore_archive_cleared",
            f"{restored} of {expected} objects were restored and the archive could not be "
            "confirmed as complete",
            tokens={"restored": str(restored), "total": str(expected)},
        )
    if occupied > 0:
        return TerminalError(
            "restore_incomplete_occupied",
            f"{restored} of {expected} objects were restored; {occupied} were left alone because "
            "a file had appeared at the same path",
            tokens={
                "restored": str(restored),
                "total": str(expected),
                "occupied": str(occupied),
            },
        )
    return TerminalError(
        "restore_incomplete",
        f"{restored} of {expected} objects were restored; the archive was kept and nothing was "
        "removed",
        tokens={"restored": str(restored), "total": str(expected)},
    )
