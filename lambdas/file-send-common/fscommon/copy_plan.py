"""The copy plan, passed between states by pointer rather than inline.

inspect-source writes the expanded object list here and threads its key onward; the transfer's
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

The transfer added the manifest and the Map Run's results export to this module, so one
place owns every admin-bucket key this plane writes. The manifest's BYTES and its reader belong
to ``cpcommon.transfer`` — the engine is shared with table-share and, later, archive — but where
this plane puts them is this plane's business.

**Both keys are grouped by the request id, and NEITHER carries the execution name.** That is the
one visible difference from table-share's layout, and it is a consequence of this plane having a
request id at all. Table-share has none: its keys are a digest of the request, two overlapping
executions of one share collide on that digest, and its manifest's LINES depend on which
recipients the guard accepted — so a shared manifest key there would let one run copy for a
recipient the other's guard had just refused. Here the id is the browser's per-submit
``MessageDeduplicationId``, and a redelivery of one SQS message cannot run a second execution
carrying it — the Pipe's deterministic execution name refuses that with ``ExecutionAlreadyExists``
(verified against the deployed machine). A Retry of the manifest verb rewrites the same key with
the same content, which is the property that matters. A NEW message reusing the id after the
five-minute dedup window is not a redelivery, and nothing here refuses it: the browser never
sends one, but a hand-built request would share both keys with a run still going, and either run
could then copy the other's plan.

Attributes:
  PREFIX: Prefix inside the admin bucket, matching the lifecycle rule's filter.
  BASENAME: The plan object's basename.
  MANIFEST_BASENAME: The transfer manifest's basename.
  RESULTS_FOLDER: Folder under the request's prefix that the Distributed Map's ResultWriter
    exports into. Step Functions appends its own Map Run component below it.
"""

import json

from cpcommon import clients, errors, events
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError

from . import messages  # noqa: F401

PREFIX = "file-send"
BASENAME = "copy-plan.json"
MANIFEST_BASENAME = "transfer-manifest.jsonl"
RESULTS_FOLDER = "results"


def _request_folder(request: dict, what: str) -> str:
    """Derives the folder every artifact of one request shares, from the request id.

    Args:
      request: The validated send request.
      what: The artifact being keyed, for the refusal's detail.

    Returns:
      The folder under the admin bucket, ending in a slash.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id. Falling back to
        a shared or random key would give up the property the id buys — a Retry writing the
        same object rather than a second one — so it refuses instead. validate-authorize
        type-checks the id before this can be reached; the guard is here because the value
        becomes a KEY, and a key built from ``None`` is a real object in a real bucket.
    """
    request_id = request.get("requestId")
    if not isinstance(request_id, str) or not request_id.strip():
        raise TerminalError(events.MALFORMED, f"a {what} key needs the request id")
    return f"{PREFIX}/{request_id.strip()}/"


def plan_key(request: dict) -> str:
    """Derives the plan's S3 key from the request id.

    Args:
      request: The validated send request.

    Returns:
      The plan key under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id.
    """
    return f"{_request_folder(request, 'copy plan')}{BASENAME}"


def transfer_manifest_key(request: dict) -> str:
    """Derives the transfer manifest's key, beside the plan it was expanded from.

    Args:
      request: The validated send request.

    Returns:
      The manifest key under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id.
    """
    return f"{_request_folder(request, 'transfer manifest')}{MANIFEST_BASENAME}"


def transfer_results_prefix(request: dict) -> str:
    """Derives the prefix the Map Run's ResultWriter exports under.

    Args:
      request: The validated send request.

    Returns:
      The results prefix under the admin bucket, with NO trailing slash — Step Functions
      appends its own Map Run component and manifest basename below it.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id.
    """
    return f"{_request_folder(request, 'transfer results')}{RESULTS_FOLDER}"


def write(request: dict, source: dict, sender: str, objects: list, total_bytes: int) -> str:
    """Writes the copy plan to the admin bucket and returns its key.

    The plan records the source it was expanded from and the sender it belongs to alongside the
    objects, so a reader — the manifest builder, or an operator looking at a failed
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


def load(key: str) -> dict:
    """Reads a plan back for the transfer manifest.

    Every unreadable shape is a WHOLE-REQUEST terminal, never a partial plan handed to the
    manifest builder. A plan short of its objects would produce a manifest short of its lines,
    the copy would succeed over it, and every recipient would be told the send went well while
    holding some of what was sent — the silent-partial-success failure this plane's collector
    exists to make impossible one stage later.

    The sender is read back rather than taken from the state for the same reason the plan
    records it: the destinations are built from it, and the plan is the object that knows which
    sender its keys were expanded for.

    Args:
      key: The plan key, as inspect-source threaded it onward.

    Returns:
      ``{"source": {"bucket", "root"}, "sender": str, "objects": [...], "totalBytes": int}``.

    Raises:
      TransientError: On a retryable S3 fault; the caller's Retry re-runs the verb.
      TerminalError: ``copy_failed`` when the plan is absent, is not valid JSON, is not an
        object, carries no objects, is SHORT OF THE COUNT IT RECORDS, names no sender or source
        bucket, or holds an entry missing the fields a destination is built from.
        inspect-source wrote it earlier in this same execution, so a failure here means the
        object is missing or corrupt, which no retry fixes.

        **The count check is what makes the paragraph above true rather than aspirational.** A
        non-empty list is not a complete one, and a truncated plan is precisely the shape that
        produces a manifest short of its lines, a copy that succeeds over it, and a recipient
        told the send went well while holding some of what was sent. The plan records its own
        ``objectCount`` at write time, so the check costs one comparison.
    """
    try:
        body = clients.s3().get_object(Bucket=cpconfig.ADMIN_BUCKET, Key=key)["Body"].read()
    except Exception as err:
        errors.raise_if_transient(err, f"get {cpconfig.ADMIN_BUCKET}/{key}")
        raise TerminalError("copy_failed", f"could not read copy plan {key}: {err}") from err

    try:
        plan = json.loads(body)
    except ValueError as err:
        raise TerminalError("copy_failed", f"copy plan {key} is not valid JSON: {err}") from err

    if not isinstance(plan, dict):
        raise TerminalError("copy_failed", f"copy plan {key} is not an object")
    objects = plan.get("objects")
    if not isinstance(objects, list) or not objects:
        raise TerminalError("copy_failed", f"copy plan {key} carries no objects")
    recorded = plan.get("objectCount")
    if not isinstance(recorded, int) or isinstance(recorded, bool) or len(objects) != recorded:
        raise TerminalError(
            "copy_failed",
            f"copy plan {key} holds {len(objects)} objects but records {recorded!r}",
        )
    if not isinstance(plan.get("sender"), str) or not plan["sender"]:
        raise TerminalError("copy_failed", f"copy plan {key} names no sender")
    if not (plan.get("source") or {}).get("bucket"):
        raise TerminalError("copy_failed", f"copy plan {key} names no source bucket")
    for entry in objects:
        if not isinstance(entry, dict) or not entry.get("item") or not entry.get("srcKey"):
            raise TerminalError(
                "copy_failed", f"copy plan {key} holds an object with no item name or source key"
            )
    return plan
