"""Per-user shared-connections cache in the user-space bucket.

The cache at ``{username}/user_settings/shared-connections.json`` is the UI projection
of a user's spaces (the registry is the source of truth; the browser only reads this).
The privileged orchestrator role may write any user's prefix. Every write is a
read-modify-write, never an S3 delete.

Concurrent control-plane executions can touch the same user's cache (the Pipe starts
the Standard state machine fire-and-forget, so serial intake is not serial execution),
and a plain read-then-write would lose updates. Every mutation is therefore an
optimistic compare-and-swap: read the object and its ETag, modify, then ``PutObject``
conditioned on that ETag (``If-Match``) or on absence (``If-None-Match: *``); a 412
means a concurrent writer won, so re-read and retry.
"""

import json
import logging

from cpcommon import observability, config as cpconfig
from cpcommon import clients
import casio

logger = logging.getLogger()


def _key(username):
    return f"{username}/user_settings/shared-connections.json"


def _is_absent(exc):
    """True when a GetObject error means the object isn't there.

    ``NoSuchKey``/404 is the normal missing-object signal; S3 returns ``403
    AccessDenied`` for a missing key when the caller lacks ``s3:ListBucket``. Treating
    403 as absent is safe only because the create path is conditional: a
    present-but-unreadable object misread as absent would make the ``If-None-Match: *``
    create fail with 412 rather than overwrite real data. (The registry deliberately
    does NOT treat 403 as absent — its admin-bucket role has ``s3:ListBucket``.)
    """
    return casio.error_code(exc) in ("NoSuchKey", "NotFound", "404", "AccessDenied", "403")


def _read(username):
    """Return ``(connections, etag)`` for the user's cache.

    A missing object yields ``([], None)``; etag None marks create-if-absent on the
    write back. Any S3 error other than absence propagates.
    """
    s3 = clients.s3()
    try:
        obj = s3.get_object(Bucket=cpconfig.USER_SPACE_BUCKET, Key=_key(username))
    except s3.exceptions.NoSuchKey:
        return [], None
    except s3.exceptions.ClientError as exc:
        if _is_absent(exc):
            logger.warning("cache read for %s treated as absent: %s", username, casio.error_code(exc))
            return [], None
        raise
    try:
        cache = json.loads(obj["Body"].read())
    except (TypeError, ValueError):
        cache = {}
    connections = cache.get("connections", []) if isinstance(cache, dict) else []
    return connections, obj.get("ETag")


def _write(username, connections, etag):
    """Write the user's cache conditionally.

    ``If-Match`` the read ETag (update) or ``If-None-Match: *`` when absent (create).
    Raises the S3 ClientError on a precondition failure so the CAS loop can retry.
    """
    kwargs = {
        "Bucket": cpconfig.USER_SPACE_BUCKET,
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
    """Compare-and-swap the user's cache through ``fn(connections) -> connections``.

    Read (+ETag), apply ``fn``, write conditionally; retry on a concurrent-writer
    precondition failure. A no-op change skips the write so removing an absent entry
    stays a true no-op. The CAS loop is the shared ``casio`` primitive (SPEC-082).
    """
    casio.cas_mutate(
        read=lambda: _read(username),
        apply=lambda connections: fn(list(connections)),
        write=lambda connections, etag: _write(username, connections, etag),
        label=f"cache/{username}",
    )


def upsert_entry(username: str, entry: dict) -> None:
    """Compare-and-swap the user's cache, upserting ``entry`` by name."""

    def apply(connections):
        kept = [c for c in connections if c.get("name") != entry["name"]]
        kept.append(entry)
        return kept

    _mutate(username, apply)


def remove_entry(username: str, name: str) -> None:
    """Remove the user's cache entry for ``name`` (compare-and-swap; never an S3 delete).

    Idempotent — a missing cache or absent entry is a no-op (no write).
    """

    def apply(connections):
        return [c for c in connections if c.get("name") != name]

    _mutate(username, apply)


def write_owner_pending(owner: str, name: str) -> None:
    """Seed the creator's cache with a ``provisioning`` owner entry on create-accept.

    Written before any provisioning work so the space survives a browser reload even
    if provisioning later fails (an unrecorded create vanishes from the UI).
    Superseded by ``write_owner_projection`` (``active``) or a ``failed`` upsert, both
    of which replace this entry by name; ``createdAt``/``members`` are intentionally
    omitted and supplied by the authoritative ``active`` write.
    """
    upsert_entry(owner, {"name": name, "role": "owner", "status": "provisioning"})


def write_owner_deleting(owner: str, name: str) -> None:
    """Mark the owner's cache entry ``deleting`` once a delete is accepted.

    Written after verification so the card shows a durable "Deleting…" state instead
    of reconciling back to ``active`` mid-cascade. Superseded by the entry's removal
    on success or a ``failed`` upsert on error.
    """
    upsert_entry(owner, {"name": name, "role": "owner", "status": "deleting"})


def _member_projection(members, owner, acknowledged):
    """Build the ``[{username, status}]`` projection (SPEC-073).

    A member is ``active`` once they've acknowledged the space (or they're the owner,
    always active); otherwise ``pending`` — invited but not yet signed in to pick it up.
    """
    ack = set(acknowledged or [])
    return [
        {"username": m, "status": "active" if (m == owner or m in ack) else "pending"}
        for m in members
    ]


def write_owner_projection(
    owner: str, name: str, members: list[str], acknowledged: list[str], created_at: str | None = None
) -> None:
    """Update the owner's cache entry with the current member roster + join status.

    This is the owner-readable projection the Manage drawer renders; members never see
    this list. Members are stored as ``{username, status}`` (SPEC-073) where status is
    derived from ``acknowledged``. ``created_at`` (when known) is carried so the
    Connections card can render its "created <date>" meta line.
    """
    entry = {
        "name": name,
        "role": "owner",
        "status": "active",
        "members": _member_projection(members, owner, acknowledged),
    }
    if created_at:
        entry["createdAt"] = created_at
    upsert_entry(owner, entry)


def write_member_entry(
    member: str, name: str, owner: str, members: list[str], acknowledged: list[str], created_at: str | None = None
) -> None:
    """Write a member's cache entry for a space they belong to.

    As of SPEC-075 a member's entry carries the same ``{username, status}`` roster the
    owner sees (SPEC-053's member-privacy stance is reversed), plus the ``owner`` name
    and ``createdAt`` for the Connections card. The read-only roster view renders it;
    members get no add/remove power.
    """
    entry = {
        "name": name,
        "role": "member",
        "status": "active",
        "owner": owner,
        "members": _member_projection(members, owner, acknowledged),
    }
    if created_at:
        entry["createdAt"] = created_at
    upsert_entry(member, entry)


def write_roster_to_all(
    members: list[str], name: str, owner: str, acknowledged: list[str], created_at: str | None = None
) -> None:
    """Fan the current roster out to the owner + every member's cache (SPEC-075).

    Called by add/remove/leave *after* the registry write (the consistency point) so
    each remaining member's cache reflects the same roster the owner sees. Per-member
    writes are best-effort: one member's cache failing is logged and skipped rather than
    aborting the rest of the fan-out (the registry mutation already committed). The
    owner projection is written last, preserving the verbs' prior end state.
    """
    written, failed = [], []
    for member in members:
        if member == owner:
            continue
        try:
            write_member_entry(member, name, owner, members, acknowledged, created_at)
            written.append(member)
        except Exception:  # best-effort fan-out — never abort the others on one failure
            logger.exception("roster fan-out to %s for %s failed (best-effort)", member, name)
            failed.append(member)
            # WARNING, not error: the fan-out continues and the registry mutation already
            # committed. What it costs is one member seeing a stale roster while everyone else
            # sees the current one — invisible from either side, which is why it is named.
            observability.warning(
                "roster fan-out failed for one member", space=name, member=member, store="cache"
            )
    write_owner_projection(owner, name, members, acknowledged, created_at)
    # PER-MEMBER EVENTS ARE ACCEPTABLE HERE, and this is a deliberate exception to the
    # per-item prohibition in SPEC-131 FR-005 and the per-file caution in SPEC-132 FR-002.
    # The bound is STRUCTURAL, not a hope: membership is capped at ten by the Cognito
    # attribute slot model (membership.MAX_SHARED_MEMBERSHIPS), so a fan-out can emit at most
    # ten events. The sweep's prohibition exists because its per-message count is unbounded
    # AND it emits into the queue it drains; neither is true here.
    observability.info(
        "roster fanned out",
        space=name,
        actor=owner,
        store="cache",
        written=len(written),
        failed=len(failed),
        stale_members=failed,
    )
