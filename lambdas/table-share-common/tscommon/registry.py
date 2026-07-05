"""Read-only access to the shared-spaces registry.

The registry is one S3 control object per space at shared-spaces/{name}.json in the
analytics admin bucket, owned by the shared-spaces control plane. Table-share only
reads it: source authorization (the actor must be an active member of a shared
source's space) and recipient-space existence (any ACTIVE space is a valid target —
membership not required, docs/table-share-architecture.md §3).
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
    """True iff ``record`` is an active space and ``actor`` is in its members."""
    return is_active(record) and actor in (record.get("members") or [])
