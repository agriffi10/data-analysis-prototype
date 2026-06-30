"""Per-user shared-connections cache (SPEC-051/053; SPEC-062 shared layer).

The cache at ``{username}/user_settings/shared-connections.json`` in the user-space
bucket is the UI projection of a user's spaces (the registry is the source of truth;
this is what the browser reads). The privileged orchestrator role may write any
user's prefix. Every write is a read-modify-write (never an S3 delete).

**Concurrency (the fix):** the cache is one S3 key per user, but multiple control-plane
executions overlap (the Pipe starts the Standard state machine FIRE_AND_FORGET, so
"serial intake" is not serial execution). Two operations touching the same user's
cache at once — e.g. being added to one space while creating/being-added to another —
would lose-update under a plain read-then-write. So every mutation is an **optimistic
compare-and-swap**: read the object + its ETag, modify, then ``PutObject`` conditioned
on that ETag (``If-Match``) or on absence (``If-None-Match: *``); a ``412
PreconditionFailed`` means a concurrent writer won — re-read and retry.

**Absence handling (the hardening):** a missing object reads as ``NoSuchKey`` when the
role holds ``s3:ListBucket`` on the bucket, but as ``403 AccessDenied`` when it does
not (S3 hides existence). Both are treated as "absent → empty cache". This is safe
*because* the create path is conditional: if a present-but-unreadable object were ever
misread as absent, the ``If-None-Match: *`` create would fail with ``412`` and we'd
raise rather than overwrite real data.
"""

import json
import logging

import config
import clients

logger = logging.getLogger()

# Bounded CAS retries. Contention is rare (a single user in a few concurrent ops), so
# a small cap is plenty; exhausting it raises rather than silently dropping a write.
_MAX_CAS_ATTEMPTS = 6


def _key(username):
    return f"{username}/user_settings/shared-connections.json"


def _error_code(exc):
    return str((getattr(exc, "response", {}) or {}).get("Error", {}).get("Code", ""))


def _is_precondition(exc):
    """A conditional PutObject failed (If-Match/If-None-Match) — a concurrent writer."""
    return _error_code(exc) in ("PreconditionFailed", "412")


def _is_absent(exc):
    """A GetObject error that means "the object isn't there". ``NoSuchKey``/404 is the
    normal missing-object signal; ``403 AccessDenied`` is what S3 returns for a missing
    key when the caller lacks ``s3:ListBucket`` (see the module docstring — safe here
    because the create path is conditional)."""
    return _error_code(exc) in ("NoSuchKey", "NotFound", "404", "AccessDenied", "403")


def _read(username):
    """Return ``(connections, etag)`` for the user's cache. A missing object yields
    ``([], None)`` (etag None marks "create-if-absent" on the write back). Any S3 error
    other than absence propagates."""
    s3 = clients.s3()
    try:
        obj = s3.get_object(Bucket=config.USER_SPACE_BUCKET, Key=_key(username))
    except s3.exceptions.NoSuchKey:
        return [], None
    except s3.exceptions.ClientError as exc:
        if _is_absent(exc):
            logger.warning("cache read for %s treated as absent: %s", username, _error_code(exc))
            return [], None
        raise
    try:
        cache = json.loads(obj["Body"].read())
    except (TypeError, ValueError):
        cache = {}
    connections = cache.get("connections", []) if isinstance(cache, dict) else []
    return connections, obj.get("ETag")


def _write(username, connections, etag):
    """Write the user's cache conditionally: ``If-Match`` the read ETag (update) or
    ``If-None-Match: *`` when absent (create). Raises the S3 ClientError on a
    precondition failure so the CAS loop can retry."""
    kwargs = {
        "Bucket": config.USER_SPACE_BUCKET,
        "Key": _key(username),
        "Body": json.dumps({"version": 1, "connections": connections}).encode(),
        "ContentType": "application/json",
    }
    if etag is None:
        kwargs["IfNoneMatch"] = "*"
    else:
        kwargs["IfMatch"] = etag
    clients.s3().put_object(**kwargs)


def _mutate(username, fn):
    """Compare-and-swap the user's cache: read (+ETag), apply ``fn(connections) ->
    connections``, write conditionally; retry on a concurrent-writer precondition
    failure. A no-op change (``fn`` returns the list unchanged) skips the write so
    removing an absent entry stays a true no-op."""
    s3 = clients.s3()
    for attempt in range(_MAX_CAS_ATTEMPTS):
        connections, etag = _read(username)
        updated = fn(list(connections))
        if updated == connections:
            return  # nothing changed — don't write
        try:
            _write(username, updated, etag)
            return
        except s3.exceptions.ClientError as exc:
            if _is_precondition(exc) and attempt < _MAX_CAS_ATTEMPTS - 1:
                continue  # a concurrent writer won; re-read and reapply
            raise
    raise RuntimeError(f"cache CAS for {username} exhausted {_MAX_CAS_ATTEMPTS} attempts")


def upsert_entry(username, entry):
    """Compare-and-swap the user's cache, upserting ``entry`` by name."""

    def apply(connections):
        kept = [c for c in connections if c.get("name") != entry["name"]]
        kept.append(entry)
        return kept

    _mutate(username, apply)


def remove_entry(username, name):
    """Remove the user's cache entry for ``name`` (compare-and-swap; never an S3
    delete). Idempotent — a missing cache or absent entry is a no-op (no write)."""

    def apply(connections):
        return [c for c in connections if c.get("name") != name]

    _mutate(username, apply)


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
