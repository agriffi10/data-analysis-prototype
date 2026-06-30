"""Shared-space registry I/O (SPEC-051/056; SPEC-062 shared layer).

The registry is the source of truth: one S3 control object per space at
``shared-spaces/{name}.json`` in the analytics admin bucket. This module owns every
read/write of it — atomic name reservation (create-once), terminal status writes,
member-list rewrites, and the final delete that frees the name. The privileged
orchestrator role is the only writer.
"""

import json
import time

import config
import clients


class ProvisioningError(Exception):
    """A create step failed (e.g. name taken, slot full). Recorded as a terminal
    ``failed`` registry/cache status with the reason, then re-raised -> Fail."""


def _key(name):
    return f"shared-spaces/{name}.json"


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load(space):
    """Return the registry record for ``space`` (dict) or None if it doesn't exist."""
    s3 = clients.s3()
    try:
        obj = s3.get_object(Bucket=config.ADMIN_BUCKET, Key=_key(space))
    except s3.exceptions.NoSuchKey:
        return None
    return json.loads(obj["Body"].read())


def reserve(name, actor, request_id):
    """Atomically create the registry object (status=provisioning) to claim the
    globally-unique name. Returns 'created', or 'replay' if this exact request
    already created it (idempotent re-run). Raises ProvisioningError on a genuine
    name collision (a different request already owns the name).

    A previous create by the SAME owner that ended ``failed`` left its reservation
    behind (the name was never rolled back, and the provisioning steps are all
    idempotent), so the owner is allowed to re-reserve it — otherwise a one-off
    failure would strand the name behind "name already taken" forever."""
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
            Bucket=config.ADMIN_BUCKET,
            Key=_key(name),
            Body=json.dumps(record).encode(),
            ContentType="application/json",
            IfNoneMatch="*",  # atomic create-if-absent -> global name uniqueness
        )
        return "created"
    except s3.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in ("PreconditionFailed", "412"):
            raise
        existing = load(name) or {}
        if existing.get("lastRequestId") == request_id and existing.get("owner") == actor:
            return "replay"
        # The owner retrying their own failed create: overwrite the stale reservation
        # and proceed (idempotent provisioning reuses anything already created).
        if existing.get("owner") == actor and existing.get("status") == "failed":
            s3.put_object(
                Bucket=config.ADMIN_BUCKET,
                Key=_key(name),
                Body=json.dumps(record).encode(),
                ContentType="application/json",
            )
            return "created"
        raise ProvisioningError("name already taken") from exc


def finalize(name, actor, request_id, status, reason=None):
    """Rewrite the registry record for a create outcome (members=[owner]); used to
    flag ``active`` on success or ``failed`` with a reason on a create error.
    Preserves the ``createdAt`` stamped by ``reserve`` (this full rewrite would
    otherwise drop it)."""
    existing = load(name) or {}
    record = {
        "version": 1,
        "name": name,
        "owner": actor,
        "members": [actor],
        "status": status,
        "lastRequestId": request_id,
        "createdAt": existing.get("createdAt") or now_iso(),
        "updatedAt": now_iso(),
    }
    if reason:
        record["reason"] = reason
    clients.s3().put_object(
        Bucket=config.ADMIN_BUCKET,
        Key=_key(name),
        Body=json.dumps(record).encode(),
        ContentType="application/json",
    )


def save_members(registry, members, request_id):
    """Rewrite the registry record with a new members list (preserving owner /
    createdAt / etc.) — the add/remove/leave read-modify-write path."""
    record = dict(registry)
    record["members"] = members
    record["status"] = "active"
    record["lastRequestId"] = request_id
    record["updatedAt"] = now_iso()
    clients.s3().put_object(
        Bucket=config.ADMIN_BUCKET,
        Key=_key(record["name"]),
        Body=json.dumps(record).encode(),
        ContentType="application/json",
    )


def set_status(registry, status, request_id, reason=None):
    """Rewrite the registry record with a new status, preserving owner/members/etc.
    Flags a space ``deleting`` before the cascade and ``failed`` on a hard error."""
    record = dict(registry)
    record["status"] = status
    record["lastRequestId"] = request_id
    record["updatedAt"] = now_iso()
    if reason:
        record["reason"] = reason
    else:
        record.pop("reason", None)
    clients.s3().put_object(
        Bucket=config.ADMIN_BUCKET,
        Key=_key(record["name"]),
        Body=json.dumps(record).encode(),
        ContentType="application/json",
    )


def delete(name):
    """Delete the registry object — the LAST cascade step, which frees the name for
    reuse. Idempotent (deleting an absent key is a no-op in S3)."""
    clients.s3().delete_object(Bucket=config.ADMIN_BUCKET, Key=_key(name))
