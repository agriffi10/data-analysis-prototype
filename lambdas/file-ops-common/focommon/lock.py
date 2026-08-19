"""The per-space file-operations lock.

Two operations in one space must not run concurrently. ``MessageGroupId`` on the request queue is
the source space, so SQS serializes *delivery* per space — but the Pipe starts the state machine
``FIRE_AND_FORGET`` and returns, so it is free to deliver the next message while the previous
execution is still running. The consequence here is worse than a raced schema: a delete removing
objects a concurrent move has already relocated is silent, unrecoverable data loss, because the
buckets have versioning off.

**The PROTOCOL is ``cpcommon.lock``'s** — the three-way acquire, the precondition mapping, the
staleness rule, the release by overwriting. What is here is what is genuinely this plane's: the key
derivation, the thresholds derived from THIS machine's ceiling, and the sentences it narrates with.

**The key is a DIGEST, and it is the same derivation the browser hashes for ``MessageGroupId``.**
An S3 key reaches 1024 characters where SQS caps a group id at 128, so the raw path is a length
failure that appears only for the users with the deepest prefixes. Computing it once here — rather
than restating the canonical string wherever it is needed — is what keeps the lock and the queue
group talking about the same space. The browser computes the same digest in TypeScript, and a test
on each side pins the same canonical string and the same expected hex.

Attributes:
  WORDING: This plane's six lock sentences. Literals here, so ``observability``'s rule that a
    message is a literal and everything variable is a field still holds at the emitting module.
"""

import hashlib
import logging

from cpcommon import clients, config
from cpcommon import lock as _lock
from cpcommon.lock import LockWording

from .config import LOCK_PREFIX, STALE_LOCK_SECONDS

logger = logging.getLogger()

WORDING = LockWording(
    acquired="space lock acquired",
    refused="space lock refused",
    stealing_stale="stealing stale space lock",
    stealing_unreadable="stealing unreadable space lock",
    released="space lock released",
    release_failed="space lock release failed",
)

__all__ = ["WORDING", "acquire", "lock_key", "release", "space_digest"]


def space_digest(bucket: str, root: str) -> str:
    """Returns the stable identifier for one space, as a SHA-256 hex digest.

    The canonical string is ``{bucket}/{root}`` with the root's trailing slash included, and the
    trailing slash is part of what is hashed rather than an incidental detail: the browser hashes
    the same string to derive the queue's ``MessageGroupId``, so a difference of one character
    means the lock and the delivery ordering are about different things and neither reports an
    error.

    Args:
      bucket: The bucket the space lives in.
      root: The space's root prefix, with or without its trailing slash.

    Returns:
      The 64-character lowercase hex digest.

    Raises:
      ValueError: If either part is empty, which would collapse every space onto one digest and
        serialize the whole plane behind a single lock.
    """
    if not bucket or not root:
        raise ValueError(f"a space digest needs a bucket and a root, got {bucket!r}/{root!r}")
    canonical = f"{bucket}/{root.rstrip('/')}/"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def lock_key(bucket: str, root: str) -> str:
    """Builds the lock object's key for one space, under the admin bucket.

    Keyed by the digest rather than the path, so the key cannot escape the prefix whatever the
    space is called: a hex digest has no slashes and no dot segments, which makes the traversal
    question this key would otherwise raise unaskable rather than merely answered.

    Args:
      bucket: The bucket the space lives in.
      root: The space's root prefix.

    Returns:
      The lock object's key.

    Raises:
      ValueError: If either part is empty.
    """
    return f"{LOCK_PREFIX}/{space_digest(bucket, root)}.json"


def acquire(bucket: str, root: str, holder: str) -> tuple[bool, str | None]:
    """Claims one space's lock, stealing it only when it is provably stale.

    **A re-claim rewrites the object and returns a NEW tag**, which matters here more than on the
    per-table lock because this plane's loser WAITS and retries rather than being refused: a waiter
    that acquires on its fourth attempt must release against the fourth tag. Releasing against an
    earlier one is a silent no-op that leaves the space locked until the staleness rule recovers it,
    which is hours.

    Args:
      bucket: The bucket the space lives in.
      root: The space's root prefix.
      holder: The claiming execution's ARN, recorded for diagnosis only. Never logged as a field.

    Returns:
      An ``(acquired, etag)`` tuple. The tag is what ``release`` must present.

    Raises:
      ValueError: If the space is not identifiable, or the holder is not a non-empty string.
      ClientError: Any write fault that is not a precondition failure.
    """
    _lock.assert_usable_holder(holder, "space lock")
    return _lock.acquire(
        bucket=config.ADMIN_BUCKET,
        key=lock_key(bucket, root),
        holder=holder,
        stale_after_seconds=STALE_LOCK_SECONDS,
        wording=WORDING,
        fields={"space_bucket": bucket, "space_root": root},
        read=_read,
    )


def release(bucket: str, root: str, etag: str | None) -> None:
    """Marks one space's lock free, under the tag the acquire returned.

    Never raises. The key is composed after the etag check and inside a guard, for the reason the
    per-table lock records: as an argument it would run before both, and this function is called on
    every terminal path including the failure path, where a raise replaces a recorded user failure
    with silence.

    Args:
      bucket: The bucket the space lives in.
      root: The space's root prefix.
      etag: The tag the most recent acquire returned. A falsy tag means there is nothing safe to
        condition on, so the release is skipped rather than written unconditionally.

    Returns:
      None.

    Raises:
      None.
    """
    if not etag:
        logger.warning("space lock for %s/%s has no etag to release against", bucket, root)
        return

    try:
        key = lock_key(bucket, root)
    except ValueError as err:
        logger.error("space lock release for %s/%s failed: %s", bucket, root, err)
        return

    _lock.release(
        bucket=config.ADMIN_BUCKET,
        key=key,
        etag=etag,
        wording=WORDING,
        fields={"space_bucket": bucket, "space_root": root},
    )


def _read(key: str) -> tuple[bytes | None, str | None]:
    """Reads the lock object's current bytes and entity tag.

    Args:
      key: The lock object's key.

    Returns:
      A ``(bytes, etag)`` tuple, both None when the object is absent or could not be read.

    Raises:
      None.
    """
    try:
        response = clients.s3().get_object(Bucket=config.ADMIN_BUCKET, Key=key)
        return response["Body"].read(), response.get("ETag")
    except Exception as err:  # noqa: BLE001
        logger.info("no readable space lock at %s (%s)", key, err)
        return None, None
