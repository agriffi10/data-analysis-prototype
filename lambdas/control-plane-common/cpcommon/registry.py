"""Read-only access to the shared-spaces registry (SPEC-107 — the union of the twins).

The registry is one S3 control object per space at ``shared-spaces/{name}.json`` in the
analytics admin bucket, owned by the shared-spaces control plane. Every control-plane
verb only ever READS it — to authorize that the actor is an active member of a shared
space, and (table-share) that a target space exists.
"""

import json

from . import clients, config


def load(name: str) -> dict | None:
    """Return the registry record for shared space ``name`` (dict) or None if absent."""
    s3 = clients.s3()
    try:
        obj = s3.get_object(Bucket=config.ADMIN_BUCKET, Key=f"shared-spaces/{name}.json")
    except s3.exceptions.NoSuchKey:
        return None
    return json.loads(obj["Body"].read())


def is_active(record: dict | None) -> bool:
    """True iff ``record`` is a provisioned, live space (a valid share target)."""
    return bool(record) and record.get("status") == "active"


def is_active_member(record: dict | None, actor: str) -> bool:
    """True iff ``record`` is an active space and ``actor`` is in its members.

    NOTE: "active" here is the SPACE's provisioning status, NOT SPEC-073's per-member
    Pending/Active join chip. Access is granted at add time (SPEC-073), so a member with
    a Pending join chip still passes this check.
    """
    return is_active(record) and actor in (record.get("members") or [])
