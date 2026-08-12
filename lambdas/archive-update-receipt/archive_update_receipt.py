"""update-receipt — the archive's receipt, rewritten to say what the restore did.

SPEC-171 FR-006. The receipt at ``{spaceRoot}archive/{archiveId}/receipt.txt`` is the only
artifact of an archive the user can see, and it carries two fields that have been placeholders
since SPEC-169 wrote it. This verb fills them in. **It rewrites; it never deletes and never
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
  ``incomplete``   some of it is back and the rest is not. This branch **always raises**
                   ``restore_incomplete`` after writing what it can, which is the rollback verb's
                   shape on the archive arm: record the outcome, then fail the run deliberately.
                   Its receipt write is best-effort for the ``restored`` branch's reason — the
                   data that landed has landed either way.

The service name is the control plane, not the function, so one restore's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import notify, receipt
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
    values (SPEC-170 FR-001), and the one that belongs on this document is the one that opened it.

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
      TerminalError: ``restore_incomplete`` — always, on the incomplete branch — naming how many
        objects were restored, that the archive is intact under the same id, and that requesting
        it again will report the files that did land.
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
      TerminalError: ``restore_incomplete`` on the incomplete branch.
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

    try:
        _rewrite(event)
    except Exception as err:  # noqa: BLE001 - the data that landed has landed; the raise below stands
        logger.warning("the receipt could not record the partial restore: %s", err)

    observability.info(
        "restore incomplete",
        actor=(event.get("actor") or {}).get("username"),
        archive_id=(event.get("archive") or {}).get("archiveId"),
        objects=restored,
        failed=outcome.get("failed"),
        expected=expected,
    )
    raise TerminalError(
        "restore_incomplete",
        f"{restored} of {expected} objects were restored; the archive was kept and nothing was "
        "deleted",
        tokens={"restored": str(restored), "total": str(expected)},
    )
