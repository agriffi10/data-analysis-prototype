"""write-manifest — the integrity record, written before anything is deleted.

The first state on the commit branch. It records what the run copied — request, actor, source,
counts — at the archive root, where the archived objects are and where the user is not.

**Its position in the machine is the requirement, not its contents.** Most durable to least: the
record that describes the archive, then the deletion of the source, then the receipt that tells
the user about it. A run interrupted between any two of those leaves a state an operator can read
and act on; the reverse order leaves a receipt for an archive that does not exist.

**Nothing may come to depend on this file.** SPEC-170 rebuilds every restore destination from the
archived keys themselves, because an archived key encodes its own origin. This is a cross-check
that can only ever fire when something is already wrong.

The service name is the control plane, not the function, so one archive's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import manifest, notify
from cpcommon import observability
from cpcommon.errors import TerminalError, TransientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


@observability.traced("write-manifest")
@notify.notifies_on_failure("manifest-record")
def handler(event, context) -> dict:
    """Step Functions entry point: writes ``_manifest.json`` at the archive root.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The request, carrying the archive destination, the counts and the stamped execution
        context.
      context: The Lambda context, unused.

    Returns:
      The request with the record's key.

    Raises:
      TerminalError: ``manifest_write_failed`` when the record cannot be written. It is a
        whole-request failure at the cheapest possible moment: nothing has been deleted yet, so
        the user still has every file, and the archive copy is left to the bucket's own lifecycle.
      TransientError: On a retryable S3 fault, so the state's Retry re-runs the verb — safe,
        because the key is a pure function of the archive root and the write is a whole-object
        PUT.
    """
    return _write_manifest(event)


def _write_manifest(event) -> dict:
    """Assembles the record from the state and writes it.

    Args:
      event: The request.

    Returns:
      The request with ``manifestKey``.

    Raises:
      TerminalError: ``manifest_write_failed``.
      TransientError: On a retryable S3 fault.
    """
    archive = event.get("archive") or {}
    source = event.get("source") or {}
    record = {
        "requestId": event.get("requestId"),
        "startedAt": (event.get("execution") or {}).get("startedAt"),
        "actor": (event.get("actor") or {}).get("username"),
        "source": {"bucket": source.get("bucket"), "root": source.get("root")},
        "objectCount": event.get("objectCount"),
        "totalBytes": event.get("totalBytes"),
    }

    try:
        key = manifest.write(archive.get("bucket"), archive.get("root"), record)
    except TransientError:
        raise
    except Exception as err:
        raise TerminalError(
            "manifest_write_failed",
            f"could not write the archive record under {archive.get('root')!r}: {err}",
        ) from err

    logger.info("archive record written to %s", key)
    observability.info(
        "archive record written",
        objects=event.get("objectCount"),
        bytes=event.get("totalBytes"),
    )
    return {**event, "manifestKey": key}
