"""Glacier retrieval: asking for the bytes back, and knowing when they are there.

SPEC-171, and the two things in this arc that no other control plane in this repo has. An
object in ``GLACIER`` is **not readable** — a ``CopyObject`` whose source is in that class fails
``InvalidObjectState`` — so a restore is not a copy. It is ``RestoreObject``, a 3-5 hour wait,
and *then* a copy of the temporary readable object S3 materialises beside it.

**Retrieval is billed and cannot be cancelled.** Everything SPEC-170 does happens before this
module is reached, and the ordering is the reason that spec exists separately: once
``request_retrieval`` has run, the user has paid for a retrieval whether or not the rest of the
run succeeds. Nothing here is speculative and nothing here is retried for free.

**Completion is established by the ``Restore`` header and by nothing else.** Neither the storage
class nor the object's presence changes when a retrieval completes — the archived object stays
``GLACIER`` forever, and what appears beside it is a temporary copy the header describes. Three
answers, and the third is the one worth writing a module for:

  ``ongoing-request="false"``   the temporary copy is there; the object can be copied.
  ``ongoing-request="true"``    S3 is still working on it.
  *no header at all*            **nothing ever asked for this object.** On an object still in a
                                Glacier class that is a FAILURE, not a "not yet" — treating it
                                as pending burns every poll iteration and then reports a timeout
                                for something that was never going to complete.

**S3 Event Notifications (``s3:ObjectRestore:Completed``) are rejected as the completion
signal**, and the reason is not that polling is nicer. They would need bucket notification
configuration covering every archive prefix, a correlation store keyed by object so an arriving
event could be attributed to the run that asked for it, and a second delivery path with its own
at-least-once semantics and its own failure modes — to replace a poll inside a machine that is
already sitting still for hours, and that the plane already knows how to write. The poll costs
one Lambda invocation every ``RESTORE_POLL_SECONDS``.

Attributes:
  COMPLETE: The object's temporary readable copy exists.
  PENDING: Retrieval was asked for and has not finished.
  NEVER_REQUESTED: No retrieval was ever asked for, on an object that needs one.
  _TOLERATED_CODES: The two ``RestoreObject`` responses that are the DESIRED state wearing an
    error's clothes. ``RestoreAlreadyInProgress`` (HTTP 409) means somebody — almost always this
    same run, redriven — has already asked, which is exactly what this call wanted to be true.
    ``InvalidObjectState`` means the object does not need a retrieval at all, which keeps the
    restore path unconditional on ``ARCHIVE_STORAGE_CLASS``: a class that needs no restore still
    tolerates one being requested, rather than the machinery being branched away behind a
    constant.
  _ONGOING: The ``Restore`` header directive that carries the answer.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from cpcommon import clients, errors
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError

from . import messages  # noqa: F401
from .config import (
    GLACIER_CLASSES,
    RESTORE_AVAILABILITY_DAYS,
    RESTORE_HEAD_CONCURRENCY,
    RESTORE_MAX_POLLS,
    RESTORE_POLL_PAGE,
    RESTORE_TIER,
)

logger = logging.getLogger(__name__)

COMPLETE = "complete"
PENDING = "pending"
NEVER_REQUESTED = "never_requested"

_TOLERATED_CODES = ("RestoreAlreadyInProgress", "InvalidObjectState")

_ONGOING = "ongoing-request"


def _error_code(err) -> str:
    """Reads an S3 error's code, or an empty string when it carries none.

    Args:
      err: The exception a boto3 call raised.

    Returns:
      The ``Error.Code`` string, or ``""``.

    Raises:
      None.
    """
    response = getattr(err, "response", None) or {}
    return str((response.get("Error") or {}).get("Code") or "")


def _restore_one(bucket: str, key: str) -> None:
    """Asks S3 to retrieve one archived object, tolerating the two answers that mean success.

    Args:
      bucket: The archive bucket.
      key: The archived object's key.

    Returns:
      None.

    Raises:
      TransientError: On a throttle or 5xx, so the batch retries.
      Exception: The raw fault on a deterministic one. A genuine failure on any object fails the
        whole run — nothing has been copied and the archive is untouched, so the user re-submits,
        and the tolerated codes above are what make that re-submission cost nothing.
    """
    try:
        clients.s3().restore_object(
            Bucket=bucket,
            Key=key,
            RestoreRequest={
                "Days": RESTORE_AVAILABILITY_DAYS,
                "GlacierJobParameters": {"Tier": RESTORE_TIER},
            },
        )
    except Exception as err:
        if _error_code(err) in _TOLERATED_CODES:
            logger.info("retrieval of %s/%s needs nothing further (%s)", bucket, key, err)
            return
        errors.raise_if_transient(err, f"restore {bucket}/{key}")
        raise


def request_retrieval(locations: list) -> int:
    """Issues ``RestoreObject`` across a batch of archived objects on a bounded worker pool.

    The pool is ``RESTORE_HEAD_CONCURRENCY`` for the reason that constant records: boto3's S3
    client takes botocore's default connection pool of 10, so threads past that contend rather
    than each getting a connection.

    Every object is attempted before anything is raised, so one bad object does not strand the
    rest of its batch un-requested — the failure fails the run either way, and a half-requested
    batch would make a re-submission cost more retrievals than it had to.

    Args:
      locations: ``(bucket, key)`` per object. The bucket rides per object rather than once for
        the batch because the caller is a Map child that holds manifest items and no request:
        taking the bucket off the first item and applying it to the rest would be an assumption
        nothing on that state can check.

    Returns:
      How many retrievals were requested.

    Raises:
      TransientError: When any object failed retryably, after every one has been attempted.
      Exception: The first deterministic fault, after every object has been attempted.
    """
    failure = None
    transient = None
    with ThreadPoolExecutor(max_workers=RESTORE_HEAD_CONCURRENCY) as pool:
        futures = [
            (f"{bucket}/{key}", pool.submit(_restore_one, bucket, key))
            for bucket, key in locations
        ]
        for key, future in futures:
            try:
                future.result()
            except errors.TransientError as exc:
                transient = transient or exc
            except Exception as exc:  # noqa: BLE001 - re-raised below, after every key is tried
                logger.warning("retrieval of %s failed: %s", key, exc)
                failure = failure or exc
    if transient is not None:
        raise transient
    if failure is not None:
        raise failure
    return len(locations)


def classify(head: dict) -> str:
    """Decides what a ``HeadObject`` response says about one object's retrieval.

    Args:
      head: The ``HeadObject`` response.

    Returns:
      ``COMPLETE``, ``PENDING`` or ``NEVER_REQUESTED``.

    Raises:
      None.
    """
    header = head.get("Restore")
    if header:
        for directive in str(header).split(","):
            name, _, value = directive.partition("=")
            if name.strip() == _ONGOING:
                return PENDING if value.strip().strip('"').lower() == "true" else COMPLETE
        return COMPLETE
    if (head.get("StorageClass") or "STANDARD") in GLACIER_CLASSES:
        return NEVER_REQUESTED
    return COMPLETE


def _state_of(bucket: str, key: str) -> str:
    """Heads one archived object and classifies its retrieval.

    Args:
      bucket: The archive bucket.
      key: The archived object's key.

    Returns:
      ``COMPLETE``, ``PENDING`` or ``NEVER_REQUESTED``.

    Raises:
      TransientError: On a throttle or 5xx, so the poll verb's own Retry re-runs it.
      TerminalError: ``restore_never_requested`` when the object is gone. An archived object that
        cannot be headed at all is not a slow retrieval, and every remaining poll spent on it
        would end in a ``restore_timed_out`` that named the wrong cause.
    """
    try:
        return classify(clients.s3().head_object(Bucket=bucket, Key=key))
    except Exception as err:
        errors.raise_if_transient(err, f"head {bucket}/{key}")
        raise TerminalError(
            "restore_never_requested", f"{bucket}/{key} could not be read back: {err}"
        ) from err


def advance(bucket: str, keys: list, start: int) -> tuple[int, bool]:
    """Sweeps forward from the index the last poll reached, a page at a time.

    **Two bounds, and they answer different questions.** ``RESTORE_POLL_PAGE`` is the
    granularity progress is RECORDED at — a page whose every object reports complete moves the
    recorded index on, and a page holding one pending object does not, so the next iteration
    re-heads that page and nothing before it. The invocation's own bound is the plan's length,
    because it keeps sweeping while pages come back complete: every object was requested at once
    at one tier, so they finish together, and stopping after one page would add a five-minute
    ``Wait`` per thousand objects to a retrieval that had already completed.

    Args:
      bucket: The archive bucket.
      keys: Every archived key, in plan order.
      start: The index the last iteration reached — everything below it is already complete.

    Returns:
      ``(index, done)`` — how far this iteration got, and whether every object is complete.

    Raises:
      TerminalError: ``restore_never_requested`` when an object carries no ``Restore`` header and
        is still in a Glacier class, or cannot be headed at all.
      TransientError: On a throttle or 5xx from any head.
    """
    index = max(0, min(start, len(keys)))
    with ThreadPoolExecutor(max_workers=RESTORE_HEAD_CONCURRENCY) as pool:
        while index < len(keys):
            page = keys[index : index + RESTORE_POLL_PAGE]
            states = list(pool.map(lambda key: _state_of(bucket, key), page))
            if NEVER_REQUESTED in states:
                position = index + states.index(NEVER_REQUESTED)
                raise TerminalError(
                    "restore_never_requested",
                    f"object {position} of {len(keys)} in {bucket} was never asked for",
                )
            if PENDING in states:
                return index, False
            index += len(page)
    return index, True


def read_progress(key: str, object_count: int) -> dict:
    """Reads the poll's progress record back, treating every unusable shape as no progress.

    **Absent is the ordinary case** — the first iteration writes it — and unreadable is treated
    the same way for a reason worth stating: the record is an OPTIMISATION, not a fact. Losing it
    costs one iteration a full re-head, where refusing on it would fail a run in its fourth hour
    over a JSON parse. A recorded index that does not fit the plan it claims to describe is
    likewise discarded rather than trusted, since resuming past the end would report a restore
    complete that had never been looked at.

    Args:
      key: The progress record's key in the admin bucket.
      object_count: How many objects the plan holds, which the record must agree with.

    Returns:
      ``{"pollCount": n, "completedThrough": i}``, zeroed when there is no usable record.

    Raises:
      TransientError: On a retryable S3 fault. A throttled read is retried rather than read as
        "no progress", because that is the one way this tolerance could cost a re-head of the
        whole archive.
    """
    empty = {"pollCount": 0, "completedThrough": 0}
    try:
        body = clients.s3().get_object(Bucket=cpconfig.ADMIN_BUCKET, Key=key)["Body"].read()
    except Exception as err:  # noqa: BLE001 - an unreadable record is no progress, never a failure
        errors.raise_if_transient(err, f"get {cpconfig.ADMIN_BUCKET}/{key}")
        logger.info("no readable restore progress at %s (%s)", key, err)
        return empty
    try:
        loaded = json.loads(body)
    except ValueError as err:
        logger.info("restore progress at %s is not readable JSON (%s)", key, err)
        return empty
    if not isinstance(loaded, dict) or loaded.get("objectCount") != object_count:
        logger.info("restore progress at %s does not describe this plan", key)
        return empty
    polls, through = loaded.get("pollCount"), loaded.get("completedThrough")
    if not isinstance(polls, int) or isinstance(polls, bool) or polls < 0:
        return empty
    if not isinstance(through, int) or isinstance(through, bool) or not 0 <= through <= object_count:
        return empty
    return {"pollCount": polls, "completedThrough": through}


def write_progress(key: str, request_id, poll_count: int, through: int, object_count: int) -> None:
    """Records how far the poll has got, so the next iteration does not start again.

    Args:
      key: The progress record's key in the admin bucket.
      request_id: The restore run's id, recorded for diagnosis.
      poll_count: How many iterations have run.
      through: The index every object below which is complete.
      object_count: How many objects the plan holds.

    Returns:
      None.

    Raises:
      TransientError: On a retryable S3 fault, so the poll verb's Retry re-runs it — safe,
        because the key is a pure function of the request id and the write is a whole-object PUT.
      ClientError: Any deterministic fault propagates.
    """
    body = json.dumps(
        {
            "requestId": request_id,
            "pollCount": poll_count,
            "completedThrough": through,
            "objectCount": object_count,
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


def exhausted(poll_count: int) -> bool:
    """Reports whether the loop has spent its whole retrieval budget.

    The cap lives in Python rather than in the ASL ``Choice`` so there is one home for it: a
    literal in the rendered machine and a constant in ``config`` would be two numbers that could
    disagree, and the disagreement would only show on a restore that was already going badly.

    Args:
      poll_count: How many iterations have run, this one included.

    Returns:
      True when no iteration remains.

    Raises:
      None.
    """
    return poll_count >= RESTORE_MAX_POLLS
