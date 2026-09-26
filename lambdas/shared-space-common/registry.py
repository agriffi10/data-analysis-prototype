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


class MembershipRefused(Exception):
    """A membership addition the freshly-read record forbids. Terminal.

    Raised from inside the compare-and-swap transform, which is the only place holding a record
    fresh enough to decide: a gate at the verb or in the authorizer reads the copy the validator
    loaded and inherits the staleness it exists to prevent.

    The base of three, so a caller can roll back its slots by catching one type while the
    notification still names the situation. The reason code the failure notifier resolves is the
    RAISED class's name, so the subclasses stay distinguishable to a user; collapsing them would
    give two quite different situations one sentence.

    Only additions are refused. Removing and acknowledging are exempt — both only shrink or
    annotate a roster, and refusing them would strand a member who slipped through.
    """


class SpaceHasNoOwner(MembershipRefused):
    """The space has been emptied: its roster is blank and its owner field is gone."""


class SpaceNeverActive(MembershipRefused):
    """The space never finished provisioning, so it is still destroyable."""


class SpaceAlreadyEmptied(MembershipRefused):
    """The space carries an emptied stamp, so its members were deliberately revoked."""


class OwnerChanged(MembershipRefused):
    """The space changed hands between authorization and the write. Terminal.

    A transfer is authorization-carrying in a way a status write is not, which is why this
    exists and ``set_status`` needs no equivalent. Alice is authorized while she owns the space;
    a concurrent transfer moves it to carol; alice's compare-and-swap re-reads the fresh record
    and would re-apply her change to it, taking the space away from carol. That is a lost
    authorization wearing the shape of a correct retry, and only a check inside the transform
    can see it.
    """


class TransferTargetNoLongerMember(MembershipRefused):
    """The member a transfer names left the roster between authorization and the write. Terminal.

    The mirror of ``OwnerChanged``, on the other half of the same decision. The validator refuses
    a target who is not a member, from the record it loaded; a concurrent removal between that
    read and the write leaves the check passed and the fact false. An owner reaches a space by
    being its owner rather than by appearing on its roster, so completing the transfer hands
    someone live access the roster has just denied them — which is why this refuses rather than
    re-adding them, a repair no one authorized.
    """


class RegistryRecordMissing(Exception):
    """A verb's fresh read found no record where one is required. Terminal.

    Refusing beats proceeding: the record is the only evidence of what a space was, and tearing
    down a prefix and a database on its absence is the worst option available.
    """


class MembersRemainAfterEmpty(Exception):
    """An emptied space still lists members after every revocation pass. Terminal.

    Raised rather than looped, because additions are refused once the owner is gone, so a retry
    could not converge on anything the first pass did not already reach.
    """


class RegistryRecordResurrected(Exception):
    """A record reappeared after the delete that freed its name. Terminal.

    A membership write that lost its race to the delete re-creates the record from the caller's
    stale copy, leaving a name locked over resources that no longer exist.
    """


def is_destroyable(record: dict | None) -> bool:
    """Reports whether a space may be torn down rather than emptied.

    **One predicate with two consumers, and that is the whole point.** The delete route's test
    and the guard refusing additions are complements of each other; written twice they drift,
    and each drift is silent — one direction destroys a live workspace, the other freezes
    additions on a healthy one.

    A space is destroyable only while it has never been usable by anyone: no durable ever-active
    stamp, and not currently active either, the second covering a record written before the
    stamp existed. Such a space was reachable only by its creator, which is what licenses
    destroying it.

    Args:
      record: The freshly-read registry record, or None.

    Returns:
      True when the space may be destroyed.

    Raises:
      None.
    """
    if record is None:
        return False
    return not record.get("everActive") and record.get("status") != "active"


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

    Only a true-absent signal is treated as missing. The orchestrator's list grant on the admin
    bucket is conditioned to ``shared-spaces/*``, which covers exactly the keys read here, so S3
    reports a missing record as absent rather than as a denial — and unlike the cache a denial is
    therefore not read as absence. Any other fault propagates rather than risk overwriting real
    data. **A conditioned grant is sufficient for that; what would break this is holding no list
    statement on the bucket at all**, which is how the same read fails on planes that only reach
    the registry through ``cpcommon``.

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

    **That overwrite is refused on a space that was ever usable**, and the distinction is the
    difference between a retry and a revival. A failed CREATE is the owner's own dead
    reservation and re-provisioning it is what the path exists for. A failed DELETE looks
    identical — same owner, same failed status — but its files are intact and its previous
    cohort's are underneath; re-provisioning that resets the roster to the owner alone and hands
    them back a populated workspace, in one call and with no confirmation. The durable
    ever-active stamp is what tells the two apart; live status cannot.

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
        if (
            existing.get("owner") == actor
            and existing.get("status") == "failed"
            and not existing.get("everActive")
        ):
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

    Stamps ``everActive`` when — and only when — the outcome is active, because that field is
    what decides whether a later delete empties the space or destroys it. This function is
    called on both create outcomes, so an unconditional stamp would mark every failed create
    ever-active, which would refuse its owner's legitimate retry and refuse to tear it down.
    An existing stamp is carried forward on both paths for the same reason the creation
    timestamp is: the record is rebuilt from a literal, so it is the one writer here that
    provably drops a field it does not name.

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
        """Builds the outcome record, carrying forward the creation timestamp and the stamp.

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
        if status == "active" or (existing or {}).get("everActive"):
            record["everActive"] = True
        return record

    casio.cas_mutate(
        read=lambda: _read(name),
        apply=apply,
        write=lambda record, etag: _put(name, record, etag),
        label=f"registry/{name}",
    )


def mark_ever_active(name: str, request_id: str) -> bool:
    """Stamps the durable ever-active fact on a record that does not carry it yet.

    The one writer of that field outside ``finalize``, shared by the delete verb and the
    one-shot backfill so the two cannot drift. The field is monotonic — written once, never
    cleared and never written false — because it is what decides whether a later delete empties
    a space or destroys it, and a status can move back and forth while that answer cannot.

    Compare-and-swap on the freshly-read record, and a no-op when the field is already there or
    the record is gone, so a re-run after a timeout costs nothing.

    Args:
      name: The space name.
      request_id: The run's request id.

    Returns:
      True when this call stamped the record, False when there was nothing to do.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """
    stamped = False

    def apply(existing):
        """Adds the field to the freshly-read record unless it is already present.

        Args:
          existing: The freshly-read record, or None.

        Returns:
          The record to write, unchanged when there is nothing to stamp.

        Raises:
          None.
        """
        nonlocal stamped
        stamped = False
        if existing is None or existing.get("everActive"):
            return existing
        stamped = True
        return {**existing, "everActive": True, "lastRequestId": request_id, "updatedAt": now_iso()}

    casio.cas_mutate(
        read=lambda: _read(name),
        apply=apply,
        write=lambda record, etag: _put(name, record, etag),
        label=f"registry/{name}",
    )
    return stamped


def effective_acknowledged(registry: dict) -> list[str]:
    """Returns the acknowledged-member usernames for a registry record.

    Membership stays a plain list of names; join status is tracked out of band as its own list
    of members who have signed in and picked up the space. A record written before that concept
    existed has no such field — its members predate it, so every one of them except the owner is
    treated as acknowledged (the owner is always active and is never listed here).

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


def save_members(
    registry: dict, request_id: str, *, add=(), remove=(), acknowledge=(), expected_owner=None
) -> dict:
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

    **``expected_owner`` re-checks the authorization, and only the GRANTING caller passes it.**
    The delta is derived from the fresh record, which keeps the roster whole, but nothing here
    asked whether the person who was allowed to change it still is: a transfer landing between
    the validator's read and this write leaves a former owner's addition to apply against the new
    owner's space. Refusing it is the same argument ``set_owner`` makes one field over. The
    removing and acknowledging callers pass nothing, deliberately — ``MembershipRefused`` exempts
    them because both only shrink or annotate a roster, and a late removal revokes rather than
    grants, so refusing one would strand a member who slipped through.

    Args:
      registry: The registry record, used for the space name and as the fallback base.
      request_id: The run's request id.
      add: Members to add.
      remove: Members to remove.
      acknowledge: Members promoting themselves from pending to active.
      expected_owner: The owner the request was authorized against, or None to apply the delta
        whatever the record now says. Passed by the adding caller only, and consulted only when
        the delta actually adds somebody.

    Returns:
      The committed record, so callers can fan the roster out from what actually landed. Fanning
      out from the caller's own list would re-introduce the same defect one layer down, and the
      cache would disagree with the registry.

    Raises:
      SpaceHasNoOwner: When an addition targets a space whose owner has been cleared.
      SpaceAlreadyEmptied: When an addition targets a space a delete has emptied.
      SpaceNeverActive: When an addition targets a space that is still destroyable.
      OwnerChanged: When an expected owner was given and the space has changed hands since.
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

        An acknowledgement is applied only if the member is still on the freshly-read roster.
        That membership test is the race the delta exists for, not belt-and-braces: without it,
        acknowledging a membership a concurrent remove just revoked would re-create it.

        The creation timestamp is defaulted to heal a record written before the field existed, so
        an older space's connections card does not show a permanently blank created date. That is
        a different default from the status one below, which heals a different missing field.

        Args:
          existing: The freshly-read record, or None.

        Returns:
          The record to write.

        Raises:
          SpaceHasNoOwner: When an addition targets a record whose owner field is gone.
          SpaceAlreadyEmptied: When an addition targets a record carrying an emptied stamp.
          SpaceNeverActive: When an addition targets a record that is still destroyable.
          OwnerChanged: When an addition was given an expected owner and the record names
            another. It sits INSIDE the addition branch and LAST within it, and both halves are
            load-bearing. Last, because an emptied record has no owner at all, so a check ahead
            of the three above would answer every delete race with "that space changed hands"
            in place of "that space has been deleted" — two quite different situations
            collapsed into the wrong one of the two sentences. Inside, because a delta that adds
            NOBODY grants nothing and so needs no re-authorization: checked outside, a request
            whose names were all already members, unknown or at their slot limit would turn an
            idempotent no-op into a refusal and lose the report naming them.
        """
        record = dict(existing) if existing is not None else dict(registry)
        if add:
            if not record.get("owner"):
                raise SpaceHasNoOwner(f"space {name!r} has no owner and cannot take new members")
            if record.get("emptiedAt"):
                raise SpaceAlreadyEmptied(f"space {name!r} was emptied and cannot take new members")
            if is_destroyable(record):
                raise SpaceNeverActive(f"space {name!r} is not provisioned and cannot take new members")
            if expected_owner is not None and record.get("owner") != expected_owner:
                raise OwnerChanged(
                    f"space {name!r} is owned by {record.get('owner')!r}, not {expected_owner!r}, "
                    "so the membership change is refused"
                )
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


def set_status(
    registry: dict, status: str, request_id: str, reason: str | None = None, expected_owner=None
) -> None:
    """Rewrites a space's status, preserving its owner, members and the rest.

    Compare-and-swap on the freshly-read record, so the status change is applied to current state
    and never regresses a value a concurrent writer just committed.

    **``expected_owner`` makes this the delete cascade's authorization re-check, because it is the
    cascade's FIRST write.** A status is not authorization-carrying and needs no such check on its
    own account; what it carries here is position. The delete verb checks its own fresh read
    before writing anything, and a transfer landing between that read and this write would leave
    the rest of the cascade running against somebody else's space — so the check goes on the write
    that opens it, where a refusal has destroyed nothing and written nothing.

    Args:
      registry: The registry record, used for the space name and as the fallback base.
      status: The new status — deleting before the cascade, or failed on a hard error.
      request_id: The run's request id.
      reason: The failure reason, when there is one. Absent, any existing reason is cleared.
      expected_owner: The owner the request was authorized against, or None to write the status
        whatever the record now says. An emptied record answers from ``previousOwner``.

    Returns:
      None.

    Raises:
      OwnerChanged: When an expected owner was given and the space has changed hands since.
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
          OwnerChanged: When an expected owner was given and the record names another.
        """
        record = dict(existing) if existing is not None else dict(registry)
        if expected_owner is not None:
            current = record.get("owner") or record.get("previousOwner")
            if current != expected_owner:
                raise OwnerChanged(
                    f"space {name!r} is owned by {current!r}, not {expected_owner!r}, "
                    "so the status change is refused"
                )
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


def set_owner(registry: dict, expected_owner: str, new_owner: str, request_id: str) -> dict:
    """Hands a space to another member under compare-and-swap, refusing if it already moved.

    Beside ``set_status`` and shaped like it, with two differences that are the whole of why it
    is a separate function.

    **It takes the expected current owner and re-checks it on the freshly-read record.**
    ``set_status`` may retry unconditionally because a status is not authorization-carrying. A
    transfer is: without the check, a retry that lands after a concurrent transfer re-applies a
    decision that was authorized against a record which no longer exists.

    **It re-checks the other half of that decision too — that the member named is still on the
    roster.** The validator refuses a target who is not a member, and a removal landing between
    that read and this write leaves the refusal passed and the fact false. Being the owner is
    itself the access, so the completed transfer would hand someone the space the roster had just
    removed them from.

    **It corrects ``acknowledged`` in the same write**, and that is not tidying. The cache's
    roster projection reads ``"active" if (m == owner or m in ack) else "pending"``, and the
    acknowledged list excludes the owner on the grounds that an owner is always active. So a
    write touching only ``owner`` would leave the outgoing owner in the roster, absent from the
    list, and rendering as *pending* to every member — someone who has used the space for months
    shown as not having picked it up yet. The list is materialised rather than left absent,
    because the fan-out reads the stored field and not this module's absence-tolerant reader: a
    legacy record that kept an absent field would fan out an empty list and show every member
    pending.

    Args:
      registry: The registry record, used for the space name and as the fallback base.
      expected_owner: The owner the request was authorized against.
      new_owner: The member taking the space, who must already be in the roster.
      request_id: The run's request id.

    Returns:
      The committed record.

    Raises:
      RegistryRecordMissing: When the record is gone. Without this the create-if-absent write
        would resurrect a deleted space under a new owner, and the expected-owner check would
        pass because it had read the caller's stale copy.
      SpaceAlreadyEmptied: When a delete emptied the space after the request was authorized.
      OwnerChanged: When the space changed hands after the request was authorized.
      TransferTargetNoLongerMember: When the member named has left the roster since the request
        was authorized.
      CasExhausted: When the attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """
    name = registry["name"]

    def apply(existing):
        """Rewrites the owner on the freshly-read record, refusing if it is no longer the one authorized.

        Args:
          existing: The freshly-read record, or None.

        Returns:
          The record to write.

        Raises:
          RegistryRecordMissing: When there is no record to rewrite.
          SpaceAlreadyEmptied: When the space carries an emptied stamp.
          OwnerChanged: When the current owner is not the expected one.
          TransferTargetNoLongerMember: When the new owner is not on the freshly-read roster. A
            roster that is not a list reads as empty and refuses, the same collapse
            ``membership.roster`` makes, which fails closed for a question phrased this way.
        """
        if existing is None:
            raise RegistryRecordMissing(f"space {name!r} has no registry record to transfer")
        record = dict(existing)
        if record.get("emptiedAt"):
            raise SpaceAlreadyEmptied(f"space {name!r} was emptied and cannot be transferred")
        current = record.get("owner")
        if current != expected_owner:
            raise OwnerChanged(
                f"space {name!r} is owned by {current!r}, not {expected_owner!r}, so the transfer is refused"
            )
        roster = record.get("members")
        members = list(roster) if isinstance(roster, list) else []
        if new_owner not in members:
            raise TransferTargetNoLongerMember(
                f"{new_owner!r} is no longer a member of space {name!r}, so the transfer is refused"
            )
        ack = [a for a in effective_acknowledged(record) if a != new_owner]
        if expected_owner in members and expected_owner not in ack:
            ack.append(expected_owner)
        record["owner"] = new_owner
        record["acknowledged"] = ack
        record["lastRequestId"] = request_id
        record["updatedAt"] = now_iso()
        return record

    return casio.cas_mutate(
        read=lambda: _read(name),
        apply=apply,
        write=lambda record, etag: _put(name, record, etag),
        label=f"registry/{name}",
    )


def empty_space(name: str, request_id: str) -> tuple[dict, dict]:
    """Rewrites a space as emptied, and hands back the record it replaced.

    The delete route's consistency point. Everything the space owns survives — the objects, the
    database, the record itself — and what ends is the membership: a blank roster, no owner, and
    a stamp saying when. The status stays active, because nothing about the space's resources
    changed and no reader may infer membership from status.

    **The replaced record is captured out of the transform rather than read beforehand.** A
    pre-read is a different record under a race, and it would pass every test that does not
    actually race; the capture is reset at the top of the transform because that transform runs
    once per attempt, so a value surviving a losing attempt would be stale. The caller needs it:
    a member added between the verb's own read and this write appears only there, and their slot
    is a live grant nobody would otherwise clear.

    **Built from the freshly-read record, never from a literal**, so fields this function does
    not name — the creation timestamp, the ever-active stamp, the schema version — survive.

    A replay normalises rather than skipping. Skipping looks tempting and is wrong: the verb has
    already written a deleting status by this point, so a skipped write leaves a completed delete
    reading as one that never finished. The two fields a replay must not disturb are preserved
    explicitly instead — the original owner, and the moment the space was emptied.

    **It takes NO expected owner, and that is a decision rather than an omission.** The delete's
    first write carries that check, so a transfer landing before the cascade starts is already
    refused with nothing written and nobody revoked. One landing after it — during the revocation
    loop — could only be caught HERE, and a refusal here arrives with every member's grant
    already gone, the new owner's included, and an owner's slot is one no ordinary verb can
    re-issue. Three reviews in a row found a different hole in the repair that would have made
    that refusal safe: it re-granted the owner a MEMBER card, it could re-grant over a delete the
    new owner had meanwhile started, and it swallowed the one failure that matters. Emptying the
    space is a state this system knows how to recover — the objects, the database and the name
    all survive, which is the whole point of emptying rather than destroying — and a grant nobody
    can see is not. So the late transfer loses its space and is recorded, rather than being half
    repaired.

    Args:
      name: The space name.
      request_id: The run's request id.

    Returns:
      A ``(committed, replaced)`` pair: the emptied record, and the record it overwrote.

    Raises:
      RegistryRecordMissing: When the record is gone, which is not a state to write over.
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """
    replaced: dict = {}

    def apply(existing):
        """Builds the emptied record and captures the one it replaces.

        Args:
          existing: The freshly-read record, or None.

        Returns:
          The record to write.

        Raises:
          RegistryRecordMissing: When there is no record to empty.
        """
        nonlocal replaced
        replaced = {}
        if existing is None:
            raise RegistryRecordMissing(f"space {name!r} has no registry record to empty")
        replaced = dict(existing)
        record = dict(existing)
        previous_owner = existing.get("owner") or existing.get("previousOwner")
        if previous_owner:
            record["previousOwner"] = previous_owner
        record["members"] = []
        record["acknowledged"] = []
        record["status"] = "active"
        record.setdefault("emptiedAt", now_iso())
        record.pop("owner", None)
        record.pop("reason", None)
        record["lastRequestId"] = request_id
        record["updatedAt"] = now_iso()
        return record

    committed = casio.cas_mutate(
        read=lambda: _read(name),
        apply=apply,
        write=lambda record, etag: _put(name, record, etag),
        label=f"registry/{name}",
    )
    return committed, replaced


def restore_owner(name: str, status: str, request_id: str, reason: str | None = None, members=()) -> None:
    """Records a failure and hands the space back to its previous owner, in one write.

    The repair for a fault that lands after the emptying rewrite. By then the owner field is
    gone, so the ordinary failure path would leave a record nobody can act on: the delete is
    owner-only and there is no owner, leaving is member-only and the roster is blank, and the
    retry the screen offers is refused. Restoring the owner returns the space to the owned,
    failed state every other failure leaves behind, which a retry can finish.

    One transform rather than a status write followed by an owner write, because both would sit
    inside a best-effort handler that swallows faults — and a fault between them leaves exactly
    the ownerless record this exists to prevent.

    **It restores a roster as well as an owner, and that is not tidiness.** The rewrite blanks the
    roster, so anyone whose revocation had not yet happened when the fault landed exists in no
    record at all: they keep the membership slot that IS their grant, they are never told, and
    nobody can remove them — an owner cannot act on a roster they are absent from, and they cannot
    leave a space that does not list them. Putting them back returns the record to the same
    owned-with-members shape a fault BEFORE the rewrite leaves, which the retry already handles.
    Re-revoking somebody already revoked is idempotent, so passing more names than strictly
    necessary is safe and passing too few is not.

    Args:
      name: The space name.
      status: The status to record.
      request_id: The run's request id.
      reason: The failure reason, when there is one.
      members: Members to put back on the roster, for anyone the run may not have revoked.

    Returns:
      None.

    Raises:
      RuntimeError: When the CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """

    def apply(existing):
        """Applies the status and re-owns the record from its previous owner.

        Args:
          existing: The freshly-read record, or None.

        Returns:
          The record to write, unchanged when there is nothing to act on.

        Raises:
          None.
        """
        if existing is None:
            return existing
        record = dict(existing)
        record["status"] = status
        if not record.get("owner") and record.get("previousOwner"):
            record["owner"] = record["previousOwner"]
        roster = list(record.get("members") or [])
        for member in members:
            if member not in roster:
                roster.append(member)
        record["members"] = roster
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
