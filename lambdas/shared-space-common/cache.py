"""Per-user shared-connections cache (SPEC-051/053; SPEC-062 shared layer).

The cache at ``{username}/user_settings/shared-connections.json`` in the user-space
bucket is the UI projection of a user's spaces (the registry is the source of truth;
this is what the browser reads). The privileged orchestrator role may write any
user's prefix. Every write is a read-modify-write (never an S3 delete), idempotent.
"""

import json

import config
import clients


def _key(username):
    return f"{username}/user_settings/shared-connections.json"


def upsert_entry(username, entry):
    """Read-modify-write the user's cache, upserting ``entry`` by name."""
    s3 = clients.s3()
    try:
        obj = s3.get_object(Bucket=config.USER_SPACE_BUCKET, Key=_key(username))
        cache = json.loads(obj["Body"].read())
    except s3.exceptions.NoSuchKey:
        cache = {"version": 1, "connections": []}
    connections = [c for c in cache.get("connections", []) if c.get("name") != entry["name"]]
    connections.append(entry)
    cache = {"version": 1, "connections": connections}
    s3.put_object(
        Bucket=config.USER_SPACE_BUCKET,
        Key=_key(username),
        Body=json.dumps(cache).encode(),
        ContentType="application/json",
    )


def remove_entry(username, name):
    """Remove the user's cache entry for ``name`` (read-modify-write; never an S3
    delete). Idempotent — a missing cache or absent entry is a no-op."""
    s3 = clients.s3()
    try:
        obj = s3.get_object(Bucket=config.USER_SPACE_BUCKET, Key=_key(username))
        cache = json.loads(obj["Body"].read())
    except s3.exceptions.NoSuchKey:
        return
    connections = [c for c in cache.get("connections", []) if c.get("name") != name]
    s3.put_object(
        Bucket=config.USER_SPACE_BUCKET,
        Key=_key(username),
        Body=json.dumps({"version": 1, "connections": connections}).encode(),
        ContentType="application/json",
    )


def write_owner_projection(owner, name, members, created_at=None):
    """Update the OWNER's cache entry with the current member list — the
    owner-readable projection the Manage drawer renders (SPEC-053); members never
    see this list. ``created_at`` (when known) is carried so the Connections card
    can render the "created <date>" meta line."""
    entry = {"name": name, "role": "owner", "status": "active", "members": members}
    if created_at:
        entry["createdAt"] = created_at
    upsert_entry(owner, entry)


def write_member_entry(member, name, owner, created_at=None):
    """Write a MEMBER's cache entry for a space they belong to. Members never get the
    member list (privacy), but they do get the ``owner`` name and ``createdAt`` so the
    Connections card can render its "owner: <name>" / "created <date>" meta line."""
    entry = {"name": name, "role": "member", "status": "active", "owner": owner}
    if created_at:
        entry["createdAt"] = created_at
    upsert_entry(member, entry)
