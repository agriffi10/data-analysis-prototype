"""Per-user membership index in the admin bucket — the projection that answers "which spaces".

The registry is one object per space, keyed by space name, so *which spaces is this user in* costs
a full listing plus a read per space. This module writes the object that answers it in one
``GetObject``: one document per user, listing the spaces they belong to, written at the moments
membership changes.

**It shares neither the roster fan-out's posture nor its position.** A per-member cache failure is
logged and skipped, because a stale roster is cosmetic — one member sees an out-of-date member
list. A stale index is an **authorization input that is wrong**, and on a removal it is wrong in
the granting direction. So every failure here raises, and the plane's per-verb catcher turns that
into a failed run with a notification. An implementer reusing the fan-out must not inherit its
``except: log and continue``.

**A GRANT is written before the registry commit; a REVOCATION after it.** This module used to
write where the fan-out does, after the commit, on the reasoning that the commit is what makes a
membership real. For a revocation that still holds and is what every ``drop`` caller does. For a
grant it was wrong, and measurably: a delete emptying the space between an add's commit and its
entry here revoked the member and the add then re-created the entry, ``status`` and all, over a
record with no owner and a blank roster — and an emptied record deliberately keeps ``status``
active, so the API's index source reads it as a live space. Written before the commit instead,
the ordering decides it: a delete landing after the commit sees the member in the record
``empty_space`` returns and revokes them, and one landing before it makes the commit refuse, so
the granting verb takes the entry back itself — which is why ``add-members`` owns a rollback for
what it wrote here. **``create-space`` is the one grant that cannot take this ordering**, and the
reason is in its own docstring: the record reads ``provisioning`` until ``finalize``, so an entry
written before the commit would name a space no session may reach yet. Its write therefore stays
after, and what that costs is recorded in the register rather than papered over.

**Absence is an answer and a denial is not.** ``cache.py`` treats ``AccessDenied`` as absence, which
is safe there only because its create is conditional. Here the same tolerance would let a
present-but-unreadable index read as "member of nothing" and be overwritten with it, so only the
real absence codes take the absent branch. The role holds a ``ListBucket`` on the admin bucket
conditioned to this prefix, which is what makes S3 answer ``NoSuchKey`` rather than a denial.

**Nothing is ever deleted.** A user who leaves their last space holds an index with an empty space
list. A deleted document and a user who was never a member are indistinguishable, and one of those
two states is reached by a code path that is allowed to fail.

Attributes:
  SCHEMA_VERSION: The document's schema version, refused rather than migrated by a reader that
    does not recognise it.
  KEY_PREFIX: The admin-bucket prefix every index object sits under. It is also the prefix both
    roles' IAM conditions name, so a change here is a change in two policy templates.
  REASON_WRITE_FAILED: The stable token recorded when a write fails. A fixed literal, so a query
    counting them cannot be defeated by an interpolated space name.
"""

import json
from typing import Any

import casio
import registry as reg
from cpcommon import clients, observability
from cpcommon import config as cpconfig

SCHEMA_VERSION = 1
KEY_PREFIX = "memberships/"

REASON_WRITE_FAILED = "membership-index-write-failed"

_ABSENT_CODES = ("NoSuchKey", "NotFound", "404")


class MembershipIndexUnreadable(Exception):
    """A stored index does not parse, or carries a shape this schema does not recognise.

    Its own type rather than a ``ValueError`` because the distinction is the point: an
    unreadable index is NOT evidence that the caller is a member of nothing. Absence is an
    answer and this is not, so the two must never take the same branch.
    """


def _key(username: str) -> str:
    """Builds the S3 key of one user's membership index.

    Args:
      username: The index owner.

    Returns:
      The object key under the admin bucket.

    Raises:
      None.
    """
    return f"{KEY_PREFIX}{username}.json"


def _is_absent(exc: BaseException) -> bool:
    """Reports whether a read error means the index is not there.

    A denial is deliberately NOT absence. The read runs under a role holding a list grant
    conditioned to this prefix, so S3 answers a missing key with a missing-key code; a denial
    means something else is wrong, and treating it as "member of nothing" would overwrite a real
    index with an empty one.

    Args:
      exc: The read fault.

    Returns:
      True when the object should be treated as absent.

    Raises:
      None.
    """
    return casio.error_code(exc) in _ABSENT_CODES


def _read(username: str) -> tuple[list[dict[str, str]], str | None]:
    """Reads a user's index and its entity tag.

    Args:
      username: The index owner.

    Returns:
      A ``(spaces, etag)`` tuple. A missing object yields an empty list and no tag, which marks
      create-if-absent on the write back.

    Raises:
      ClientError: On any S3 error other than absence, including a denial.
      MembershipIndexUnreadable: If the document does not parse, or carries a version or a shape
        this schema does not know.
    """
    s3 = clients.s3()
    try:
        obj = s3.get_object(Bucket=cpconfig.ADMIN_BUCKET, Key=_key(username))
    except s3.exceptions.NoSuchKey:
        return [], None
    except s3.exceptions.ClientError as exc:
        if _is_absent(exc):
            return [], None
        raise
    try:
        document = json.loads(obj["Body"].read())
    except ValueError as exc:
        raise MembershipIndexUnreadable(f"membership index for {username} does not parse") from exc
    if not isinstance(document, dict) or document.get("version") != SCHEMA_VERSION:
        raise MembershipIndexUnreadable(
            f"membership index for {username} carries an unknown schema"
        )
    spaces = document.get("spaces")
    if not isinstance(spaces, list):
        raise MembershipIndexUnreadable(
            f"membership index for {username} carries no space list"
        )
    return spaces, obj.get("ETag")


def _write(username: str, spaces: list[dict[str, str]], etag: str | None) -> None:
    """Writes a user's index conditionally on the tag it was read at.

    Args:
      username: The index owner.
      spaces: The full space list to write.
      etag: The tag to match, or None to write only if the object is absent.

    Returns:
      None.

    Raises:
      ClientError: On a precondition failure, so the CAS loop can retry, or any other S3 fault.
    """
    body = {
        "version": SCHEMA_VERSION,
        "username": username,
        "spaces": spaces,
        "updatedAt": reg.now_iso(),
    }
    kwargs: dict[str, Any] = {
        "Bucket": cpconfig.ADMIN_BUCKET,
        "Key": _key(username),
        "Body": json.dumps(body).encode(),
        "ContentType": "application/json",
    }
    if etag is None:
        kwargs["IfNoneMatch"] = "*"
    else:
        kwargs["IfMatch"] = etag
    clients.s3().put_object(**kwargs)


def _mutate(username: str, fn: Any) -> None:
    """Compare-and-swaps a user's index through a transform.

    A no-op change skips the write, so dropping a space the index does not name stays a true
    no-op rather than a write that bumps the timestamp.

    Args:
      username: The index owner.
      fn: Takes the current space list and returns the new one.

    Returns:
      None.

    Raises:
      CasExhausted: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
      MembershipIndexUnreadable: If the stored document is unreadable.
    """
    casio.cas_mutate(
        read=lambda: _read(username),
        apply=lambda spaces: fn(list(spaces)),
        write=lambda spaces, etag: _write(username, spaces, etag),
        label=f"membership-index/{username}",
    )


def record(username: str, space: str, status: str) -> None:
    """Records that a user belongs to a space, replacing any entry of the same name.

    Args:
      username: The member.
      space: The space name.
      status: The space's status, from the record the caller is committing against. Only an active
        space yields a session tag, so the status is carried rather than assumed.

    Returns:
      None.

    Raises:
      CasExhausted: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
      MembershipIndexUnreadable: If the stored document is unreadable.
    """

    def apply(spaces: list[dict[str, str]]) -> list[dict[str, str]]:
        """Replaces any same-named entry and appends the new one.

        Args:
          spaces: The current list.

        Returns:
          The updated list.

        Raises:
          None.
        """
        kept = [entry for entry in spaces if entry.get("name") != space]
        kept.append({"name": space, "status": status})
        return kept

    _guarded(username, space, "record", apply)


def drop(username: str, space: str) -> None:
    """Removes a user's entry for one space. Idempotent, and never an S3 delete.

    Args:
      username: The member.
      space: The space name to remove.

    Returns:
      None.

    Raises:
      CasExhausted: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
      MembershipIndexUnreadable: If the stored document is unreadable.
    """

    def apply(spaces: list[dict[str, str]]) -> list[dict[str, str]]:
        """Drops any entry naming the space.

        Args:
          spaces: The current list.

        Returns:
          The filtered list.

        Raises:
          None.
        """
        return [entry for entry in spaces if entry.get("name") != space]

    _guarded(username, space, "drop", apply)


def record_for_all(members: list[str], space: str, status: str) -> None:
    """Records one space against every named member, stopping at the first failure.

    Args:
      members: The members to record it against.
      space: The space name.
      status: The space's status from the record the caller is committing against.

    Returns:
      None.

    Raises:
      CasExhausted: When a member's CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
      MembershipIndexUnreadable: If a stored document is unreadable.
    """
    for member in members:
        record(member, space, status)
    _fanned_out(members, space, "record")


def drop_for_all(members: list[str], space: str) -> None:
    """Removes one space from every named member's index, stopping at the first failure.

    Args:
      members: The members to remove it from.
      space: The space name.

    Returns:
      None.

    Raises:
      CasExhausted: When a member's CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
      MembershipIndexUnreadable: If a stored document is unreadable.
    """
    for member in members:
        drop(member, space)
    _fanned_out(members, space, "drop")


def _guarded(username: str, space: str, action: str, apply: Any) -> None:
    """Performs one member's index write, recording the failure before letting it rise.

    **Every write goes through here, single or fanned out**, because the record is what says
    *which* member's index is wrong — and that is the whole question when a session's tags
    disagree with a roster. The notifier downstream is given the execution's error and never the
    member.

    Args:
      username: The member whose index is written.
      space: The space name, for the record.
      action: Which write it is, for the record.
      apply: Takes the current space list and returns the new one.

    Returns:
      None.

    Raises:
      Exception: Whatever the write raised, after recording it. Never swallowed: the roster
        fan-out beside this one is best-effort because a stale roster is cosmetic, and a stale
        index is an authorization input that is wrong — on a removal, in the granting direction.
    """
    try:
        _mutate(username, apply)
    except Exception:
        observability.error(
            "membership index write failed",
            space=space,
            member=username,
            action=action,
            store="membership-index",
            reason=REASON_WRITE_FAILED,
        )
        raise


def _fanned_out(members: list[str], space: str, action: str) -> None:
    """Records that a whole fan-out landed.

    Emitted only once every member's write has committed, so the count in the record is a count
    of writes that happened rather than of writes that were attempted.

    Args:
      members: The members written.
      space: The space name.
      action: Which write it was.

    Returns:
      None.

    Raises:
      None.
    """
    observability.info(
        "membership index written",
        space=space,
        action=action,
        store="membership-index",
        written=len(members),
    )
