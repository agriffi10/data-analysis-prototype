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
    the pending concept, so they are all treated as acknowledged (active).

    CALLERS DO NOT PERSIST THROUGH THIS. They used to, by setting
    ``registry["acknowledged"]`` before ``save_members``; SPEC-151 FR-004 deleted that
    contract because it carried the same stale-snapshot defect as the roster itself.
    ``save_members`` now derives ``acknowledged`` inside its own CAS and takes an
    ``acknowledge=`` delta. This function is a pure read.
    """
    ack = registry.get("acknowledged")
    if ack is None:
        owner = registry.get("owner")
        return [m for m in registry.get("members", []) if m != owner]
    return list(ack)


def save_members(registry: dict, request_id: str, *, add=(), remove=(), acknowledge=()) -> dict:
    """Apply a membership DELTA under compare-and-swap; return the committed record.

    A DELTA, not a computed list, and that is the whole point (SPEC-151 FR-004). This
    used to take the roster the caller had derived from ``event["registry"]`` — a
    snapshot read before the request began — and assign it over the freshly-read record.
    The CAS re-read the record and then overwrote the one field it exists to protect
    with a stale value, so two overlapping requests on one space were last-write-wins on
    the roster: a concurrent remove reinstated a just-added member. Nothing serializes
    them (``shared-spaces/pipe.tf`` is FIRE_AND_FORGET and the group id is one global
    constant), which ``casio``'s own module docstring says outright.

    The new roster is derived from ``existing["members"]`` INSIDE ``apply``, so both
    interleavings of a concurrent add and remove take effect. ``acknowledged`` is derived
    the same way and for the same reason — it was carrying the identical stale-snapshot
    bug one field over. Removals drop from both; ``add`` lands in ``members`` only, so a
    newly-added user stays ``pending`` until they acknowledge (SPEC-073); ``acknowledge``
    is the fourth verb's delta, promoting an existing member pending -> active.

    FOUR callers, not the three SPEC-151 FR-004 lists: ``acknowledge-membership`` is one
    too, and it is the only one that ADDS to ``acknowledged``. Left out, it would have
    kept passing a whole computed list and kept the defect.

    STATUS IS NO LONGER SET. It used to be forced to ``"active"`` unconditionally, which
    let a membership write racing a delete return a ``deleting`` space to ``active`` —
    the cascade would then run against a record claiming to be healthy. Only ``setdefault``
    remains, to heal a record written before the field existed.

    Returns the committed record so callers can fan the roster out from what actually
    landed. Fanning out from the caller's own list would re-introduce the same defect one
    layer down: the cache would disagree with the registry.
    """
    name = registry["name"]
    removing = set(remove)

    def apply(existing):
        record = dict(existing) if existing is not None else dict(registry)
        # BEFORE the add is applied, and the order is load-bearing: a pre-SPEC-073 record
        # has no `acknowledged` field, so `effective_acknowledged` treats every member as
        # acknowledged. Read after the add, that would sweep the member being added right
        # now into the acknowledged set and show them `active` instead of `pending`.
        # Still read from the FRESH record, not the caller's snapshot — that is the point
        # of the delta.
        prior_ack = effective_acknowledged(record)
        members = [m for m in record.get("members", []) if m not in removing]
        for member in add:
            if member not in members:
                members.append(member)
        record["members"] = members
        ack = [a for a in prior_ack if a not in removing and a in members]
        for member in acknowledge:
            # `in members` guards the race the delta exists for: acknowledging a
            # membership a concurrent remove just revoked must not re-create it.
            if member in members and member not in ack:
                ack.append(member)
        record["acknowledged"] = ack
        record["lastRequestId"] = request_id
        record.setdefault("status", "active")
        # Heal a record written before createdAt was stamped (older spaces) so the
        # Connections card's "created <date>" line isn't permanently blank.
        record.setdefault("createdAt", now_iso())
        record["updatedAt"] = now_iso()
        return record

    return casio.cas_mutate(
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
