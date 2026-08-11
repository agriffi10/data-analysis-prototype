"""The copy plan, passed between states by pointer rather than inline.

inspect-source writes the expanded object list here and threads its key onward; SPEC-166's
manifest builder loads it once. It is not on the state, and the reason is the one this fleet
learned twice: at ``SEND_MAX_OBJECTS`` the plan is tens of megabytes and the Step Functions
payload limit is 256 KB, so the list could not ride even once — let alone through a Map's item
selector, which copies the whole state into every item.

It lives in the admin bucket rather than a user's space: the SPA never browses it, so the plan
needs no hidden-folder convention, and a user cannot delete it out from under a running
execution — they do hold delete rights in their own space. Nothing deletes it here either; a
lifecycle rule expires it (``modules/analytics/s3.tf``).

**The key is the request id, not a digest of the request.** Table-share hashes the fields that
identify a share because it has no request id and needed replay safety; this plane has one, and
it is already the FIFO ``MessageDeduplicationId`` — the only double-submit guard on the queue.
So the key is execution-stable for free: a Retry of inspect-source rewrites the same key with
the same content rather than leaving a second plan behind, and two different requests can never
collide however similar their selections are.

``messages`` is imported for its side effect as well as tidiness: it registers this domain's
reason codes, and a terminal error validates its reason at construction. Without the import,
a process importing only this module raises a validation error where it meant to write a
refusal — the same import-order trap that once shipped three unraisable reason codes.

Attributes:
  PREFIX: Prefix inside the admin bucket, matching the lifecycle rule's filter.
  BASENAME: The plan object's basename.
"""

import json

from cpcommon import clients, errors, events
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError

from . import messages  # noqa: F401

PREFIX = "file-send"
BASENAME = "copy-plan.json"


def plan_key(request: dict) -> str:
    """Derives the plan's S3 key from the request id.

    Args:
      request: The validated send request.

    Returns:
      The plan key under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id. Falling back to
        a shared or random key would give up the property the id buys — a Retry writing the
        same object rather than a second one — so it refuses instead. validate-authorize
        type-checks the id before this can be reached; the guard is here because the value
        becomes a KEY, and a key built from ``None`` is a real object in a real bucket.
    """
    request_id = request.get("requestId")
    if not isinstance(request_id, str) or not request_id.strip():
        raise TerminalError(events.MALFORMED, "a copy plan key needs the request id")
    return f"{PREFIX}/{request_id.strip()}/{BASENAME}"


def write(request: dict, source: dict, sender: str, objects: list, total_bytes: int) -> str:
    """Writes the copy plan to the admin bucket and returns its key.

    The plan records the source it was expanded from and the sender it belongs to alongside the
    objects, so a reader — SPEC-166's manifest builder, or an operator looking at a failed
    send — does not have to join it back against the execution to know what it describes.

    Args:
      request: The validated request, which determines the key.
      source: The authorized source, carrying the bucket and root.
      sender: The verified sender's username, which namespaces every destination.
      objects: The expanded objects, each carrying its item, relative key, source key and size.
      total_bytes: How many bytes those objects hold.

    Returns:
      The key the plan was written to.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs inspect-source —
        safe, because the key is a pure function of the request id and the verb is read-only
        besides this write.
      TerminalError: ``malformed_event`` from the key derivation.
      ClientError: Any deterministic fault propagates.
    """
    key = plan_key(request)
    body = json.dumps(
        {
            "source": {"bucket": source["bucket"], "root": source["root"]},
            "sender": sender,
            "objects": objects,
            "objectCount": len(objects),
            "totalBytes": total_bytes,
        },
        separators=(",", ":"),
    ).encode()
    try:
        clients.s3().put_object(
            Bucket=cpconfig.ADMIN_BUCKET, Key=key, Body=body, ContentType="application/json"
        )
    except Exception as err:
        errors.raise_if_transient(err, f"put {cpconfig.ADMIN_BUCKET}/{key}")
        raise
    return key
