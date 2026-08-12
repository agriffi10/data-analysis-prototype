"""write-receipt — the last state, and the only artifact of an archive the user can see.

Written AFTER the source deletion, so a receipt only ever exists for an archive that actually
completed. It carries the UUID, which is the user's only route to a restore — the archived objects
are in a bucket the browser has no relationship with, and the reports folder that holds this file
is the one place the id appears outside a notification.

**Its failure is a terminal failure of the run even though the data is safely archived**, and that
is FR-006's decision rather than an oversight: a user with no receipt has no id, and therefore no
route to a restore. The failure message says the data IS archived and names the request id, so the
run is recoverable by hand rather than merely reported.

The service name is the control plane, not the function, so one archive's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import notify, receipt
from cpcommon import observability
from cpcommon.errors import TerminalError, TransientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


@observability.traced("write-receipt")
@notify.notifies_on_failure("receipt")
def handler(event, context) -> dict:
    """Step Functions entry point: writes the receipt into the user's own space.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The request, carrying the source, the archive destination, the counts and the
        stamped execution context.
      context: The Lambda context, unused.

    Returns:
      The request with the receipt's key.

    Raises:
      TerminalError: ``receipt_write_failed`` when the receipt cannot be written. The data is
        archived and the source is gone by this point, so the message says so and names the
        request id.
      TransientError: On a retryable S3 fault, so the state's Retry re-runs the verb — safe,
        because the key is a pure function of the request and the write is a whole-object PUT.
    """
    return _write_receipt(event)


def _write_receipt(event) -> dict:
    """Renders the receipt from the state and writes it to the space's own bucket.

    **The key comes off the state, resolved once by validate-authorize.** Recomputing it here
    would be a second construction of a string SPEC-168 deliberately resolves in one place — and
    it would leave ``archive.receiptKey`` a field that rides the whole run and is never read.

    Args:
      event: The request.

    Returns:
      The request with ``receiptKey``.

    Raises:
      TerminalError: ``receipt_write_failed``.
      TransientError: On a retryable S3 fault.
    """
    source = event.get("source") or {}
    archive = event.get("archive") or {}
    record = {
        "requestId": event.get("requestId"),
        "startedAt": (event.get("execution") or {}).get("startedAt"),
        "source": {"bucket": source.get("bucket"), "root": source.get("root")},
        "archive": {"bucket": archive.get("bucket"), "root": archive.get("root")},
        "objectCount": event.get("objectCount"),
        "totalBytes": event.get("totalBytes"),
    }

    try:
        key = receipt.write(archive.get("receiptBucket"), archive.get("receiptKey"), record)
    except (TerminalError, TransientError):
        raise
    except Exception as err:
        raise TerminalError(
            "receipt_write_failed",
            f"the archive completed but its receipt could not be written: {err}",
            tokens={"requestId": str(event.get("requestId"))},
        ) from err

    logger.info("receipt written to %s", key)
    observability.info(
        "receipt written",
        actor=(event.get("actor") or {}).get("username"),
        objects=event.get("objectCount"),
        bytes=event.get("totalBytes"),
    )
    return {**event, "receiptKey": key}
