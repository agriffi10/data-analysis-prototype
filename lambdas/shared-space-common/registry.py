"""Shared-space registry I/O — the source of truth.

The registry is one S3 control object per space in the analytics admin bucket. This module owns
every read and write of it: atomic name reservation, terminal status writes, member-list
rewrites, and the final delete that frees the name. The privileged orchestrator role is the only
writer.

Concurrent executions can touch the same space, because the Pipe starts the state machine
fire-and-forget, so every non-create mutator is an optimistic compare-and-swap through the
shared primitive: read the record with its tag, apply the change to the freshly-read record, and
write conditioned on that tag.
"""

import json
from datetime import UTC, datetime

import casio
from cpcommon import clients
from cpcommon import config as cpconfig


class ProvisioningError(Exception):
    """A failed create step, such as a taken name or a full membership slot. Terminal.

    Recorded as a failed registry and cache status carrying the reason, then re-raised.
    """


def _key(name):
    """Builds the S3 key of one space's registry object.

    Args:
      name: The space name.

    Returns:
      The object key under the admin bucket.

    Raises:
      None.
    """
    return f"shared-spaces/{name}.json"


def now_iso() -> str:
    """Returns the current UTC time in the registry's timestamp format.

    Args:
      None.

    Returns:
      The timestamp string.

    Raises:
      None.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(name: str) -> tuple[dict | None, str | None]:
    """Reads a space's registry record and its entity tag.

    Only a true-absent signal is treated as missing. The admin bucket role holds list
    permission, so unlike the cache a denial is not read as absence — any other fault propagates
    rather than risk overwriting real data.

    Args:
      name: The space name.

    Returns:
      A ``(record, etag)`` tuple, both None when the space does not exist.

    Raises:
      ClientError: On any S3 fault other than absence.
      ValueError: If the stored record is not valid JSON.
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
    """Writes a registry record conditionally on the tag it was read at.

    Args:
      name: The space name.
      record: The record to write.
      etag: The tag to match, or None to write only if the object is absent.

    Returns:
      None.

    Raises:
      ClientError: On a precondition failure, so the CAS loop can retry, or any other S3 fault.
    """
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
    """Reads a space's registry record.

    Args:
      space: The space name.

    Returns:
      The record, or None when the space does not exist.

    Raises:
      ClientError: On any S3 fault other than absence.
    """
    record, _etag = _read(space)
    return record


def reserve(name: str, actor: str, request_id: str) -> str:
    """Atomically creates the registry object to claim a name.

    The create-if-absent write is what makes the name globally unique. A previous create by the
    same owner that ended failed left its reservation behind — the name was never rolled back,
    and the provisioning steps are all idempotent — so the owner is allowed to re-reserve it,
    otherwise a one-off failure would strand the name behind a taken-name refusal forever.

    Args:
      name: The requested space name.
      actor: The verified creator.
      request_id: The run's request id.

    Returns:
      ``created``, or ``replay`` when this exact request already created it.

    Raises:
      ProvisioningError: On a genuine collision, where a different request already owns the name.
      ClientError: On any S3 fault other than a precondition failure.
      RuntimeError: When collision resolution exhausts its attempts.
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
            IfNoneMatch="*",
        )
        return "created"
    except s3.exceptions.ClientError as exc:
        if not casio.is_precondition(exc):
            raise
        return _resolve_reserve_collision(name, actor, request_id, record, exc)


def _resolve_reserve_collision(name: str, actor: str, request_id: str, record: dict, cause: Exception) -> str:
    """Resolves a create collision into a replay, a permitted overwrite, or a refusal.

    The failed-retry overwrite is conditioned on the tag just read rather than written
    unconditionally, so two simultaneous retries of the same failed create cannot both commit —
    the loser gets a precondition failure and re-reads. A reservation that vanished between the
    create attempt and the read is retried as a clean conditional create.

    Args:
      name: The requested space name.
      actor: The verified creator.
      request_id: The run's request id.
      record: The record the create attempted to write.
      cause: The precondition failure that triggered this resolution.

    Returns:
      ``replay`` for the same request, or ``created`` when the owner's own failed reservation
      was overwritten.

    Raises:
      ProvisioningError: When the name is genuinely taken.
      RuntimeError: When the attempts are exhausted.
      ClientError: On any S3 fault other than a precondition failure.
    """
    for _ in range(casio.MAX_CAS_ATTEMPTS):
        existing, etag = _read(name)
        if existing is None:
            try:
                _put(name, record, None)
                return "created"
            except Exception as exc:
                if casio.is_precondition(exc):
                    continue
                raise
        if existing.get("lastRequestId") == request_id and existing.get("owner") == actor:
            return "replay"
        if existing.get("owner") == actor and existing.get("status") == "failed":
            try:
                _put(name, record, etag)
                return "created"
            except Exception as exc:
                if casio.is_precondition(exc):
                    continue
                raise
        raise ProvisioningError("name already taken") from cause
    raise RuntimeError(f"reserve collision resolution for {name} exhausted attempts")


def finalize(name: str, actor: str, request_id: str, status: str, reason: str | None = None) -> None:
    """Rewrites the registry record with a create's outcome.

    Preserves the creation timestamp the reservation stamped, which this full rewrite would
    otherwise drop. Compare-and-swap, so a racing writer cannot be lost.

    Args:
      name: The space name.
      actor: The verified creator, who is the sole member at this point.
      request_id: The run's request id.
      status: ``active`` on success, or ``failed``.
      reason: The failure reason, when there is one.

    Returns:
      None.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """

    def apply(existing):
        """Builds the outcome record, carrying forward the creation timestamp.

        Args:
          existing: The freshly-read record, or None.

        Returns:
          The record to write.

        Raises:
          None.
        """
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
    """Returns the acknowledged-member usernames for a registry record.

    Membership stays a plain list of names; join status is tracked out of band as its own list
    of members who have signed in and picked up the space. A record written before that concept
    existed has no such field — its members predate it, so they are all treated as acknowledged.

    Callers do not persist through this. They used to, by setting the field before saving the
    roster, and that contract was deleted because it carried the same stale-snapshot defect as
    the roster itself. The saver now derives the field inside its own compare-and-swap and takes
    a delta. This is a pure read.

    Args:
      registry: The registry record.

    Returns:
      The acknowledged member names.

    Raises:
      None.
    """
    ack = registry.get("acknowledged")
    if ack is None:
        owner = registry.get("owner")
        return [m for m in registry.get("members", []) if m != owner]
    return list(ack)


def save_members(registry: dict, request_id: str, *, add=(), remove=(), acknowledge=()) -> dict:
    """Applies a membership delta under compare-and-swap and returns the committed record.

    A delta, not a computed list, and that is the whole point. This used to take the roster the
    caller had derived from a snapshot read before the request began, and assign it over the
    freshly-read record — so the CAS re-read the record and then overwrote the one field it
    exists to protect with a stale value. Two overlapping requests on one space were
    last-write-wins on the roster, and a concurrent remove reinstated a just-added member.
    Nothing serializes them: the Pipe is fire-and-forget and the message group is one global
    constant.

    The new roster is derived from the freshly-read record inside the transform, so both
    interleavings of a concurrent add and remove take effect. The acknowledged list is derived
    the same way and for the same reason — it was carrying the identical bug one field over.
    Removals drop from both; an add lands in the roster only, so a newly-added user stays pending
    until they acknowledge; and the acknowledge delta promotes an existing member to active. Four
    verbs call this, and the acknowledging one is the only caller that adds to the acknowledged
    list — left out, it would have kept passing a whole computed list and kept the defect.

    Status is no longer set here. It used to be forced to active unconditionally, which let a
    membership write racing a delete return a deleting space to active, and the cascade would
    then run against a record claiming to be healthy. Only a default remains, to heal a record
    written before the field existed.

    Args:
      registry: The registry record, used for the space name and as the fallback base.
      request_id: The run's request id.
      add: Members to add.
      remove: Members to remove.
      acknowledge: Members promoting themselves from pending to active.

    Returns:
      The committed record, so callers can fan the roster out from what actually landed. Fanning
      out from the caller's own list would re-introduce the same defect one layer down, and the
      cache would disagree with the registry.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """
    name = registry["name"]
    removing = set(remove)

    def apply(existing):
        """Derives the new roster and acknowledged list from the freshly-read record.

        The acknowledged list is read before the add is applied, and that order is load-bearing:
        a record predating the pending concept has no such field, so every member reads as
        acknowledged, and reading after the add would sweep the member being added right now
        into that set and show them active instead of pending.

        Args:
          existing: The freshly-read record, or None.

        Returns:
          The record to write.

        Raises:
          None.
        """
        record = dict(existing) if existing is not None else dict(registry)
        prior_ack = effective_acknowledged(record)
        members = [m for m in record.get("members", []) if m not in removing]
        for member in add:
            if member not in members:
                members.append(member)
        record["members"] = members
        ack = [a for a in prior_ack if a not in removing and a in members]
        for member in acknowledge:
            if member in members and member not in ack:
                ack.append(member)
        record["acknowledged"] = ack
        record["lastRequestId"] = request_id
        record.setdefault("status", "active")
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
    """Rewrites a space's status, preserving its owner, members and the rest.

    Compare-and-swap on the freshly-read record, so the status change is applied to current state
    and never regresses a value a concurrent writer just committed.

    Args:
      registry: The registry record, used for the space name and as the fallback base.
      status: The new status — deleting before the cascade, or failed on a hard error.
      request_id: The run's request id.
      reason: The failure reason, when there is one. Absent, any existing reason is cleared.

    Returns:
      None.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """
    name = registry["name"]

    def apply(existing):
        """Applies the status change to the freshly-read record.

        Args:
          existing: The freshly-read record, or None.

        Returns:
          The record to write.

        Raises:
          None.
        """
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
    """Deletes the registry object — the last cascade step, freeing the name for reuse.

    Idempotent: deleting an absent key is a no-op in S3.

    Args:
      name: The space name.

    Returns:
      None.

    Raises:
      ClientError: On any S3 fault.
    """
    clients.s3().delete_object(Bucket=cpconfig.ADMIN_BUCKET, Key=_key(name))
