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

**IT RUNS TWICE, AND THE SECOND PASS MAY ONLY NARROW.** The first runs after the expansion; the
second runs immediately before the transfer, because a guard separated from its copy has expired —
and pass one separates them by its own duration, which at the object cap is a full sweep of every
destination key. The second pass therefore evaluates **only items currently ``cleared``**. An item
the first pass conflicted is not re-headed and cannot be resurrected: the colliding object may have
been deleted in between, and the governing rule on this fleet is that an earlier terminal is never
overwritten.

**Which pass is running is SEEDED BY THE ASL, never inferred**, and a conflict found by the second
carries its own reason code. "The guard has not run" and "the guard ran and found nothing" are
indistinguishable inside a handler, so the pass has to arrive as data.

The service name is the control plane, not the function, so one operation's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  SECOND_PASS: The ``guardPass`` value that means "immediately before the transfer".
  _CONFLICT_REASONS: The reason code each pass records a collision under. Two codes rather than
    one because the second pass's collision is a different event — something arrived while the
    operation was being prepared, which is worth wording differently from something that was
    already there when the user pressed the button.
  _ABSENT_STATUSES: The HTTP statuses that mean the key is not there. ``403`` is deliberately not
    among them, and the reason is above. In this plane's own buckets a 403 has become unlikely
    rather than impossible — the execution role holds bucket-wide read — so the branch is a
    fail-closed guard rather than a live case, and it is kept for exactly that reason.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from cpcommon import clients, errors, observability
from cpcommon.errors import TerminalError
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

SECOND_PASS = 2

_CONFLICT_REASONS = {1: "destination_occupied", 2: "destination_occupied_late"}


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


def _submitted_at(loaded: dict) -> datetime:
    """Returns the instant the overwrite predicate is measured against.

    **Taken from the PLAN and from nowhere else, with no fallback to the state.** The plan is the
    object that knows which request its destination keys were derived for, and reading this off the
    state instead is the very substitution the supersession check exists to catch — a fallback would
    reintroduce it on exactly the runs where the two disagree.

    **An unusable instant refuses the request rather than degrading the mode.** Falling back to
    ``None`` would silently apply refuse semantics under an overwrite answer the user has already
    confirmed, and — worse — would take the short-circuit that overwrite must never take, reporting
    a partial sample as though the sweep had finished.

    Args:
      loaded: The parsed plan.

    Returns:
      The parsed instant, always time-zone aware.

    Raises:
      TerminalError: ``plan_unreadable`` when the plan names no usable submission time under an
        overwrite answer.
    """
    value = loaded.get("submittedAt")
    if not isinstance(value, str) or not value:
        raise TerminalError("plan_unreadable", "the plan names no submission time to overwrite from")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as err:
        raise TerminalError("plan_unreadable", f"{value!r} is not an instant") from err
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


def _collisions(
    bucket: str, dest_keys: list, submitted_at: datetime | None
) -> tuple[list, bool, int]:
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
      ``(occupied_keys, more, checked)`` — the collisions found, whether there may be more than the
      caller will name, and how many keys were actually headed. The last is reported rather than
      inferred from the plan, because under the short-circuit those two numbers differ by three
      orders of magnitude and the plan's is the one that is wrong.

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
    checked = 0
    with ThreadPoolExecutor(max_workers=FILE_OPS_HEAD_CONCURRENCY) as pool:
        for start in range(0, len(dest_keys), FILE_OPS_HEAD_CONCURRENCY):
            batch = dest_keys[start : start + FILE_OPS_HEAD_CONCURRENCY]
            for key, occupied in zip(batch, pool.map(check, batch), strict=True):
                if occupied:
                    found.append(key)
            checked += len(batch)
            if submitted_at is None and len(found) >= FILE_OPS_CONFLICT_SAMPLE:
                return found, checked < len(dest_keys), checked
    return found, False, checked


def _still_cleared(existing) -> set:
    """Returns the item keys that are still provisionally cleared.

    **The second pass's whole safety property is built on this set.** Anything already decided —
    a conflict from the first pass, a protected location, a no-op — is absent from it, so the
    second pass cannot re-head those keys and cannot turn an earlier terminal back into a
    ``cleared``.

    Args:
      existing: The outcome list as it arrived.

    Returns:
      The item keys whose current outcome is ``cleared``.

    Raises:
      None.
    """
    return {
        record["itemKey"]
        for record in (existing or [])
        if isinstance(record, dict) and record.get("outcome") == outcomes.CLEARED
    }


def _guard(loaded: dict, request: dict, guard_pass: int) -> tuple[list, int]:
    """Decides every eligible item's outcome against the destination.

    Args:
      loaded: The parsed plan, which holds the derived destination keys.
      request: The running request, which carries the destination root the sample is rendered
        against.
      guard_pass: Which sweep this is. On the second, only items still ``cleared`` are considered
        and a collision is recorded under the later reason code.

    Returns:
      ``(decided, checked)`` — one outcome record per item this pass judged, the cleared ones
      unchanged and the conflicted ones carrying a bounded sample, and how many keys were headed in
      total. On the second pass an item that is no longer ``cleared`` produces NO record, so
      carrying the result forward leaves its earlier outcome untouched.

    Raises:
      TerminalError: ``plan_unreadable`` when an overwrite answer has no usable instant behind it.
      TransientError: On a throttle or 5xx from any head.
    """
    destination = loaded.get("destination") or {}
    bucket = destination.get("bucket")
    root = (request.get("destination") or {}).get("root") or ""
    submitted_at = _submitted_at(loaded) if loaded.get("onConflict") == "overwrite" else None
    eligible = (
        _still_cleared(request.get("outcomes")) if guard_pass >= SECOND_PASS else None
    )
    reason = _CONFLICT_REASONS.get(guard_pass, _CONFLICT_REASONS[SECOND_PASS])

    decided, checked = [], 0
    for item in loaded["items"]:
        if eligible is not None and item["itemKey"] not in eligible:
            continue
        dest_keys = [entry["destKey"] for entry in item["objects"] if entry.get("destKey")]
        occupied, more, headed = _collisions(bucket, dest_keys, submitted_at)
        checked += headed
        if not occupied:
            decided.append(outcomes.outcome(item["itemKey"], item["label"], outcomes.CLEARED))
            continue
        sample = [_sample_path(key, root) for key in occupied[:FILE_OPS_CONFLICT_SAMPLE]]
        decided.append(
            outcomes.outcome(
                item["itemKey"],
                item["label"],
                outcomes.CONFLICT,
                reason,
                sample=sample,
                more=more or len(occupied) > len(sample),
            )
        )
    return decided, checked


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
      The request with the COMPLETE outcome list, conflicts included, and how many destination keys
      were actually headed. Every item conflicting is an ordinary result reaching the ordinary terminal — there
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
    guard_pass = event.get("guardPass") if isinstance(event.get("guardPass"), int) else 1

    decided, checked = _guard(loaded, event, guard_pass)
    conflicted = [record for record in decided if record["outcome"] == outcomes.CONFLICT]

    logger.info(
        "pass %d checked %d destination(s) for %s: %d of %d item(s) conflicted",
        guard_pass,
        checked,
        actor,
        len(conflicted),
        len(decided),
    )
    observability.info(
        "destinations checked",
        actor=actor,
        operation=event.get("operation"),
        guard_pass=guard_pass,
        on_conflict=loaded.get("onConflict"),
        items=len(decided),
        objects=loaded.get("objectCount"),
        checked=checked,
        conflicted=len(conflicted),
    )
    return {
        **event,
        "checkedCount": checked,
        "outcomes": outcomes.carry_forward(event.get("outcomes"), decided),
    }
