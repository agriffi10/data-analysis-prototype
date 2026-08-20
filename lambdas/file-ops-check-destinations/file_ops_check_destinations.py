"""check-destinations — the per-item conflict guard, and the last state before anything is written.

Reads the plan back and decides, item by item, whether it may proceed. Read-only: it copies
nothing, deletes nothing and refuses nothing outright — a conflicted item is recorded as an outcome
and every other item carries on.

**THE REFUSAL IS PER ITEM, WHICH IS WHAT SEPARATES THIS PLANE FROM EVERY OTHER ONE.** The archive's
guard refuses the whole restore because there is one archive and one destination; here a user
selected five folders, and one of them colliding is not a reason to do nothing about the other four
— that is what the browser does today, and turning it into a whole-request refusal would make a
select-all move fail on its first conflict.

**THE COLLISION UNIT IS THE DERIVED DESTINATION KEY, NOT THE DESTINATION SUBTREE.** That is what
the browser does — it intersects the keys it would write against the destination's listing — and it
is what preserves MERGING INTO AN EXISTING FOLDER: copying ``reports/`` into ``out/`` while
``out/reports/notes.txt`` exists, when no source key maps onto it, is legal today and stays legal.
"The destination subtree holds anything" is a stricter test that would remove a shipped capability.

**IT HEADS EVERY KEY RATHER THAN LISTING THE DESTINATION**, and a listing structurally cannot serve
this check. ``CommonPrefixes`` carries no ``LastModified``, ``Size`` or keys, so a delimited listing
cannot answer the overwrite predicate below the first level; and ``ListObjectsV2`` never returns a
per-key 403 — an ``AccessDenied`` fails the whole listing. Heads are also bounded by OUR OWN object
cap rather than by the size of someone else's destination folder.

**A 403 COUNTS AS OCCUPIED, IN BOTH MODES.** A key this role cannot head is one it must not
overwrite, and under the overwrite answer it yields no ``LastModified`` at all — so "an existing
object" must never be read as "the ones we could head". A head that faults for any other reason
refuses its item; it never falls through to clear, which is the one mistake here that ends in data
loss.

The service name is the control plane, not the function, so one operation's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  _ABSENT_STATUSES: The HTTP statuses that mean the key is not there. ``403`` is deliberately not
    among them, and the reason is above. In this plane's own buckets a 403 has become unlikely
    rather than impossible — the execution role holds bucket-wide read — so the branch is a
    fail-closed guard rather than a live case, and it is kept for exactly that reason.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from cpcommon import clients, errors, observability
from focommon import notify, outcomes, plan
from focommon.config import (
    FILE_OPS_CONFLICT_SAMPLE,
    FILE_OPS_HEAD_CONCURRENCY,
    FILE_OPS_SAMPLE_PATH_CHARS,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-ops")

_ABSENT_STATUSES = (404,)


def _status(err) -> int:
    """Reads an S3 error's HTTP status, or 0 when it carries none.

    Args:
      err: The exception a ``head_object`` call raised.

    Returns:
      The HTTP status code, or 0.

    Raises:
      None.
    """
    meta = getattr(err, "response", None) or {}
    return int((meta.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0)


def _submitted_at(request: dict, loaded: dict) -> datetime | None:
    """Returns the instant the overwrite predicate is measured against.

    Taken from the PLAN rather than the state, because the plan is the object that knows which
    request its destination keys were derived for — taking it off the state instead is the very
    substitution the supersession check exists to catch.

    Args:
      request: The running request, used only when the plan carries no instant.
      loaded: The parsed plan.

    Returns:
      The parsed instant, or None when there is none to parse.

    Raises:
      None.
    """
    value = loaded.get("submittedAt") or request.get("submittedAt")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _occupied(bucket: str, key: str, submitted_at: datetime | None) -> bool:
    """Reports whether one destination key stands in this operation's way.

    Under ``refuse`` any existing object does. Under ``overwrite`` only one the user could not have
    seen does: an object whose ``LastModified`` PRECEDES the request's submission is one they were
    looking at when they confirmed, and a newer one is not.

    A folder placeholder counts like any other object under ``refuse``. Under ``overwrite`` it is
    judged by the same instant as everything else — a rule with an exception is a rule someone
    extends, and the value of this guard is that it has none.

    Args:
      bucket: The destination bucket.
      key: The destination key.
      submitted_at: The request's submission instant, or None under ``refuse``.

    Returns:
      True when the key is occupied by something this operation may not write over.

    Raises:
      TransientError: On a throttle or 5xx. A guard that cannot see the destination must retry and
        then fail its own state — never fall through to "nothing is there".
      TerminalError: Never; an unexpected deterministic fault is reported as occupied so the item
        is skipped rather than overwritten.
    """
    try:
        head = clients.s3().head_object(Bucket=bucket, Key=key)
    except Exception as err:  # noqa: BLE001 - anything but a proven 404 is treated as occupied
        errors.raise_if_transient(err, f"head {bucket}/{key}")
        if _status(err) in _ABSENT_STATUSES:
            return False
        logger.info("treating %s/%s as occupied: %s", bucket, key, err)
        return True
    if submitted_at is None:
        return True
    modified = head.get("LastModified")
    if modified is None:
        return True
    if modified.tzinfo is None:
        modified = modified.replace(tzinfo=UTC)
    return modified >= submitted_at


def _sample_path(key: str, root: str) -> str:
    """Renders one colliding key as a path the user recognises.

    Relative to the space root, never an ``s3://`` URI — the user reads the path they see in the
    file browser. Shortened FROM THE MIDDLE when it is longer than a notification can carry, so the
    basename survives: that is the part that identifies the file, and the caps admit keys no
    message could ever render whole.

    Args:
      key: The colliding destination key, absolute.
      root: The destination space root.

    Returns:
      The path to name in the refusal.

    Raises:
      None.
    """
    path = key.removeprefix(root)
    if len(path) <= FILE_OPS_SAMPLE_PATH_CHARS:
        return path
    keep = (FILE_OPS_SAMPLE_PATH_CHARS - 3) // 2
    return f"{path[:keep]}...{path[-keep:]}"


def _collisions(bucket: str, dest_keys: list, submitted_at: datetime | None) -> tuple[list, bool]:
    """Heads one item's destination keys and returns the ones that are occupied.

    **Under ``refuse`` it short-circuits on the round that fills the sample; under ``overwrite`` it
    cannot short-circuit at all**, and the difference is stated here because a shared early exit
    would silently make ``overwrite`` sample-dependent: a newer object ANYWHERE in the item's key
    set refuses the item, so every key has to be asked about.

    **The ordinary case costs a full sweep either way.** A clean item is always ``objectCount``
    heads — there is nothing to stop early on — so the timeout is sized for that rather than for a
    hoped-for average.

    Stopping at the ROUND rather than at the key keeps the pool's own work coherent: the round is
    already in flight. Order is the plan's, which is the source's listing order, so the paths a
    user is shown are the ones nearest the top of the folder they were looking at.

    Args:
      bucket: The destination bucket.
      dest_keys: This item's derived destination keys, in plan order.
      submitted_at: The submission instant under ``overwrite``, or None under ``refuse``.

    Returns:
      ``(occupied_keys, more)`` — the collisions found, and whether there may be more than the
      caller will name.

    Raises:
      TransientError: On a throttle or 5xx from any head.
    """
    def check(key: str) -> bool:
        """Heads one destination key in the bucket this call is guarding.

        Args:
          key: The destination key.

        Returns:
          True when the key is occupied.

        Raises:
          TransientError: On a throttle or 5xx.
        """
        return _occupied(bucket, key, submitted_at)

    found: list = []
    with ThreadPoolExecutor(max_workers=FILE_OPS_HEAD_CONCURRENCY) as pool:
        for start in range(0, len(dest_keys), FILE_OPS_HEAD_CONCURRENCY):
            batch = dest_keys[start : start + FILE_OPS_HEAD_CONCURRENCY]
            for key, occupied in zip(batch, pool.map(check, batch), strict=True):
                if occupied:
                    found.append(key)
            stopped = start + len(batch)
            if submitted_at is None and len(found) >= FILE_OPS_CONFLICT_SAMPLE:
                return found, stopped < len(dest_keys)
    return found, False


def _guard(loaded: dict, request: dict) -> list:
    """Decides every planned item's outcome against the destination.

    Args:
      loaded: The parsed plan, which holds the derived destination keys.
      request: The running request.

    Returns:
      One outcome record per planned item — the cleared ones unchanged, the conflicted ones
      carrying a bounded sample.

    Raises:
      TransientError: On a throttle or 5xx from any head.
    """
    destination = loaded.get("destination") or {}
    bucket = destination.get("bucket")
    root = (request.get("destination") or {}).get("root") or ""
    submitted_at = _submitted_at(request, loaded) if loaded.get("onConflict") == "overwrite" else None

    decided = []
    for item in loaded["items"]:
        dest_keys = [entry["destKey"] for entry in item["objects"] if entry.get("destKey")]
        occupied, more = _collisions(bucket, dest_keys, submitted_at)
        if not occupied:
            decided.append(outcomes.outcome(item["itemKey"], item["label"], outcomes.CLEARED))
            continue
        sample = [_sample_path(key, root) for key in occupied[:FILE_OPS_CONFLICT_SAMPLE]]
        decided.append(
            outcomes.outcome(
                item["itemKey"],
                item["label"],
                outcomes.CONFLICT,
                "destination_occupied",
                sample=sample,
                more=more or len(occupied) > len(sample),
            )
        )
    return decided


@observability.traced("check-destinations")
@notify.notifies_on_failure("check-destinations")
def handler(event, context) -> dict:
    """Step Functions entry point: decides which items may write where they were planned to.

    A thin shim; the orchestration lives below so it is testable without a Lambda context.
    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out, so
    if it were outermost the span would close as successful on an invocation that actually failed
    and notified.

    Args:
      event: The validated request, carrying the plan key and the outcome list so far.
      context: The Lambda context, unused.

    Returns:
      The request with the COMPLETE outcome list, conflicts included, and how many keys were
      checked. Every item conflicting is an ordinary result reaching the ordinary terminal — there
      is no whole-request refusal on this path.

    Raises:
      TerminalError: ``plan_unreadable`` or ``plan_superseded`` when the plan is not this run's.
      TransientError: On a retryable S3 fault.
    """
    return _check_destinations(event)


def _check_destinations(event) -> dict:
    """Loads the plan and heads every destination it names.

    Args:
      event: The validated request.

    Returns:
      The request with the carried-forward outcomes and the checked count.

    Raises:
      TerminalError: ``plan_unreadable`` or ``plan_superseded``.
      TransientError: On a retryable S3 fault.
    """
    actor = (event.get("actor") or {}).get("username")
    loaded = plan.load(event.get("planKey"), event)

    decided = _guard(loaded, event)
    conflicted = [record for record in decided if record["outcome"] == outcomes.CONFLICT]

    logger.info(
        "checked %d destination(s) for %s: %d of %d item(s) conflicted",
        loaded.get("objectCount"),
        actor,
        len(conflicted),
        len(decided),
    )
    observability.info(
        "destinations checked",
        actor=actor,
        operation=event.get("operation"),
        on_conflict=loaded.get("onConflict"),
        items=len(decided),
        objects=loaded.get("objectCount"),
        conflicted=len(conflicted),
    )
    return {
        **event,
        "checkedCount": loaded.get("objectCount"),
        "outcomes": outcomes.carry_forward(event.get("outcomes"), decided),
    }
