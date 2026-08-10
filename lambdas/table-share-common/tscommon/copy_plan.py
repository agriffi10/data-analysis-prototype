"""The copy plan, passed between states by pointer rather than inline.

inspect-source writes the source object list here and threads its key onward; copy-objects
loads it once per recipient.

It is not on the state, and the reason is measured rather than assumed: the list runs to the
1000-object cap, the Map's item selector copies the whole state into every item, and the result
path merges the per-recipient results back in. At the shipped caps with ordinary Hive keys of
around 140 characters that reached **249 KB — 95%** of the 256 KB state-payload limit, and 71%
with zero failures. Breaching it destroys every per-recipient outcome the Map exists to preserve.
By pointer the same state is about 34%. The same indirection, for the same reason, as the
data-quality manifest.

It lives in the admin bucket rather than a user's space: the SPA never browses it, so the plan
needs no hidden-folder convention, and a user cannot delete it out from under a running
execution — they do hold delete rights in their own space. Nothing deletes it here either; a
lifecycle rule expires it.

``messages`` is imported for its side effect as well as its constants: it registers this
domain's reason codes, and a terminal error validates its reason at construction. Without the
import, the failure below raises a validation error in any process that has not separately
imported it — true of a process importing only this module, and the same class of import-order
trap that once shipped three unraisable reason codes.

This module also owns the transfer manifest's KEY LAYOUT (SPEC-160). The manifest's bytes and
its reader belong to ``cpcommon.transfer`` — the engine is shared with the file-send and
archive planes — but where table-share puts it, and what makes that key unique, is this
plane's business and belongs beside the plan it sits next to.

Attributes:
  PREFIX: Prefix inside the admin bucket, matching the lifecycle rule's filter.
  BASENAME: The plan object's basename.
  MANIFEST_BASENAME: The transfer manifest's basename.
  RESULTS_FOLDER: Folder under the execution's prefix that the Distributed Map's ResultWriter
    exports into. Step Functions appends its own Map Run component below it.
"""

import hashlib
import json

from cpcommon import clients, errors
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError

from . import messages  # noqa: F401

PREFIX = "table-share"
BASENAME = "copy-plan.json"
MANIFEST_BASENAME = "transfer-manifest.jsonl"
RESULTS_FOLDER = "results"


def request_digest(request: dict) -> str:
    """Digests the fields that identify a share.

    Args:
      request: The share request, carrying the actor, source and result name.

    Returns:
      The hex digest both this plane's admin-bucket keys are grouped under.

    Raises:
      None.
    """
    source = request.get("source") or {}
    return hashlib.sha256(
        "\x00".join(
            [
                str(request.get("actor") or ""),
                str(source.get("database") or ""),
                str(source.get("table") or ""),
                str(request.get("tableName") or ""),
            ]
        ).encode()
    ).hexdigest()


def transfer_manifest_key(request: dict, execution_name: str) -> str:
    """Derives the transfer manifest's key, which is unique to ONE execution.

    That is the difference from ``plan_key`` beside it, and it is not stylistic. A copy plan
    is a pure function of the request, and two overlapping executions colliding on one plan
    key is harmless because both plans describe the same object set. A manifest's lines depend
    on which recipients the guard Map accepted — time- and destination-dependent — so on a
    shared key the later execution would overwrite the earlier one's manifest, and a Map Run
    could copy for a recipient its own guard had refused as ``conflict``.

    Args:
      request: The share request.
      execution_name: The Step Functions execution name, stamped onto the state by a Pass.

    Returns:
      The manifest key under the admin bucket.

    Raises:
      ValueError: If no execution name was stamped. Falling back to a shared key would
        reintroduce exactly the collision this component exists to prevent, so it refuses.
    """
    if not execution_name:
        raise ValueError("a transfer manifest key needs the execution name")
    return f"{PREFIX}/{request_digest(request)}/{execution_name}/{MANIFEST_BASENAME}"


def transfer_results_prefix(request: dict, execution_name: str) -> str:
    """Derives the prefix the Map Run's ResultWriter exports under, for the same execution.

    Args:
      request: The share request.
      execution_name: The Step Functions execution name.

    Returns:
      The results prefix under the admin bucket, with no trailing slash — Step Functions
      appends its own Map Run component and manifest basename below it.

    Raises:
      ValueError: If no execution name was stamped.
    """
    if not execution_name:
        raise ValueError("a transfer results prefix needs the execution name")
    return f"{PREFIX}/{request_digest(request)}/{execution_name}/{RESULTS_FOLDER}"


def plan_key(request: dict) -> str:
    """Derives the plan's S3 key as a pure function of the request.

    Table-share has no request id, so the key is a digest of the fields that identify the
    share. That makes it replay-safe: a Retry of inspect-source rewrites the same key with the
    same content rather than leaving a second plan behind.

    Two executions can overlap on one key. The FIFO message group is the source table, but the
    Pipe is fire-and-forget, so SQS considers the message handled as soon as the start call
    returns rather than when the execution finishes — a group serializes starts, not runs, and
    redelivery after a crash or a redrive opens the same window. It is still safe as a bounded
    claim: a collision needs the same actor, source database, source table and result name, and
    those requests list the same prefix, so both plans describe the same object set and either
    is correct for either execution. The residual exposure is a source mutated between the two
    listings, where the earlier execution would copy the later snapshot. Nothing here silently
    mixes two different sources, because the digest covers the database and table. Making it
    airtight would take an execution-unique salt threaded through the state, which costs an ASL
    payload-shape change the bounded exposure did not justify. SPEC-160 pays that cost for the
    transfer manifest, where the argument above does NOT carry — see
    ``transfer_manifest_key``. The plan is deliberately left as it was.

    Args:
      request: The share request, carrying the actor, source and result name.

    Returns:
      The plan key under the admin bucket.

    Raises:
      None.
    """
    return f"{PREFIX}/{request_digest(request)}/{BASENAME}"


def write(request: dict, objects: list) -> str:
    """Writes the plan to the admin bucket and returns its key.

    Args:
      request: The share request, which determines the key.
      objects: The planned source objects.

    Returns:
      The key the plan was written to.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs inspect-source —
        safe, because the key is a pure function of the request and the verb is read-only
        besides this write.
      ClientError: Any deterministic fault propagates.
    """
    key = plan_key(request)
    body = json.dumps({"objects": objects}, separators=(",", ":")).encode()
    try:
        clients.s3().put_object(
            Bucket=cpconfig.ADMIN_BUCKET, Key=key, Body=body, ContentType="application/json"
        )
    except Exception as err:
        errors.raise_if_transient(err, f"put {cpconfig.ADMIN_BUCKET}/{key}")
        raise
    return key


def load(key: str) -> list:
    """Reads a plan back and returns its object list.

    An empty plan is refused rather than treated as no work: it would copy nothing and report
    success, leaving the recipient a table pointing at an empty prefix. inspect-source already
    rejects an empty source, so an empty plan here means the object is wrong, not the source.

    Args:
      key: The plan key.

    Returns:
      The planned objects.

    Raises:
      TransientError: On a retryable S3 fault; the Map item's Retry re-runs it.
      TerminalError: ``copy_failed`` when the plan cannot be read, is not valid JSON, or
        carries no objects. By this point inspect-source has already written it, so a failure
        here means the object is missing or corrupt, which no retry fixes — and copying a
        partial set would silently give the recipient an incomplete table.
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

    objects = plan.get("objects")
    if not isinstance(objects, list) or not objects:
        raise TerminalError("copy_failed", f"copy plan {key} carries no objects")
    return objects
