"""The copy plan, passed between states by POINTER rather than inline.

``inspect-source`` writes the source object list here and threads its KEY onward;
``copy-objects`` loads it once per recipient.

WHY IT IS NOT ON THE STATE, measured rather than assumed: the list runs to
``SHARE_MAX_OBJECTS`` (1000) entries, and the Map's ``ItemSelector`` copies the WHOLE state
into every item, then ``ResultPath`` merges the per-recipient results back into it. At the
shipped caps with ordinary Hive keys (``year=/month=/day=/hour=/part-…parquet``, ~140
chars) that reached **249 KB — 95%** of Step Functions' 256 KB state-payload limit, and
**71% with zero failures**. Breaching it raises ``States.DataLimitExceeded`` ON THE MAP,
which routes to the whole-request ``RecordFailure`` and destroys every per-recipient
outcome the Map exists to preserve — turning a partial success into a total failure, on
exactly the requests that already went worst. By pointer the same state is ~34%.

This is the same indirection, for the same reason, as SPEC-110's data-quality manifest.

WHERE IT LIVES, and why not in a user's space: the admin bucket. The SPA never browses it,
so the plan needs no hidden-folder convention (note ``athenaresults/`` is NOT hidden — only
locked as a copy destination — so it would have shown control-plane JSON to users), and a
user cannot delete it out from under a running execution; they DO hold ``s3:DeleteObject``
in their own space. Nothing deletes it here either: the ``expire-table-share-copy-plans``
lifecycle rule in ``analytics/s3.tf`` expires it.
"""

import hashlib
import json

from cpcommon import clients, errors
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError

# Imported for its SIDE EFFECT as well as its constants: tscommon.messages registers this
# domain's reason codes with cpcommon at import, and TerminalError validates its reason
# against that registry AT CONSTRUCTION. Without this import, `copy_failed` below raises
# ValueError in any process that has not separately imported tscommon.messages — which
# happens to be true of the deployed verbs (they import notify, which imports messages) and
# NOT true of a process that imports only this module. The same class of import-order trap
# that shipped three unraisable reason codes in SPEC-110.
from . import messages  # noqa: F401

#: Prefix inside the admin bucket. Matches the lifecycle rule's filter.
PREFIX = "table-share"
BASENAME = "copy-plan.json"


def plan_key(request: dict) -> str:
    """``table-share/{hash}/copy-plan.json`` — a pure function of the request.

    Table-share has no ``requestId`` (unlike the data-quality arc), so the key is a digest
    of the fields that identify the share. That makes it replay-safe the same way: a Step
    Functions ``Retry`` of inspect-source rewrites the SAME key with the same content rather
    than leaving a second plan behind.

    TWO EXECUTIONS *CAN* OVERLAP ON ONE KEY, and an earlier version of this docstring
    claimed otherwise — wrongly. The FIFO ``MessageGroupId`` is ``{database}.{table}``, but
    the Pipe is ``invocation_type = "FIRE_AND_FORGET"`` (pipe.tf), so SQS considers the
    message handled as soon as ``StartExecution`` RETURNS, not when the execution finishes.
    A group serializes starts, not runs. Redelivery after a Pipes crash and a DLQ redrive
    open the same window.

    WHY IT IS STILL SAFE, stated as the bounded claim it actually is: a collision needs the
    same actor, source database, source table AND result name. Those requests list the SAME
    prefix, so both plans describe the same object set and either is correct for either
    execution. The residual exposure is a source MUTATED between the two listings — the
    earlier execution would then copy the later snapshot. Nothing here silently mixes two
    different sources, because the digest covers the database and table (pinned by test).

    Making it airtight would take an execution-unique salt (``$$.Execution.Name`` threaded
    in), which costs an ASL payload-shape change; the bounded exposure above did not justify
    it. Recorded so the next person weighs it rather than re-deriving it.
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
    """Write the plan and return its key.

    Raises:
        TransientError: on a retryable S3 fault, so the caller's Step Function ``Retry``
            re-runs inspect-source — which is safe, because the key is a pure function of
            the request and the verb is read-only besides this write.
    """
    key = plan_key(request)
    body = json.dumps({"objects": objects}, separators=(",", ":")).encode()
    try:
        clients.s3().put_object(
            Bucket=cpconfig.ADMIN_BUCKET, Key=key, Body=body, ContentType="application/json"
        )
    except Exception as err:  # retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, f"put {cpconfig.ADMIN_BUCKET}/{key}")
        raise
    return key


def load(key: str) -> list:
    """Return the plan's object list.

    Raises:
        TransientError: on a retryable S3 fault (the Map item's ``Retry`` re-runs it).
        TerminalError: ``copy_failed`` when the plan cannot be read or parsed. By this point
            inspect-source has already written it, so a failure here means the object is
            missing or corrupt — which no retry fixes, and copying a PARTIAL set of objects
            would silently give the recipient an incomplete table.
    """
    try:
        body = clients.s3().get_object(Bucket=cpconfig.ADMIN_BUCKET, Key=key)["Body"].read()
    except Exception as err:  # retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, f"get {cpconfig.ADMIN_BUCKET}/{key}")
        raise TerminalError("copy_failed", f"could not read copy plan {key}: {err}") from err

    try:
        plan = json.loads(body)
    except ValueError as err:
        raise TerminalError("copy_failed", f"copy plan {key} is not valid JSON: {err}") from err

    objects = plan.get("objects")
    if not isinstance(objects, list) or not objects:
        # An empty plan would copy nothing and report success — the recipient would get a
        # table pointing at an empty prefix. inspect-source rejects an empty source
        # (source_empty), so an empty plan here means the object is wrong, not the source.
        raise TerminalError("copy_failed", f"copy plan {key} carries no objects")
    return objects
