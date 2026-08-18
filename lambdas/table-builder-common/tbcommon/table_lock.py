"""The per-table refresh lock.

Two refreshes of one table can overlap. ``MessageGroupId`` on the request queue is the target
database, so SQS serializes *delivery* per database, but the Pipe starts the state machine
``FIRE_AND_FORGET`` and returns immediately — so it is free to deliver the next message while the
previous execution is still running. The in-place ``glue:UpdateTable`` reduced the damage
(neither run can see a missing table) but could not close it, because Glue offers no
compare-and-set on ``UpdateTable``. This module is the serialization the catalog cannot provide:
the second refresh is refused rather than raced.

**The lock is released by OVERWRITING, never by deleting, and that is forced rather than chosen.**
The table-builder execution role carries an explicit ``Deny`` on ``s3:DeleteObject`` for the whole
admin bucket (``NoDataObjectDelete``), deliberately kept when the plane removed
``glue:DeleteTable``. Releasing by deletion would mean amending that Deny — trading a standing
safety property for an implementation convenience. So "free" is a *state* of the object, not its
absence, and a test greps this module to keep it that way.

The conditional-write protocol is ``cpcommon.cas``'s, but the loop is deliberately not:
``cas_mutate`` **retries** on a precondition failure, which is right for an append and wrong for a
lock. Here a lost precondition means another execution holds it, and the correct answer is to
refuse. Only ``cas.is_precondition`` is shared — the one place that knows a failed match and a
racing create are the same answer.

Attributes:
  LOCK_PREFIX: Key prefix for every lock object, under the admin bucket.
  MACHINE_TIMEOUT_SECONDS: The table-builder state machine's ``TimeoutSeconds``, mirrored here
    because a steal threshold is only meaningful against a bounded execution — a Standard machine
    with no timeout may run for a year, and no age threshold could be justified against it.
    Derived from the refresh path's worst case: every Task retries 3 times
    over 2/4/8-second intervals, so a state costs ``4 * timeout + 14`` seconds, and the path sums
    to ≈2400 s (validate 74, acquire 74, load-definition 74, inspect-source 254, infer-schema 494,
    diff-schema 74, apply-refresh 1214, release 74, notify 74). The create path is ≈2260 s, so
    3600 clears both and adding it cannot fail an ordinary create. **Phase 2 lands the test that
    holds this equal to what Terraform sets**; until then this is a mirror, not a verified copy.
  STALE_LOCK_SECONDS: Age past which a held lock is stolen — the machine timeout plus a margin
    for the delay between an execution's last state and its timeout being observed. Strictly
    greater than the timeout, asserted by a test: a threshold below it would let a *running*
    execution's lock be stolen, which is the race this module exists to prevent.
  LOCK_VERSION: Body schema version, recorded so a later reader can tell which shape wrote an
    object. Nothing reads it back today — a version-aware branch would need a second shape to
    branch on, and inventing one now would be a guess about a migration nobody has designed.
"""

import json
import logging
from datetime import UTC, datetime
from typing import cast

from cpcommon import cas, clients, config, observability

logger = logging.getLogger()

LOCK_PREFIX = "locks/table-builder"
MACHINE_TIMEOUT_SECONDS = 3600
STALE_LOCK_SECONDS = MACHINE_TIMEOUT_SECONDS + 900
LOCK_VERSION = 1

__all__ = [
    "LOCK_PREFIX",
    "LOCK_VERSION",
    "MACHINE_TIMEOUT_SECONDS",
    "STALE_LOCK_SECONDS",
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
        if not isinstance(value, str) or not config.CATALOG_IDENTIFIER_RE.match(value):
            raise ValueError(f"refresh lock {label} is not catalog-safe: {value!r}")
    return f"{LOCK_PREFIX}/{database}/{table}.json"


def acquire(database: str, table: str, holder: str) -> tuple[bool, str | None]:
    """Claims the table's refresh lock, stealing it only when it is provably stale.

    Conditional ``PutObject`` only — ``IfNoneMatch`` when the object does not exist yet, ``IfMatch``
    when it exists and is free or stale. A lost precondition is not retried: it means another
    execution claimed it between this read and this write, which is the answer, not a transient
    fault.

    A read failure is treated as absent, which makes the following write create-only and therefore
    a *refusal* when the object does in fact exist. That is the safe direction — the discipline
    ``log-sweep`` uses for the same reason — because the alternative is overwriting a live holder's
    lock on a transient S3 error.

    **The holder is validated, because a null holder is what "free" MEANS.** An empty or missing
    identity would write a lock that every later reader — including the next line of this module —
    correctly interprets as unheld, so the claim would succeed and grant nothing: two executions
    would hold ``acquired=True`` on one table, which is the exact state this module exists to
    prevent. The caller passes a per-request identity, and an absent path in ASL resolves to
    exactly this, so the guard is on the reachable case, not a theoretical one.

    **A lock this holder already owns is re-claimed, not refused.** The state machine retries the
    acquire task on a Lambda service fault, and a put whose response was lost has already written
    the lock — so a re-invocation that refused would fail a request whose own earlier attempt
    succeeded, and would do it under the one reason code that tells the user another refresh is
    running.

    That branch is why the holder MUST identify the execution and not the request. A request id
    identifies the message, and Pipes delivery is at-least-once, so a redelivered message runs a
    second execution carrying the same id while the first is still going — and this branch would
    then hand both of them the lock, with no refusal event and an acquire event reading
    ``stolen: False``. The caller passes the execution ARN for exactly that reason.

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
    if not isinstance(holder, str) or not holder:
        raise ValueError(f"refresh lock holder is not a usable identity: {holder!r}")

    key = lock_key(database, table)
    raw, etag = _read(key)

    if raw is None:
        return _claim(key, database, table, holder, etag=None, stolen=False)

    state = _parse(raw)
    if state is None:
        observability.warning(
            "stealing unreadable refresh lock", database=database, table=table, age_seconds=None
        )
        return _claim(key, database, table, holder, etag=etag, stolen=True)

    if state.get("holder") is None:
        return _claim(key, database, table, holder, etag=etag, stolen=False)

    if state.get("holder") == holder:
        logger.info("refresh lock for %s.%s is already ours — reclaiming", database, table)
        return _claim(key, database, table, holder, etag=etag, stolen=False)

    age = _age_seconds(state.get("acquiredAt"))
    if age is None or not 0 <= age <= STALE_LOCK_SECONDS:
        observability.warning(
            "stealing stale refresh lock", database=database, table=table, age_seconds=age
        )
        return _claim(key, database, table, holder, etag=etag, stolen=True)

    observability.info(
        "refresh lock refused",
        database=database,
        table=table,
        held_since=state.get("acquiredAt"),
    )
    return False, None


def release(database: str, table: str, etag: str | None) -> None:
    """Marks the table's lock free, under the tag the acquire returned.

    Never raises and never retries a lost compare-and-swap. Losing it means the lock was stolen by
    a later execution, and re-writing would clobber the new holder — so the loss is
    recorded and left alone. A request that did its work and then reported failure because of its
    own bookkeeping would be a worse outcome than a lock that FR-004 can recover anyway.

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
        _put(lock_key(database, table), _body(holder=None, acquired_at=None), etag)
    except Exception as err:  # noqa: BLE001
        logger.error("refresh lock release for %s.%s failed: %s", database, table, err)
        observability.error("refresh lock release failed", database=database, table=table)
        return

    observability.info("refresh lock released", database=database, table=table)


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
        logger.info("no readable refresh lock at %s (%s)", key, err)
        return None, None


def _parse(raw: bytes) -> dict | None:
    """Decodes a lock body, reporting an unusable one as unreadable rather than raising.

    A body nobody can read is not evidence that a refresh is running, so the caller treats None as
    stale. The alternative — treating it as held — leaves a table that can never be refreshed
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
        logger.warning("refresh lock body is not JSON (%s)", err)
        return None
    return state if isinstance(state, dict) else None


def _age_seconds(acquired_at: object) -> float | None:
    """Reports how long ago a lock was claimed.

    A NEGATIVE age is possible and is not filtered here — a future-dated claim time, from clock
    skew or a corrupt write, would otherwise be younger than every threshold forever and cost the
    table its refresh permanently, with no operator recovery path (the role cannot delete the
    object). The caller treats it as stealable for the same reason it treats an unreadable body
    that way: a timestamp that cannot be true is no evidence that a refresh is running.

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
    key: str, database: str, table: str, holder: str, *, etag: str | None, stolen: bool
) -> tuple[bool, str | None]:
    """Writes the claim conditionally, reporting a lost precondition as a refusal.

    Args:
      key: The lock object's key.
      database: The target Glue database name, for the event.
      table: The target table name, for the event.
      holder: The claiming execution's ARN.
      etag: The tag to match, or None to write only if the object is absent.
      stolen: Whether this claim took the lock from a stale or unreadable holder.

    Returns:
      An ``(acquired, etag)`` tuple.

    Raises:
      ClientError: Any write fault that is not a precondition failure.
    """
    body = _body(holder=holder, acquired_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    try:
        response = _put(key, body, etag)
    except Exception as exc:
        if cas.is_precondition(exc):
            observability.info("refresh lock refused", database=database, table=table, held_since=None)
            return False, None
        raise
    observability.info("refresh lock acquired", database=database, table=table, stolen=stolen)
    return True, response.get("ETag")


def _put(key: str, body: bytes, etag: str | None) -> dict:
    """Writes the lock object conditionally on the tag it was read at.

    Args:
      key: The lock object's key.
      body: The full object body.
      etag: The tag to match, or None to write only if the object is absent.

    Returns:
      The ``PutObject`` response, whose ETag is what a later release conditions on.

    Raises:
      ClientError: On a precondition failure, or any other S3 fault.
    """
    kwargs: dict[str, object] = {
        "Bucket": config.ADMIN_BUCKET,
        "Key": key,
        "Body": body,
        "ContentType": "application/json",
    }
    if etag is None:
        kwargs["IfNoneMatch"] = "*"
    else:
        kwargs["IfMatch"] = etag
    return cast("dict", clients.s3().put_object(**kwargs))


def _body(*, holder: str | None, acquired_at: str | None) -> bytes:
    """Renders a lock body.

    Args:
      holder: The holding execution's ARN, or None for a free lock.
      acquired_at: The ISO-8601 claim time, or None for a free lock.

    Returns:
      The encoded JSON body.

    Raises:
      None.
    """
    return json.dumps(
        {"version": LOCK_VERSION, "holder": holder, "acquiredAt": acquired_at}
    ).encode("utf-8")
