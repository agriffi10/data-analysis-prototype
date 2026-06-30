"""Unit tests for the add-members verb (SPEC-053; SPEC-062)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import clients  # noqa: E402
import config  # noqa: E402
import add_members as a  # noqa: E402
from fakes import install  # noqa: E402


def _enable_notifications():
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
    return clients._sqs


def _sent(sqs):
    """(recipient, message) for each enqueued notification, in order."""
    out = []
    for m in sqs.sent:
        body = json.loads(m["MessageBody"])
        out.append((body["username"], body["message"]))
    return out


def _active_reg(name="sales", owner="alice", members=None):
    return {
        "name": name,
        "owner": owner,
        "members": members if members is not None else [owner],
        "status": "active",
        "createdAt": "t0",
        "lastRequestId": "r0",
    }


def _seed_reg(s3, reg):
    s3.store[("admin-bkt", f"shared-spaces/{reg['name']}.json")] = json.dumps(reg).encode()


def test_add_members_assigns_slot_registry_cache_and_owner_projection():
    s3, glue, lf, cognito = install()
    cognito.users = {"bob": {}}
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = a.add_members("sales", ["bob"], "req-2", reg)
    assert out["added"] == ["bob"]
    assert out["ignoredUnknown"] == [] and out["skippedAtLimit"] == []
    assert cognito.users["bob"]["custom:shared_space_1"] == "sales"
    bob_cache = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])
    assert bob_cache["connections"] == [
        {"name": "sales", "role": "member", "status": "active", "owner": "alice", "createdAt": "t0"}
    ]
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert set(reg2["members"]) == {"alice", "bob"} and reg2["owner"] == "alice"
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert owner_cache["connections"][0]["members"] == ["alice", "bob"]


def test_add_members_ignores_unknown_users_silently():
    s3, glue, lf, cognito = install()
    cognito.users = {"bob": {}}
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = a.add_members("sales", ["bob", "ghost"], "req-2", reg)
    assert out["added"] == ["bob"] and out["ignoredUnknown"] == ["ghost"]
    assert ("user-bkt", "ghost/user_settings/shared-connections.json") not in s3.store


def test_add_members_skips_at_limit_target_and_still_adds_others():
    s3, glue, lf, cognito = install(max_memberships=2)
    cognito.users = {
        "full": {"custom:shared_space_1": "x", "custom:shared_space_2": "y"},
        "bob": {},
    }
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = a.add_members("sales", ["full", "bob"], "req-2", reg)
    assert out["skippedAtLimit"] == ["full"] and out["added"] == ["bob"]
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert set(reg2["members"]) == {"alice", "bob"}


def test_add_members_idempotent_for_existing_member():
    s3, glue, lf, cognito = install()
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}}
    reg = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg)

    out = a.add_members("sales", ["bob"], "req-2", reg)
    assert out["added"] == []
    assert cognito.updates == []


def test_add_members_never_adds_the_owner():
    s3, glue, lf, cognito = install()
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = a.add_members("sales", ["alice"], "req-2", reg)
    assert out["added"] == [] and out["ignoredUnknown"] == []


# ── SPEC-061: producer events 3, 4, 5 ────────────────────────────────────────
def test_add_member_notifies_added_user():
    s3, glue, lf, cognito = install()
    cognito.users = {"bob": {}}
    sqs = _enable_notifications()
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    a.add_members("sales", ["bob"], "req-2", reg)
    assert _sent(sqs) == [("bob", 'You\'ve been added to the shared workspace "sales".')]


def test_add_unknown_notifies_owner():
    s3, glue, lf, cognito = install()
    cognito.users = {"bob": {}}
    sqs = _enable_notifications()
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    a.add_members("sales", ["ghost"], "req-2", reg)
    assert _sent(sqs) == [("alice", 'Couldn\'t add "ghost" to "sales": no such user.')]


def test_add_at_limit_notifies_owner():
    s3, glue, lf, cognito = install(max_memberships=2)
    cognito.users = {"full": {"custom:shared_space_1": "x", "custom:shared_space_2": "y"}}
    sqs = _enable_notifications()
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    a.add_members("sales", ["full"], "req-2", reg)
    assert _sent(sqs) == [
        ("alice", 'Couldn\'t add "full" to "sales": they\'ve reached their workspace limit.')
    ]


def test_bulk_add_emits_per_affected_user_and_silences_existing_members():
    s3, glue, lf, cognito = install(max_memberships=2)
    cognito.users = {
        "bob": {},
        "carol": {},
        "full": {"custom:shared_space_1": "x", "custom:shared_space_2": "y"},
        "dave": {"custom:shared_space_1": "sales"},  # already a member -> silent
    }
    sqs = _enable_notifications()
    reg = _active_reg(members=["alice", "dave"])
    _seed_reg(s3, reg)

    a.add_members("sales", ["bob", "carol", "full", "ghost", "dave"], "req-2", reg)
    sent = _sent(sqs)
    # Two "added" (bob, carol) + one at-limit (full) + one unknown (ghost) to the owner;
    # the already-member dave emits nothing.
    assert ("bob", 'You\'ve been added to the shared workspace "sales".') in sent
    assert ("carol", 'You\'ve been added to the shared workspace "sales".') in sent
    assert ("alice", 'Couldn\'t add "full" to "sales": they\'ve reached their workspace limit.') in sent
    assert ("alice", 'Couldn\'t add "ghost" to "sales": no such user.') in sent
    assert len(sent) == 4
    assert all(r != "dave" and "dave" not in m for r, m in sent)


def test_handler_uses_validated_context():
    s3, glue, lf, cognito = install()
    cognito.users = {"bob": {}}
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)
    out = a.handler(
        {"space": "sales", "requestId": "req-2", "registry": reg, "payload": {"members": ["bob"]}}, None
    )
    assert out["added"] == ["bob"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} add-members tests passed.")
    sys.exit(0)
