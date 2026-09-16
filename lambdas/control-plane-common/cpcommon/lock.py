"""The compare-and-set lock protocol, shared by every plane that serializes its own executions.

**This is an ALGORITHM, so it lives here.** ``MessageGroupId`` orders delivery per group, but the
Pipe starts the state machine ``FIRE_AND_FORGET`` and returns, so two executions against one target
can overlap. A conditional-write lock is the serialization the queue cannot provide, and it arrived
on ``tbcommon.table_lock`` for the per-table refresh. It moves here **ahead of** its second
consumer — the specced file-ops per-space lock, which is not built yet — because a second full copy
of it would be a second place a concurrency bug can be introduced, in the one module whose whole
purpose is preventing one. Extracting before the second caller rather than after is deliberate:
building the caller first means importing a leaf domain's module, which is the undeclared shared
layer this repo has already had to unpick once.

What each domain keeps is what is genuinely its own: its key layout, its own thresholds, and the
sentences it narrates with. What is here is the protocol: the three-way acquire branch, the
precondition mapping, the staleness rule and the release.

**The READER IS INJECTED, and that is not a style choice.** A caller's test pins the read so that
two acquires see the same stale tag and the compare-and-set — rather than the age check — decides
which one wins. That is the only way to exercise the concurrent case, so the seam has to live in
the module the test can reach. The callable is invoked as ``read(key)``, with the bucket closed over
by the caller, and the caller resolves it as a module global at call time so a patch takes effect.

The conditional-write protocol is ``cas``'s, but the loop deliberately is not: ``cas_mutate``
**retries** on a precondition failure, which is right for an append and wrong for a lock. Here a
lost precondition means someone else holds it, and the correct answer is to stop. Only
``cas.is_precondition`` is shared — the one place that knows a failed match and a racing create are
the same answer.

Attributes:
  DEFAULT_VERSION: Body schema version written when a caller states none. Recorded so a later
    reader can tell which shape wrote an object; nothing reads it back, because a version-aware
    branch would need a second shape to branch on and inventing one now would be a guess about a
    migration nobody has designed.
  RESERVED_FIELDS: Event field names this protocol supplies itself. A binding whose own fields
    collide with one would raise ``TypeError`` at the emit — and only on the branch that uses that
    name, so a steal-only or refusal-only crash on the rarest path. Checked up front instead.
  Reader: Reads a lock object, called as ``read(key)`` and returning ``(bytes, etag)`` with both
    None when it is absent or unreadable. A parameter rather than a call into S3 here, because
    pinning the read is the only way a caller's test can reach the concurrent case: two acquires
    seeing one stale tag, decided by the compare-and-set rather than the age check.
"""

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from . import cas, clients, observability

logger = logging.getLogger()

DEFAULT_VERSION = 1

RESERVED_FIELDS = frozenset({"stolen", "held_since", "age_seconds"})

Reader = Callable[[str], tuple[bytes | None, str | None]]

__all__ = [
    "DEFAULT_VERSION",
    "RESERVED_FIELDS",
    "LockWording",
    "Reader",
    "acquire",
    "assert_fields_are_free",
    "assert_usable_holder",
    "release",
]


@dataclass(frozen=True)
class LockWording:
    """The six sentences one domain's lock narrates with.

    A domain holds its own table of these rather than passing a single label, because the six are
    emitted from seven call sites with different fields and a caller's tests assert them by
    message. Keeping them as literals in the domain's own frozen table is what preserves
    ``observability``'s rule that a message is a literal and everything variable is a field: the
    variable part here is which plane is speaking, not what it says.

    Attributes:
      acquired: The lock was claimed. Carries a ``stolen`` field.
      refused: The lock is held by someone else. Carries a ``held_since`` field, which is None
        when a compare-and-set lost rather than a live holder being read.
      stealing_stale: A held lock older than the threshold is being taken. Carries ``age_seconds``.
      stealing_unreadable: A lock whose body could not be parsed is being taken. Carries
        ``age_seconds`` of None.
      released: The lock was marked free.
      release_failed: The release could not be written. Emitted at error level; the request
        proceeds regardless.
    """

    acquired: str
    refused: str
    stealing_stale: str
    stealing_unreadable: str
    released: str
    release_failed: str


def assert_usable_holder(holder: object, label: str = "lock") -> None:
    """Fails unless the holder is an identity a later reader will not mistake for "free".

    A null or empty holder is what FREE means in this body, so a claim carrying one would write a
    lock that every later reader — including the next call into this module — correctly reads as
    unheld. Two executions would then hold the lock at once, which is the single state this module
    exists to prevent. An absent ASL path resolves to exactly this, so the guard is on a reachable
    case rather than a theoretical one.

    Exposed separately from ``acquire`` so a caller can run it before composing its own key, which
    is what keeps a bad holder and a bad key raising in the caller's established order.

    Args:
      holder: The claiming execution's identity, from the caller.
      label: Names the lock in the message, so a fleet with more than one kind of lock does not
        report them all identically. The message reaches CloudWatch and the decoded Step Functions
        ``Cause``, where "which lock" is the first thing a reader needs.

    Returns:
      None.

    Raises:
      ValueError: If the holder is not a non-empty string.
    """
    if not isinstance(holder, str) or not holder:
        raise ValueError(f"{label} holder is not a usable identity: {holder!r}")


def assert_fields_are_free(fields: Mapping[str, object]) -> None:
    """Fails unless a binding's own event fields leave the protocol's reserved names alone.

    The emit sites expand ``**fields`` alongside a branch-specific keyword, so a binding that named
    one of those itself would raise ``TypeError`` — on that branch only, which means a crash on the
    steal or the refusal and nowhere else. Failing here instead turns the rarest possible runtime
    fault into one every call makes immediately.

    Args:
      fields: The binding's identifying fields.

    Returns:
      None.

    Raises:
      ValueError: If any reserved name is present.
    """
    clashes = sorted(RESERVED_FIELDS & set(fields))
    if clashes:
        raise ValueError(f"lock fields may not use the protocol's own names: {', '.join(clashes)}")


def acquire(
    *,
    bucket: str,
    key: str,
    holder: str,
    stale_after_seconds: float,
    wording: LockWording,
    fields: Mapping[str, object],
    read: Reader,
    version: int = DEFAULT_VERSION,
) -> tuple[bool, str | None]:
    """Claims the lock, stealing it only when it is provably stale.

    Conditional ``PutObject`` only — ``IfNoneMatch`` when the object does not exist yet, ``IfMatch``
    when it exists and is free, stale or unreadable. A lost precondition is not retried: it means
    another execution claimed it between this read and this write, which is the answer rather than
    a transient fault.

    A read failure is treated as absent, which makes the following write create-only and therefore
    a *refusal* when the object does in fact exist. That is the safe direction, because the
    alternative is overwriting a live holder's lock on a transient S3 error.

    **A lock this holder already owns is re-claimed, not refused.** A state machine retries the
    acquire task on a Lambda service fault, and a put whose response was lost has already written
    the lock — so a re-invocation that refused would fail a request whose own earlier attempt
    succeeded. That branch is why the holder must identify the EXECUTION and not the request: a
    request id is whatever the caller sent, so a second execution can carry the same id while the
    first is still going. Reusing an execution name was measured to return the original run or fail
    rather than start a second, but that the Pipe reuses the name for a redelivered message is
    inferred rather than proven, so nothing here relies on redelivery being harmless.

    **The re-claim rewrites the object**, so it returns a NEW tag and stamps a new claim time. A
    caller that acquires more than once must release against the most recent tag; an earlier one is
    dead, and releasing against it is a silent no-op that leaves the lock held until it goes stale.

    Args:
      bucket: The bucket the lock object lives in, read at call time by the caller.
      key: The lock object's key, composed by the caller.
      holder: The claiming execution's ARN, recorded for diagnosis only. Never logged as a field.
      stale_after_seconds: Age past which a held lock is taken. A caller derives this from its own
        machine's ceiling; a threshold below that ceiling steals a RUNNING execution's lock.
      wording: The domain's six sentences.
      fields: The domain's identifying fields, merged into every event.
      read: Reads the lock object, called as ``read(key)``.
      version: Body schema version to write.

    Returns:
      An ``(acquired, etag)`` tuple. The tag is what ``release`` must present; it is None whenever
      the lock was not acquired, and may be None on success if S3 returned no tag.

    Raises:
      ValueError: If the holder is not a non-empty string, or the fields use a reserved name.
      ClientError: Any write fault that is not a precondition failure.
    """
    assert_usable_holder(holder)
    assert_fields_are_free(fields)

    raw, etag = read(key)

    if raw is None:
        return _claim(bucket, key, holder, etag=None, stolen=False, wording=wording, fields=fields, version=version)

    state = _parse(raw)
    if state is None:
        observability.warning(wording.stealing_unreadable, **fields, age_seconds=None)
        return _claim(bucket, key, holder, etag=etag, stolen=True, wording=wording, fields=fields, version=version)

    if state.get("holder") is None:
        return _claim(bucket, key, holder, etag=etag, stolen=False, wording=wording, fields=fields, version=version)

    if state.get("holder") == holder:
        logger.info("lock at %s is already ours — reclaiming", key)
        return _claim(bucket, key, holder, etag=etag, stolen=False, wording=wording, fields=fields, version=version)

    age = _age_seconds(state.get("acquiredAt"))
    if age is None or not 0 <= age <= stale_after_seconds:
        observability.warning(wording.stealing_stale, **fields, age_seconds=age)
        return _claim(bucket, key, holder, etag=etag, stolen=True, wording=wording, fields=fields, version=version)

    observability.info(wording.refused, **fields, held_since=state.get("acquiredAt"))
    return False, None


def release(
    *,
    bucket: str,
    key: str,
    etag: str | None,
    wording: LockWording,
    fields: Mapping[str, object],
    version: int = DEFAULT_VERSION,
) -> None:
    """Marks the lock free, under the tag the acquire returned.

    Never raises and never retries a lost compare-and-swap. Losing it means the lock was stolen by
    a later execution, and re-writing would clobber the new holder — reintroducing the concurrency
    the lock exists to prevent, from its own cleanup. A request that did its work and then reported
    failure because of its own bookkeeping would be a worse outcome than a lock the staleness rule
    recovers anyway.

    Releases by OVERWRITING, never by deleting, so that a release is idempotent and a stolen lock
    stays detectable by compare-and-set. "Free" is a STATE of the object, not its absence.

    Args:
      bucket: The bucket the lock object lives in.
      key: The lock object's key.
      etag: The tag ``acquire`` returned, and the most recent one when it was called more than
        once. A falsy tag means there is nothing safe to condition on, so the release is skipped
        rather than written unconditionally.
      wording: The domain's six sentences.
      fields: The domain's identifying fields, merged into every event.
      version: Body schema version to write.

    Returns:
      None.

    Raises:
      ValueError: If the fields use a reserved name — a binding error, not a request failure, and
        the one thing this function does raise on.
    """
    assert_fields_are_free(fields)

    if not etag:
        logger.warning("lock at %s has no etag to release against", key)
        return

    try:
        _put(bucket, key, _body(holder=None, acquired_at=None, version=version), etag)
    except Exception as err:  # noqa: BLE001
        logger.error("lock release for %s failed: %s", key, err)
        observability.error(wording.release_failed, **fields)
        return

    observability.info(wording.released, **fields)


def _parse(raw: bytes) -> dict | None:
    """Decodes a lock body, reporting an unusable one as unreadable rather than raising.

    A body nobody can read is not evidence that an operation is running, so the caller treats None
    as stale. The alternative — treating it as held — leaves a target that can never be operated on
    again, which is a worse failure than the race.

    Args:
      raw: The lock object's bytes.

    Returns:
      The decoded object, or None if it is not a JSON object.

    Raises:
      None.
    """
    try:
        state = json.loads(raw)
    except Exception as err:  # noqa: BLE001
        logger.warning("lock body is not JSON (%s)", err)
        return None
    return state if isinstance(state, dict) else None


def _age_seconds(acquired_at: object) -> float | None:
    """Reports how long ago a lock was claimed.

    A NEGATIVE age is possible and is not filtered here — a future-dated claim time, from clock
    skew or a corrupt write, would otherwise be younger than every threshold forever and cost the
    target its operation permanently, with no operator recovery path. The caller treats it as
    stealable for the same reason it treats an unreadable body that way: a timestamp that cannot be
    true is no evidence that anything is running.

    Args:
      acquired_at: The recorded ISO-8601 claim time, or anything else.

    Returns:
      The age in seconds, negative when the claim time is in the future, or None if the value is
      missing or unparseable.

    Raises:
      None.
    """
    if not isinstance(acquired_at, str):
        return None
    try:
        claimed = datetime.fromisoformat(acquired_at)
    except ValueError:
        return None
    if claimed.tzinfo is None:
        claimed = claimed.replace(tzinfo=UTC)
    return (datetime.now(UTC) - claimed).total_seconds()


def _claim(
    bucket: str,
    key: str,
    holder: str,
    *,
    etag: str | None,
    stolen: bool,
    wording: LockWording,
    fields: Mapping[str, object],
    version: int,
) -> tuple[bool, str | None]:
    """Writes the claim conditionally, reporting a lost precondition as a refusal.

    Args:
      bucket: The bucket the lock object lives in.
      key: The lock object's key.
      holder: The claiming execution's ARN.
      etag: The tag to match, or None to write only if the object is absent.
      stolen: Whether this claim took the lock from a stale or unreadable holder.
      wording: The domain's six sentences.
      fields: The domain's identifying fields.
      version: Body schema version to write.

    Returns:
      An ``(acquired, etag)`` tuple.

    Raises:
      ClientError: Any write fault that is not a precondition failure.
    """
    body = _body(
        holder=holder,
        acquired_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        version=version,
    )
    try:
        response = _put(bucket, key, body, etag)
    except Exception as exc:
        if cas.is_precondition(exc):
            observability.info(wording.refused, **fields, held_since=None)
            return False, None
        raise
    observability.info(wording.acquired, **fields, stolen=stolen)
    return True, response.get("ETag")


def _put(bucket: str, key: str, body: bytes, etag: str | None) -> dict:
    """Writes the lock object conditionally on the tag it was read at.

    Args:
      bucket: The bucket the lock object lives in.
      key: The lock object's key.
      body: The full object body.
      etag: The tag to match, or None to write only if the object is absent.

    Returns:
      The ``PutObject`` response, whose ETag is what a later release conditions on.

    Raises:
      ClientError: On a precondition failure, or any other S3 fault.
    """
    kwargs: dict[str, object] = {
        "Bucket": bucket,
        "Key": key,
        "Body": body,
        "ContentType": "application/json",
    }
    if etag is None:
        kwargs["IfNoneMatch"] = "*"
    else:
        kwargs["IfMatch"] = etag
    return cast("dict", clients.s3().put_object(**kwargs))


def _body(*, holder: str | None, acquired_at: str | None, version: int) -> bytes:
    """Renders a lock body.

    The three keys are the whole shape, and a caller's test asserts exactly that set — a fourth
    would change what every existing lock object means.

    Args:
      holder: The holding execution's ARN, or None for a free lock.
      acquired_at: The ISO-8601 claim time, or None for a free lock.
      version: Body schema version to write.

    Returns:
      The encoded JSON body.

    Raises:
      None.
    """
    return json.dumps({"version": version, "holder": holder, "acquiredAt": acquired_at}).encode("utf-8")
