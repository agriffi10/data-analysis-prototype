"""Unit tests for the add-members verb (SPEC-053; SPEC-062)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import add_members as a  # noqa: E402
from fakes import install  # noqa: E402


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
    assert bob_cache["connections"] == [{"name": "sales", "role": "member", "status": "active"}]
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
