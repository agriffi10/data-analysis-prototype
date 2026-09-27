"""Per-user shared-connections cache in the user-space bucket.

The cache is the UI projection of a user's spaces — the registry is the source of truth and the
browser only reads this. The privileged orchestrator role may write any user's prefix. Every
write is a read-modify-write, never an S3 delete.

Concurrent executions can touch the same user's cache, because the Pipe starts the state
machine fire-and-forget and serial intake is not serial execution, so a plain read-then-write
would lose updates. Every mutation is therefore an optimistic compare-and-swap through the
shared primitive.
"""

import json
import logging

import casio
from cpcommon import clients, observability
from cpcommon import config as cpconfig

logger = logging.getLogger()


def _key(username):
    """Builds the S3 key of one user's cache object.

    Args:
      username: The cache owner.

    Returns:
      The object key under their own prefix.

    Raises:
      None.
    """
    return f"{username}/user_settings/shared-connections.json"


def _is_absent(exc):
    """Reports whether a read error means the object is not there.

    A missing-key code is the normal signal; S3 also returns a denial for a missing key when the
    caller lacks list permission. Treating the denial as absent is safe only because the create
    path is conditional: a present-but-unreadable object misread as absent makes the create-only
    write fail on its precondition rather than overwrite real data. The registry deliberately
    does not treat a denial as absent, because its role does hold list permission for the keys it
    reads — unconditioned on this bucket, and conditioned to ``shared-spaces/*`` on the admin one.
    This tolerance is belt-and-braces rather than the thing making the cache work.

    Args:
      exc: The read fault.

    Returns:
      True when the object should be treated as absent.

    Raises:
      None.
    """
    return casio.error_code(exc) in ("NoSuchKey", "NotFound", "404", "AccessDenied", "403")


def _read(username):
    """Reads a user's cache and its entity tag.

    Args:
      username: The cache owner.

    Returns:
      A ``(connections, etag)`` tuple. A missing object yields an empty list and no tag, which
      marks create-if-absent on the write back.

    Raises:
      ClientError: On any S3 error other than absence.
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
    """Writes a user's cache conditionally on the tag it was read at.

    Args:
      username: The cache owner.
      connections: The full connection list to write.
      etag: The tag to match, or None to write only if the object is absent.

    Returns:
      None.

    Raises:
      ClientError: On a precondition failure, so the CAS loop can retry, or any other S3 fault.
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
    """Compare-and-swaps a user's cache through a transform.

    A no-op change skips the write, so removing an absent entry stays a true no-op.

    Args:
      username: The cache owner.
      fn: Takes the current connections and returns the new list.

    Returns:
      None.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """
    casio.cas_mutate(
        read=lambda: _read(username),
        apply=lambda connections: fn(list(connections)),
        write=lambda connections, etag: _write(username, connections, etag),
        label=f"cache/{username}",
    )


def upsert_entry(username: str, entry: dict) -> None:
    """Inserts or replaces one connection entry in a user's cache, by name.

    Args:
      username: The cache owner.
      entry: The entry to write, keyed by its name.

    Returns:
      None.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """

    def apply(connections):
        """Replaces any same-named entry and appends the new one.

        Args:
          connections: The current list.

        Returns:
          The updated list.

        Raises:
          None.
        """
        kept = [c for c in connections if c.get("name") != entry["name"]]
        kept.append(entry)
        return kept

    _mutate(username, apply)


def remove_entry(username: str, name: str) -> None:
    """Removes a user's cache entry for one space. Never an S3 delete.

    Idempotent — a missing cache or absent entry writes nothing.

    Args:
      username: The cache owner.
      name: The space name to remove.

    Returns:
      None.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """

    def apply(connections):
        """Drops any entry with the given name.

        Args:
          connections: The current list.

        Returns:
          The filtered list.

        Raises:
          None.
        """
        return [c for c in connections if c.get("name") != name]

    _mutate(username, apply)


def _is_create_card(entry: dict) -> bool:
    """Reports whether a cache entry is a create's own card rather than a space the user holds.

    A create's card is the provisioning seed or a failed create. Anything else under the name — a
    space the user owns or belongs to, or one being deleted — is a space the create never made.

    Args:
      entry: One connection entry.

    Returns:
      True for a provisioning entry or a failed create.

    Raises:
      None.
    """
    status = entry.get("status")
    return status == "provisioning" or (status == "failed" and entry.get("failedAction") == "create")


def upsert_create_card(owner: str, entry: dict) -> bool:
    """Writes a create's card by name, unless the user's list already holds a space by that name.

    A create of a name the user already owns or belongs to is refused by the reservation, and
    that refusal says nothing about the entry already there. Replacing it by name turned a
    working space's card into a failed create that Retry collides on again and Dismiss cannot
    forget, so the held entry is left as it is and the notification carries the refusal.

    Args:
      owner: The creator.
      entry: The create's card, keyed by its name.

    Returns:
      True when the card was written, False when a held entry was left in place.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """
    held = False

    def apply(connections):
        """Replaces a same-named create card, or returns the list unchanged over a held entry.

        Args:
          connections: The current list.

        Returns:
          The updated list, or the same list when the name is held.

        Raises:
          None.
        """
        nonlocal held
        current = next((c for c in connections if c.get("name") == entry["name"]), None)
        held = current is not None and not _is_create_card(current)
        if held:
            return connections
        return [c for c in connections if c.get("name") != entry["name"]] + [entry]

    _mutate(owner, apply)
    return not held


def write_owner_pending(owner: str, name: str) -> bool:
    """Seeds the creator's cache with a provisioning entry when a create is accepted.

    Written before any provisioning work, so the space survives a browser reload even if
    provisioning later fails — an unrecorded create vanishes from the UI. Superseded by the
    active projection or a failed upsert, both of which replace this entry by name. The creation
    date and roster are intentionally omitted and supplied by the authoritative active write.
    Not written over a space already on the creator's list, for the reason ``upsert_create_card``
    gives.

    Args:
      owner: The creator.
      name: The space name.

    Returns:
      True when the entry was written, False when the name was already held.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """
    return upsert_create_card(owner, {"name": name, "role": "owner", "status": "provisioning"})


def write_owner_deleting(owner: str, name: str) -> bool:
    """Marks the owner's cache entry as deleting once a delete is accepted.

    Written after verification so the card shows a durable deleting state instead of reconciling
    back to active mid-cascade. Superseded by the entry's removal on success or a failed upsert
    on error.

    It names the verb it belongs to, because the screen offers a retry on a card stuck in this
    state and a card that does not say which verb it came from is retried as a create — the one
    verb that cannot work on a name already taken.

    Args:
      owner: The space's owner.
      name: The space name.

    Returns:
      True, since a delete's card always replaces the entry — the returned value matches the
      create's seed, which the validator records as whether the intent was written.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """
    upsert_entry(owner, {"name": name, "role": "owner", "status": "deleting", "failedAction": "delete"})
    return True


def _member_projection(members, owner, acknowledged):
    """Builds the roster projection carrying each member's join status.

    A member is active once they have acknowledged the space, or if they are the owner, who is
    always active; otherwise they are pending — invited but not yet signed in to pick it up.

    Args:
      members: The current member names.
      owner: The space's owner.
      acknowledged: The members who have acknowledged.

    Returns:
      A list of ``{username, status}`` dicts.

    Raises:
      None.
    """
    ack = set(acknowledged or [])
    return [
        {"username": m, "status": "active" if (m == owner or m in ack) else "pending"}
        for m in members
    ]


def write_owner_projection(
    owner: str, name: str, members: list[str], acknowledged: list[str], created_at: str | None = None
) -> None:
    """Updates the owner's cache entry with the current roster and join statuses.

    Args:
      owner: The space's owner.
      name: The space name.
      members: The current member names.
      acknowledged: The members who have acknowledged.
      created_at: The creation date, when known, so the connections card can render its meta
        line.

    Returns:
      None.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
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
    """Writes one member's cache entry for a space they belong to.

    A member's entry carries the same roster the owner sees, reversing the earlier
    member-privacy stance, plus the owner's name and the creation date. The read-only roster
    view renders it; members get no add or remove power.

    Args:
      member: The member whose cache is written.
      name: The space name.
      owner: The space's owner.
      members: The current member names.
      acknowledged: The members who have acknowledged.
      created_at: The creation date, when known.

    Returns:
      None.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
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


@observability.step("write-roster")
def write_roster_to_all(
    members: list[str], name: str, owner: str, acknowledged: list[str], created_at: str | None = None
) -> None:
    """Fans the current roster out to the owner and every member's cache.

    **Call bound: at most once per invocation**, in each of the five verbs that reach it — add,
    remove, leave, transfer-ownership and acknowledge-membership — two of which reach it inside
    a conditional. The span goes around the WHOLE fan-out rather than around each member's
    write: the shared layer offers this plane no bounded function to step, so the loop is the
    call site and its body is what must stay uninstrumented.

    Called by add, remove and leave after the registry write, which is the consistency point, so
    each remaining member's cache reflects the same roster the owner sees. Per-member writes are
    best-effort: one member's cache failing is logged and skipped rather than aborting the rest
    of the fan-out, because the registry mutation already committed. What that costs is one
    member seeing a stale roster while everyone else sees the current one — invisible from either
    side, which is why it is named in the record. The owner projection is written last,
    preserving the verbs' prior end state.

    Per-member events are acceptable here, a deliberate exception to the per-item prohibition
    elsewhere. The bound is structural rather than a hope: membership is capped by the Cognito
    attribute slot model, so a fan-out can emit at most that many events. The sweep's
    prohibition exists because its per-message count is unbounded and it emits into the queue it
    drains; neither is true here.

    **An ownerless roster writes nothing at all.** Every caller reaches this after its registry
    compare-and-swap, and passes the owner that commit carries; a space a concurrent delete has
    emptied carries none, because the emptying rewrite clears the field. Fanning out anyway would
    re-create a card for a space that is gone, on the screen the delete has just cleared, and
    write the owner projection under a falsy key. The verb is past its consistency point by this
    point, so the skip is recorded rather than raised.

    Args:
      members: The current member names.
      name: The space name.
      owner: The space's owner, as the committed record carries it rather than as the request was
        authorized against it. A transfer landing between the two would otherwise fan the roster
        out naming the FORMER owner, and every member's card would show the space as still theirs.
      acknowledged: The members who have acknowledged.
      created_at: The creation date, when known.

    Returns:
      None.

    Raises:
      RuntimeError: When the owner projection's CAS attempts are exhausted.
      ClientError: On a non-precondition S3 fault writing the owner projection.
    """
    if not owner:
        observability.info(
            "roster fan-out skipped: the committed record has no owner",
            space=name,
            store="cache",
            written=0,
        )
        return
    written, failed = [], []
    for member in members:
        if member == owner:
            continue
        try:
            write_member_entry(member, name, owner, members, acknowledged, created_at)
            written.append(member)
        except Exception:
            logger.exception("roster fan-out to %s for %s failed (best-effort)", member, name)
            failed.append(member)
            observability.warning(
                "roster fan-out failed for one member", space=name, member=member, store="cache"
            )
    write_owner_projection(owner, name, members, acknowledged, created_at)
    observability.info(
        "roster fanned out",
        space=name,
        actor=owner,
        store="cache",
        written=len(written),
        failed=len(failed),
        stale_members=failed,
    )
