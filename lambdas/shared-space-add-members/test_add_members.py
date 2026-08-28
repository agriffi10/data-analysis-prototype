"""Unit tests for the add-members verb."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import add_members as a
from cpcommon import clients
from cpcommon import config as cpconfig
from fakes import install


def _enable_notifications():
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
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
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {}}
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = a.add_members("sales", ["bob"], "req-2", reg)
    assert out["added"] == ["bob"]
    assert out["ignoredUnknown"] == [] and out["skippedAtLimit"] == []
    assert cognito.users["bob"]["custom:shared_space_1"] == "sales"
    bob_cache = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])
    # SPEC-075: bob's own entry now carries the full roster (owner active, bob pending
    # until he acks), same projection the owner sees.
    assert bob_cache["connections"] == [
        {
            "name": "sales",
            "role": "member",
            "status": "active",
            "owner": "alice",
            "members": [
                {"username": "alice", "status": "active"},
                {"username": "bob", "status": "pending"},
            ],
            "createdAt": "t0",
        }
    ]
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert set(reg2["members"]) == {"alice", "bob"} and reg2["owner"] == "alice"
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    # bob is newly added -> pending until he signs in and acks; alice (owner) is active.
    assert owner_cache["connections"][0]["members"] == [
        {"username": "alice", "status": "active"},
        {"username": "bob", "status": "pending"},
    ]


def test_add_members_skips_at_limit_target_and_still_adds_others():
    s3, _glue, _lf, cognito = install(max_memberships=2)
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


def test_add_member_notifies_added_user():
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {}}
    sqs = _enable_notifications()
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    a.add_members("sales", ["bob"], "req-2", reg)
    assert _sent(sqs) == [("bob", 'You\'ve been added to the shared workspace "sales".')]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} add-members tests passed.")
    sys.exit(0)
