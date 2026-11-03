"""The per-table refresh lock.

Two refreshes of one table can overlap. ``MessageGroupId`` on the request queue is the target
database, so SQS serializes *delivery* per database, but the Pipe starts the state machine
``FIRE_AND_FORGET`` and returns immediately — so it is free to deliver the next message while the
previous execution is still running. The in-place ``glue:UpdateTable`` reduced the damage
(neither run can see a missing table) but could not close it, because Glue offers no
compare-and-set on ``UpdateTable``. This module is the serialization the catalog cannot provide:
the second refresh is refused rather than raced.

**The PROTOCOL now lives in ``cpcommon.lock``**, which is where an algorithm belongs once a second
plane is going to need it — the specced file-ops per-space lock, extracted ahead of that caller
rather than after it. What stays here is
what is genuinely table-builder's: the key layout, the thresholds derived from THIS machine's
ceiling, and the sentences this plane narrates with. The behaviour is unchanged, and this module's
own suites are the proof: the protocol moved without them being rewritten.

**The lock is released by OVERWRITING, never by deleting, and that is forced rather than chosen.**
The table-builder execution role carries an explicit ``Deny`` on ``s3:DeleteObject`` for the whole
admin bucket (``NoDataObjectDelete``), deliberately kept when the plane removed
``glue:DeleteTable``. Releasing by deletion would mean amending that Deny — trading a standing
safety property for an implementation convenience. So "free" is a *state* of the object, not its
absence, and a test in ``cpcommon`` greps the protocol to keep it that way.

Attributes:
  LOCK_PREFIX: Key prefix for every lock object, under the admin bucket.
  MACHINE_TIMEOUT_SECONDS: The table-builder state machine's ``TimeoutSeconds``, mirrored here
    because a steal threshold is only meaningful against a bounded execution — a Standard machine
    with no timeout may run for a year, and no age threshold could be justified against it.
    Derived from the refresh path's worst case: every Task retries 3 times
    over 2/4/8-second intervals, so a state costs ``4 * timeout + 14`` seconds, and the path sums
    to ≈2400 s (validate 74, acquire 74, load-definition 74, inspect-source 254, infer-schema 494,
    diff-schema 74, apply-refresh 1214, release 74, notify 74). Each state also waits up to 75 s
    for its function to wake from Inactive, ≈3080 s in all. The create path is ≈2780 s with its
    wakes, so 3600 clears both and adding it cannot fail an ordinary create. **Phase 2 lands the test that
    holds this equal to what Terraform sets**; until then this is a mirror, not a verified copy.
  STALE_LOCK_SECONDS: Age past which a held lock is stolen — the machine timeout plus a margin
    for the delay between an execution's last state and its timeout being observed. Strictly
    greater than the timeout, asserted by a test: a threshold below it would let a *running*
    execution's lock be stolen, which is the race this module exists to prevent.
  LOCK_VERSION: Body schema version, recorded so a later reader can tell which shape wrote an
    object. Nothing reads it back today — a version-aware branch would need a second shape to
    branch on, and inventing one now would be a guess about a migration nobody has designed.
  WORDING: This plane's six lock sentences. Literals here, so ``observability``'s rule that a
    message is a literal and everything variable is a field still holds at the emitting module.
"""

import logging

from cpcommon import clients, config, observability
from cpcommon import lock as _lock
from cpcommon.lock import LockWording

logger = logging.getLogger()

LOCK_PREFIX = "locks/table-builder"
MACHINE_TIMEOUT_SECONDS = 3600
STALE_LOCK_SECONDS = MACHINE_TIMEOUT_SECONDS + 900
LOCK_VERSION = 1

WORDING = LockWording(
    acquired="refresh lock acquired",
    refused="refresh lock refused",
    stealing_stale="stealing stale refresh lock",
    stealing_unreadable="stealing unreadable refresh lock",
    released="refresh lock released",
    release_failed="refresh lock release failed",
)

__all__ = [
    "LOCK_PREFIX",
    "LOCK_VERSION",
    "MACHINE_TIMEOUT_SECONDS",
    "STALE_LOCK_SECONDS",
    "WORDING",
    "acquire",
    "lock_key",
    "release",
]


def lock_key(database: str, table: str) -> str:
    """Builds the lock object's key, rejecting anything that could escape the prefix.

    Both names are catalog-safe by construction (they are the S3 prefix, the principal
    tag and the Glue database name), so this validation should never fire in production. It
    raises rather than sanitising deliberately: a sanitised name would silently address a
    *different* table's lock, which is worse than the traversal it was trying to prevent.

    Args:
      database: The target Glue database name.
      table: The target table name.

    Returns:
      The lock object's key under the admin bucket.

    Raises:
      ValueError: If either name is not a catalog-safe identifier.
    """
    for label, value in (("database", database), ("table", table)):
        if not isinstance(value, str) or not config.CATALOG_IDENTIFIER_RE.fullmatch(value):
            raise ValueError(f"refresh lock {label} is not catalog-safe: {value!r}")
    return f"{LOCK_PREFIX}/{database}/{table}.json"


def acquire(database: str, table: str, holder: str) -> tuple[bool, str | None]:
    """Claims the table's refresh lock, stealing it only when it is provably stale.

    A thin binding of ``cpcommon.lock.acquire`` to this plane's key, threshold and wording. The
    holder is validated FIRST, before the key is composed, so a call carrying both a bad holder and
    a bad name still raises about the holder.

    ``_read`` is passed as a module global resolved at call time rather than bound at import, which
    is what lets a test pin the read so two acquires see the same stale tag and the compare-and-set
    decides between them.

    Args:
      database: The target Glue database name.
      table: The target table name.
      holder: The claiming execution's ARN, recorded for diagnosis only. Never logged as a field.

    Returns:
      An ``(acquired, etag)`` tuple. The tag is what ``release`` must present; it is None whenever
      the lock was not acquired, and may be None on success if S3 returned no tag.

    Raises:
      ValueError: If either name is not a catalog-safe identifier, or the holder is not a
        non-empty string.
      ClientError: Any write fault that is not a precondition failure.
    """
    _lock.assert_usable_holder(holder, "refresh lock")
    return _lock.acquire(
        bucket=config.ADMIN_BUCKET,
        key=lock_key(database, table),
        holder=holder,
        stale_after_seconds=STALE_LOCK_SECONDS,
        wording=WORDING,
        fields={"database": database, "table": table},
        read=_read,
        version=LOCK_VERSION,
    )


def release(database: str, table: str, etag: str | None) -> None:
    """Marks the table's lock free, under the tag the acquire returned.

    Never raises and never retries a lost compare-and-swap — see ``cpcommon.lock.release``.

    **The key is composed AFTER the etag check and inside a guard**, which is not tidiness: as an
    argument to the shared release it would run before both, so an uncatalog-safe name would raise
    out of a function whose whole contract is that it cannot fail. The verb that calls this runs on
    every terminal path including the failure path, and a raise there is a task failure that
    replaces a recorded user failure with silence.

    Args:
      database: The target Glue database name.
      table: The target table name.
      etag: The tag ``acquire`` returned. A falsy tag means there is nothing safe to condition on,
        so the release is skipped rather than written unconditionally.

    Returns:
      None.

    Raises:
      None.
    """
    if not etag:
        logger.warning("refresh lock for %s.%s has no etag to release against", database, table)
        return

    try:
        key = lock_key(database, table)
    except ValueError as err:
        logger.error("refresh lock release for %s.%s failed: %s", database, table, err)
        observability.error(WORDING.release_failed, database=database, table=table)
        return

    _lock.release(
        bucket=config.ADMIN_BUCKET,
        key=key,
        etag=etag,
        wording=WORDING,
        fields={"database": database, "table": table},
        version=LOCK_VERSION,
    )


def _read(key: str) -> tuple[bytes | None, str | None]:
    """Reads the lock object's current bytes and entity tag.

    The bucket is read at call time rather than closed over at import, because a caller's tests set
    it as a module attribute on ``cpcommon.config``.

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
        logger.info("no readable refresh lock at %s (%s)", key, err)
        return None, None
