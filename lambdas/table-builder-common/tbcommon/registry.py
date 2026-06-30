"""Shared-spaces registry read (SPEC-056 source of truth; consumed here read-only).

The registry is one S3 control object per space at ``shared-spaces/{name}.json`` in
the analytics admin bucket (owned by the shared-spaces control plane). The
table-builder validator only READS it, to authorize that the actor is an active
member of a shared space before allowing a table there.
"""

import json

from . import config, clients


def load(name):
    """Return the registry record for shared space ``name`` (dict) or None if absent."""
    s3 = clients.s3()
    try:
        obj = s3.get_object(Bucket=config.ADMIN_BUCKET, Key=f"shared-spaces/{name}.json")
    except s3.exceptions.NoSuchKey:
        return None
    return json.loads(obj["Body"].read())


def is_active_member(record, actor):
    """True iff ``record`` is an active space and ``actor`` is in its members."""
    return bool(record) and record.get("status") == "active" and actor in (record.get("members") or [])
