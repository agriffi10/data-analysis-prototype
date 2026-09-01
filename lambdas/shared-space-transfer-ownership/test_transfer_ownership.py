"""The transfer verb: the roster it publishes, the two people it tells, and the fence behind the router."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import transfer_ownership as verb
from cpcommon import clients
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError
from fakes import install

_REG = ("admin-bkt", "shared-spaces/finance.json")


def _record(**overrides):
    """Builds an active registry record for the space under test.

    Args:
      **overrides: Fields to replace.

    Returns:
      The record.

    Raises:
      None.
    """
    record = {
        "schemaVersion": 1,
        "name": "finance",
        "owner": "alice",
        "members": ["alice", "bob", "carol"],
        "acknowledged": ["bob", "carol"],
        "status": "active",
        "everActive": True,
        "createdAt": "2026-01-01T00:00:00Z",
    }
    record.update(overrides)
    return record


def _setup(**overrides):
    """Installs the fakes, seeds the registry, and turns notifications on.

    Args:
      **overrides: Registry fields to replace.

    Returns:
      The S3 fake and the seeded record.

    Raises:
      None.
    """
    s3, *_ = install()
    record = _record(**overrides)
    s3.store[_REG] = json.dumps(record).encode()
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/notifications.fifo"
    return s3, record


def _event(record, new_owner="bob", **extra):
    """Builds the validated context the router hands this verb.

    Args:
      record: The registry record.
      new_owner: The member taking the space.
      **extra: Extra context fields.

    Returns:
      The task input.

    Raises:
      None.
    """
    event = {
        "action": "transfer_ownership",
        "actor": record.get("owner", ""),
        "space": "finance",
        "payload": {"newOwner": new_owner},
        "registry": record,
        "requestId": "r1",
    }
    event.update(extra)
    return event


def _cache(s3, username):
    """Reads one user's shared-connections entry for the space.

    Args:
      s3: The S3 fake.
      username: Whose cache to read.

    Returns:
      The entry, or None when the user has none.

    Raises:
      None.
    """
    raw = s3.store.get(("user-bkt", f"{username}/user_settings/shared-connections.json"))
    if raw is None:
        return None
    entries = [e for e in json.loads(raw)["connections"] if e["name"] == "finance"]
    return entries[0] if entries else None


def _status_of(entry, username):
    """Reads one member's join status out of a cached roster projection.

    Args:
      entry: The cache entry.
      username: The member to look up.

    Returns:
      The status string, or None when the member is absent.

    Raises:
      None.
    """
    for member in entry["members"]:
        if member["username"] == username:
            return member["status"]
    return None


def test_a_transfer_leaves_both_parties_reading_active_in_every_roster():
    """FR-003: the outgoing owner keeps their membership and does NOT fall back to pending.

    Driven against a space ``add_members`` has run on — one carrying an explicit acknowledged
    list — because that is every space in the product, and it is the case where an owner-only
    rewrite would show someone who has used the space for months as not having picked it up yet.
    """
    s3, record = _setup()

    verb.handler(_event(record), None)

    for reader in ("alice", "bob", "carol"):
        entry = _cache(s3, reader)
        assert _status_of(entry, "alice") == "active", f"{reader} sees the former owner as pending"
        assert _status_of(entry, "bob") == "active", f"{reader} sees the new owner as pending"


def test_a_space_with_no_acknowledged_field_still_leaves_both_parties_active():
    """FR-003: the legacy path — created before the field existed and never added to."""
    record = _record()
    del record["acknowledged"]
    s3, *_ = install()
    s3.store[_REG] = json.dumps(record).encode()
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/notifications.fifo"

    verb.handler(_event(record), None)

    entry = _cache(s3, "carol")
    assert _status_of(entry, "alice") == "active"
    assert _status_of(entry, "bob") == "active"


def test_the_roles_and_the_named_owner_move_with_the_transfer():
    """FR-003/FR-004: the former owner becomes a member naming the new one; the new one is owner."""
    s3, record = _setup()

    verb.handler(_event(record), None)

    assert _cache(s3, "alice")["role"] == "member"
    assert _cache(s3, "alice")["owner"] == "bob"
    assert _cache(s3, "bob")["role"] == "owner"
    assert _cache(s3, "carol")["owner"] == "bob", "every member's cache names the new owner"


def test_a_member_with_no_cache_document_has_one_created():
    """FR-004: absent is not skipped — a member who has never signed in still gets the roster."""
    s3, record = _setup()
    assert _cache(s3, "carol") is None

    verb.handler(_event(record), None)

    assert _cache(s3, "carol") is not None


def test_the_registry_commits_before_the_fan_out():
    """FR-004: a fan-out landing first would publish an owner the registry does not agree with."""
    s3, record = _setup()
    seen = []
    real_put = s3.put_object

    def watch(Bucket, Key, Body, **kw):
        seen.append(Key)
        return real_put(Bucket=Bucket, Key=Key, Body=Body, **kw)

    s3.put_object = watch
    verb.handler(_event(record), None)

    registry_at = seen.index("shared-spaces/finance.json")
    first_cache_at = next(i for i, key in enumerate(seen) if key.endswith("shared-connections.json"))
    assert registry_at < first_cache_at, f"the fan-out ran before the registry committed: {seen}"


def test_one_members_cache_failing_does_not_abort_the_others():
    """FR-004: best-effort per member, and the failure is logged with the member named."""
    s3, record = _setup()
    real_put = s3.put_object

    def fail_for_carol(Bucket, Key, Body, **kw):
        if Key.startswith("carol/"):
            raise RuntimeError("carol's cache is unavailable")
        return real_put(Bucket=Bucket, Key=Key, Body=Body, **kw)

    s3.put_object = fail_for_carol
    verb.handler(_event(record), None)

    assert json.loads(s3.store[_REG])["owner"] == "bob", "the registry still committed"
    assert _cache(s3, "alice") is not None, "the other members were still written"
    assert _cache(s3, "bob") is not None


def test_exactly_two_people_are_notified_and_each_is_told_the_other_name():
    """FR-005: one producer says the outcome, and only the two whose role changed hear it."""
    _s3, record = _setup()

    verb.handler(_event(record), None)

    sent = [json.loads(m["MessageBody"]) for m in clients._sqs.sent]
    recipients = sorted(m["username"] for m in sent)
    assert recipients == ["alice", "bob"], f"someone else was told: {recipients}"

    by_user = {m["username"]: m["message"] for m in sent}
    assert "bob" in by_user["alice"] and "finance" in by_user["alice"]
    assert "alice" in by_user["bob"] and "finance" in by_user["bob"]


def test_an_operator_driven_transfer_notifies_both_parties_and_names_no_operator():
    """FR-008: the operator is not a party to the outcome, only the cause of it."""
    _s3, record = _setup()

    verb.handler(_event(record, origin="operator"), None)

    sent = [json.loads(m["MessageBody"]) for m in clients._sqs.sent]
    assert sorted(m["username"] for m in sent) == ["alice", "bob"]
    assert not any("operator" in m["message"].lower() for m in sent)


def test_the_verb_refuses_a_context_carrying_a_refusal():
    """The fence behind the router, and the reason it is not belt and braces.

    The compare-and-swap's owner check is a LOST-UPDATE guard: it asks whether the owner changed
    since the request was authorized, and for a forged operator message nothing about the owner
    has changed — so it passes. If the Choice ever failed to select the refusal branch, the
    transfer would complete. This is what stops that being one edit away.
    """
    s3, record = _setup()

    with pytest.raises(TerminalError) as raised:
        verb.handler(
            _event(record, refusal={"code": "TransferOriginUntrusted", "message": "no"}), None
        )

    assert "TransferOriginUntrusted" in str(raised.value)
    assert json.loads(s3.store[_REG])["owner"] == "alice", "the space did not move"
    assert clients._sqs.sent == [], "and nobody was told it had"


def test_a_transfer_naming_nobody_is_refused_rather_than_writing_an_empty_owner():
    """The payload field is optional on the wire, so the verb cannot assume it is there."""
    s3, record = _setup()

    with pytest.raises(TerminalError):
        verb.handler(_event(record, payload={}), None)

    assert json.loads(s3.store[_REG])["owner"] == "alice"


def test_a_transfer_moves_no_membership_slot_and_enqueues_no_leave():
    """FR-003: the former owner's own AWS access is untouched, and leaving stays a separate action.

    Access here is the membership principal tag, membership did not change, so no slot moves. And
    the verb must not "tidy up" by having the outgoing owner leave — they stay a member.
    """
    s3, _glue, lf, cognito = install()
    record = _record()
    s3.store[_REG] = json.dumps(record).encode()
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/notifications.fifo"

    verb.handler(_event(record), None)

    assert cognito.updates == [], "no membership slot was written or cleared"
    assert lf.grants == [] and lf.revokes == []
    assert json.loads(s3.store[_REG])["members"] == ["alice", "bob", "carol"]

    sent = [json.loads(m["MessageBody"]) for m in clients._sqs.sent]
    assert not any(m.get("action") == "leave" for m in sent), "no leave was enqueued"
