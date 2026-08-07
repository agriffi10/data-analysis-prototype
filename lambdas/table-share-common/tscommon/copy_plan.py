"""The copy plan, passed between states by pointer rather than inline.

inspect-source writes the source object list here and threads its key onward; copy-objects
loads it once per recipient. The list runs to the object cap, and the Map copies the whole
state into every item, so inline it reached 95% of the state-payload limit at the shipped
caps — and breaching that destroys every per-recipient outcome the Map exists to preserve. By
pointer the same state is about a third. The same indirection, for the same reason, as the
data-quality manifest. Measurements: ``docs/lambda-rationale.md``.

It lives in the admin bucket rather than a user's space: the SPA never browses it, so the plan
needs no hidden-folder convention, and a user cannot delete it out from under a running
execution — they do hold delete rights in their own space. Nothing deletes it here either; a
lifecycle rule expires it.

``messages`` is imported for its side effect as well as its constants: it registers this
domain's reason codes, and a terminal error validates its reason at construction. Without the
import, the failure below raises a validation error in any process that has not separately
imported it — true of a process importing only this module, and the same class of import-order
trap that once shipped three unraisable reason codes.

Attributes:
  PREFIX: Prefix inside the admin bucket, matching the lifecycle rule's filter.
  BASENAME: The plan object's basename.
"""

import hashlib
import json

from cpcommon import clients, errors
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError

from . import messages  # noqa: F401

PREFIX = "table-share"
BASENAME = "copy-plan.json"


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
    payload-shape change the bounded exposure did not justify.

    Args:
      request: The share request, carrying the actor, source and result name.

    Returns:
      The plan key under the admin bucket.

    Raises:
      None.
    """
    source = request.get("source") or {}
    digest = hashlib.sha256(
        "\x00".join(
            [
                str(request.get("actor") or ""),
                str(source.get("database") or ""),
                str(source.get("table") or ""),
                str(request.get("tableName") or ""),
            ]
        ).encode()
    ).hexdigest()
    return f"{PREFIX}/{digest}/{BASENAME}"


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
