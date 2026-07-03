"""Unit tests for the remove-members verb."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import clients  # noqa: E402
import config  # noqa: E402
import remove_members as r  # noqa: E402
from fakes import install  # noqa: E402


def _enable_notifications():
    """Point the emit helper at a queue so notify is no longer a no-op; return the
    FakeSqs install() already wired onto clients._sqs."""
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
    return clients._sqs


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


def test_remove_members_clears_slot_registry_and_cache_leaves_data():
    s3, glue, lf, cognito = install()
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}}
    reg = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg)
    s3.store[("user-bkt", "bob/user_settings/shared-connections.json")] = json.dumps(
        {"version": 1, "connections": [{"name": "sales", "role": "member", "status": "active"}]}
    ).encode()

    out = r.remove_members("sales", ["bob"], "req-3", reg)
    assert out["removed"] == ["bob"]
    assert cognito.users["bob"]["custom:shared_space_1"] == ""
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg2["members"] == ["alice"]
    bob_cache = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])
    assert bob_cache["connections"] == []
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert owner_cache["connections"][0]["members"] == [{"username": "alice", "status": "active"}]
    assert glue.created == []


def test_remove_members_idempotent_for_non_member():
    s3, glue, lf, cognito = install()
    cognito.users = {"bob": {}}
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = r.remove_members("sales", ["bob"], "req-3", reg)
    assert out["removed"] == []


def test_remove_members_never_removes_the_owner():
    s3, glue, lf, cognito = install()
    reg = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg)

    out = r.remove_members("sales", ["alice"], "req-3", reg)
    assert out["removed"] == []
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert "alice" in reg2["members"]


def test_handler_uses_validated_context():
    s3, glue, lf, cognito = install()
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}}
    reg = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg)
    out = r.handler(
        {"space": "sales", "requestId": "req-3", "registry": reg, "payload": {"members": ["bob"]}}, None
    )
    assert out["removed"] == ["bob"]


def test_remove_members_notifies_each_removed_member():
    s3, glue, lf, cognito = install()
    sqs = _enable_notifications()
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}}
    reg = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg)

    r.remove_members("sales", ["bob"], "req-3", reg)
    # Exactly one notification — to the removed member, not the owner.
    assert len(sqs.sent) == 1
    msg = sqs.sent[0]
    assert msg["MessageGroupId"] == "bob"
    assert msg["MessageDeduplicationId"] == "req-3:remove-member:bob"
    assert json.loads(msg["MessageBody"]) == {
        "action": "create",
        "username": "bob",
        "message": 'You\'ve been removed from the shared workspace "sales".',
    }


def test_remove_members_noop_notifies_nothing():
    s3, glue, lf, cognito = install()
    sqs = _enable_notifications()
    cognito.users = {"bob": {}}
    reg = _active_reg(members=["alice"])  # bob isn't a member
    _seed_reg(s3, reg)

    r.remove_members("sales", ["bob"], "req-3", reg)
    assert sqs.sent == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} remove-members tests passed.")
    sys.exit(0)
