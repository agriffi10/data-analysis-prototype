"""Unit tests for the leave verb (SPEC-054; SPEC-062)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import leave as l  # noqa: E402
from auth import AuthorizationError  # noqa: E402
from fakes import install, raises  # noqa: E402


def _seed_full_space(s3, glue, cognito, name="sales", members=("alice", "bob")):
    owner = members[0]
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(
        {"name": name, "owner": owner, "members": list(members), "status": "active", "createdAt": "t0"}
    ).encode()
    s3.store[("shared-bkt", f"{name}/DO_NOT_DELETE.txt")] = b"marker"
    glue.databases.add(name)
    glue.tables[name] = ["t1", "t2"]
    cognito.users = {}
    for m in members:
        cognito.users[m] = {"custom:shared_space_1": name}
        role = "owner" if m == owner else "member"
        s3.store[("user-bkt", f"{m}/user_settings/shared-connections.json")] = json.dumps(
            {"version": 1, "connections": [{"name": name, "role": role, "status": "active"}]}
        ).encode()


def test_leave_clears_slot_cache_registry_and_owner_projection_leaves_data():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    out = l.leave_space("sales", "bob", "req-l", reg)
    assert out["left"] is True
    assert cognito.users["bob"]["custom:shared_space_1"] == ""
    bob_cache = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])
    assert bob_cache["connections"] == []
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg2["members"] == ["alice"]
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert owner_cache["connections"][0]["members"] == ["alice"]
    assert ("shared-bkt", "sales/DO_NOT_DELETE.txt") in s3.store
    assert "sales" in glue.databases and glue.tables["sales"] == ["t1", "t2"]


def test_leave_idempotent_for_non_member():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice",))
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    out = l.leave_space("sales", "carol", "req-l", reg)
    assert out["left"] is False
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg2["members"] == ["alice"]


def test_leave_defensive_owner_guard():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    raises(lambda: l.leave_space("sales", "alice", "req-l", reg), AuthorizationError, "owner cannot leave")


def test_handler_uses_validated_context():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    out = l.handler({"space": "sales", "actor": "bob", "requestId": "req-l", "registry": reg}, None)
    assert out["left"] is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} leave tests passed.")
    sys.exit(0)
