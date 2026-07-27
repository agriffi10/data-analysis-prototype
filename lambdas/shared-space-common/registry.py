"""Shared-space registry I/O.

The registry is the source of truth: one S3 control object per space at
``shared-spaces/{name}.json`` in the analytics admin bucket. This module owns every
read/write of it — atomic name reservation (create-once), terminal status writes,
member-list rewrites, and the final delete that frees the name. The privileged
orchestrator role is the only writer.

Concurrent control-plane executions can touch the same space (the Pipe starts the
Standard state machine fire-and-forget), so every non-create mutator is an optimistic
compare-and-swap via the shared ``casio`` helper: read the record with its ETag, apply
the change to the *freshly-read* record, and ``PutObject`` conditioned on that ETag; a
412 means a concurrent writer won, so re-read, re-apply, and retry (SPEC-082).
"""

import json
from datetime import UTC, datetime

import casio
from cpcommon import clients
from cpcommon import config as cpconfig


class ProvisioningError(Exception):
    """A failed create step (e.g. name taken, slot full); terminal.

    Recorded as a ``failed`` registry/cache status with the reason, then re-raised.
    """


def _key(name):
    return f"shared-spaces/{name}.json"


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(name: str) -> tuple[dict | None, str | None]:
    """Return ``(record, etag)`` for a space; ``(None, None)`` when it doesn't exist.

    Only a true-absent signal (``NoSuchKey``/404) is treated as missing — the admin
    bucket role has ``s3:ListBucket``, so unlike the cache we do NOT read a 403 as
    absent; any other S3 error propagates rather than risk overwriting real data.
    """
    s3 = clients.s3()
    try:
        obj = s3.get_object(Bucket=cpconfig.ADMIN_BUCKET, Key=_key(name))
    except s3.exceptions.NoSuchKey:
        return None, None
    except s3.exceptions.ClientError as exc:
        if casio.error_code(exc) in ("NoSuchKey", "NotFound", "404"):
            return None, None
        raise
    return json.loads(obj["Body"].read()), obj.get("ETag")


def _put(name: str, record: dict, etag: str | None) -> None:
    """Write a registry record conditionally: ``If-Match`` the read ETag, or
    ``If-None-Match: *`` when absent (create). Raises the S3 ClientError on a
    precondition failure so the CAS loop can retry."""
    kwargs = {
        "Bucket": cpconfig.ADMIN_BUCKET,
        "Key": _key(name),
        "Body": json.dumps(record).encode(),
        "ContentType": "application/json",
    }
    if etag is None:
        kwargs["IfNoneMatch"] = "*"
    else:
        kwargs["IfMatch"] = etag
    clients.s3().put_object(**kwargs)


def load(space: str) -> dict | None:
    """Return the registry record for ``space`` (dict) or None if it doesn't exist."""
    record, _etag = _read(space)
    return record


def reserve(name: str, actor: str, request_id: str) -> str:
    """Atomically create the registry object (status=provisioning) to claim the name.

    Returns 'created', or 'replay' if this exact request already created it
    (idempotent re-run). Raises ProvisioningError on a genuine name collision (a
    different request already owns the name).

    A previous create by the SAME owner that ended ``failed`` left its reservation
    behind (the name was never rolled back, and the provisioning steps are all
    idempotent), so the owner is allowed to re-reserve it — otherwise a one-off
    failure would strand the name behind "name already taken" forever.
    """
    s3 = clients.s3()
    record = {
        "version": 1,
        "name": name,
        "owner": actor,
        "members": [actor],
        "status": "provisioning",
        "createdAt": now_iso(),
        "lastRequestId": request_id,
    }
    try:
        s3.put_object(
            Bucket=cpconfig.ADMIN_BUCKET,
            Key=_key(name),
            Body=json.dumps(record).encode(),
            ContentType="application/json",
            IfNoneMatch="*",  # atomic create-if-absent -> global name uniqueness
        )
        return "created"
    except s3.exceptions.ClientError as exc:
        if not casio.is_precondition(exc):
            raise
        return _resolve_reserve_collision(name, actor, request_id, record, exc)


def _resolve_reserve_collision(name: str, actor: str, request_id: str, record: dict, cause: Exception) -> str:
    """Resolve a create collision: ``replay`` for the same request, a *conditional*
    overwrite when the owner retries their own ``failed`` create, else the name is
    genuinely taken.

    The failed-retry overwrite is conditioned on the ETag just read (not the old
    unconditional put), so two simultaneous retries of the same failed create can't
    both commit — the loser gets a 412 and re-reads (SPEC-082 FR-002).
    """
    for _ in range(casio.MAX_CAS_ATTEMPTS):
        existing, etag = _read(name)
        if existing is None:
            # The reservation vanished between the create attempt and now — retry a
            # clean conditional create.
            try:
                _put(name, record, None)
                return "created"
            except Exception as exc:
                if casio.is_precondition(exc):
                    continue
                raise
        if existing.get("lastRequestId") == request_id and existing.get("owner") == actor:
            return "replay"
        # The owner retrying their own failed create: overwrite the stale reservation
        # and proceed (idempotent provisioning reuses anything already created).
        if existing.get("owner") == actor and existing.get("status") == "failed":
            try:
                _put(name, record, etag)
                return "created"
            except Exception as exc:
                if casio.is_precondition(exc):
                    continue  # a sibling retry won; re-read and re-evaluate
                raise
        raise ProvisioningError("name already taken") from cause
    raise RuntimeError(f"reserve collision resolution for {name} exhausted attempts")


def finalize(name: str, actor: str, request_id: str, status: str, reason: str | None = None) -> None:
    """Rewrite the registry record for a create outcome (members=[owner]).

    Flags ``active`` on success or ``failed`` with a reason on a create error.
    Preserves the ``createdAt`` stamped by ``reserve`` (this full rewrite would
    otherwise drop it). Compare-and-swap so a racing writer can't be lost (SPEC-082).
    """

    def apply(existing):
        record = {
            "version": 1,
            "name": name,
            "owner": actor,
            "members": [actor],
            "status": status,
            "lastRequestId": request_id,
            "createdAt": (existing or {}).get("createdAt") or now_iso(),
            "updatedAt": now_iso(),
        }
        if reason:
            record["reason"] = reason
        return record

    casio.cas_mutate(
        read=lambda: _read(name),
        apply=apply,
        write=lambda record, etag: _put(name, record, etag),
        label=f"registry/{name}",
    )


def effective_acknowledged(registry: dict) -> list[str]:
    """Return the acknowledged-member usernames for a registry record (SPEC-073).

    Membership stays a plain ``members: string[]``; join status is tracked out-of-band
    as ``acknowledged: string[]`` (members who have signed in and picked up the space).
    A record written before SPEC-073 has no ``acknowledged`` field — its members predate
    the pending concept, so they are all treated as acknowledged (active). The caller
    persists any change by setting ``registry["acknowledged"]`` before ``save_members``.
    """
    ack = registry.get("acknowledged")
    if ack is None:
        owner = registry.get("owner")
        return [m for m in registry.get("members", []) if m != owner]
    return list(ack)


def save_members(registry: dict, members: list[str], request_id: str) -> None:
    """Rewrite the registry record with a new members list, preserving other fields.

    The add/remove/leave read-modify-write path. Compare-and-swap: the new members +
    ``acknowledged`` (the caller's intent) are layered onto the *freshly-read* record
    each attempt, so a concurrent writer's other-field change (e.g. ``set_status``)
    survives instead of being lost (SPEC-082).
    """
    name = registry["name"]
    acknowledged = registry.get("acknowledged")

    def apply(existing):
        record = dict(existing) if existing is not None else dict(registry)
        record["members"] = members
        record["status"] = "active"
        record["lastRequestId"] = request_id
        if acknowledged is not None:
            record["acknowledged"] = acknowledged
        # Heal a record written before createdAt was stamped (older spaces) so the
        # Connections card's "created <date>" line isn't permanently blank.
        record.setdefault("createdAt", now_iso())
        record["updatedAt"] = now_iso()
        return record

    casio.cas_mutate(
        read=lambda: _read(name),
        apply=apply,
        write=lambda record, etag: _put(name, record, etag),
        label=f"registry/{name}",
    )


def set_status(registry: dict, status: str, request_id: str, reason: str | None = None) -> None:
    """Rewrite the registry record with a new status, preserving owner/members/etc.

    Flags a space ``deleting`` before the cascade and ``failed`` on a hard error.
    Compare-and-swap on the freshly-read record, so the status change is applied to
    current state and never regresses a value a concurrent writer just committed
    (SPEC-082 FR-001).
    """
    name = registry["name"]

    def apply(existing):
        record = dict(existing) if existing is not None else dict(registry)
        record["status"] = status
        record["lastRequestId"] = request_id
        record["updatedAt"] = now_iso()
        if reason:
            record["reason"] = reason
        else:
            record.pop("reason", None)
        return record

    casio.cas_mutate(
        read=lambda: _read(name),
        apply=apply,
        write=lambda record, etag: _put(name, record, etag),
        label=f"registry/{name}",
    )


def delete(name: str) -> None:
    """Delete the registry object — the LAST cascade step, freeing the name for reuse.

    Idempotent (deleting an absent key is a no-op in S3).
    """
    clients.s3().delete_object(Bucket=cpconfig.ADMIN_BUCKET, Key=_key(name))
