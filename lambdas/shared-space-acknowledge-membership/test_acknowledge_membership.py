"""Unit tests for the acknowledge-membership verb (SPEC-073)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import acknowledge_membership as ack  # noqa: E402
from auth import AuthorizationError  # noqa: E402
from fakes import install, raises  # noqa: E402


def _seed(s3, name="sales", members=("alice", "bob"), acknowledged=None):
    """Seed a registry (+ owner cache) for space ``name``; owner = members[0].

    ``acknowledged=None`` writes NO acknowledged field (a legacy, pre-073 record);
    pass a list to seed a post-073 record with explicit join status.
    """
    owner = members[0]
    record = {"name": name, "owner": owner, "members": list(members), "status": "active", "createdAt": "t0"}
    if acknowledged is not None:
        record["acknowledged"] = list(acknowledged)
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(record).encode()
    s3.store[("user-bkt", f"{owner}/user_settings/shared-connections.json")] = json.dumps(
        {"version": 1, "connections": [{"name": name, "role": "owner", "status": "active"}]}
    ).encode()


def _owner_members(s3, owner="alice"):
    cache = json.loads(s3.store[("user-bkt", f"{owner}/user_settings/shared-connections.json")])
    return cache["connections"][0]["members"]


def test_acknowledge_flips_pending_member_to_active():
    s3, glue, lf, cognito = install()
    _seed(s3, acknowledged=[])  # bob was added as pending
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    out = ack.acknowledge_membership("sales", "bob", "req-a", reg)

    assert out["activated"] is True
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg2["acknowledged"] == ["bob"]
    assert reg2["members"] == ["alice", "bob"]  # membership unchanged
    assert _owner_members(s3) == [
        {"username": "alice", "status": "active"},  # owner always active
        {"username": "bob", "status": "active"},
    ]


def test_acknowledge_idempotent_when_already_active():
    s3, glue, lf, cognito = install()
    _seed(s3, acknowledged=["bob"])
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    before = s3.store[("user-bkt", "alice/user_settings/shared-connections.json")]

    out = ack.acknowledge_membership("sales", "bob", "req-a", reg)

    assert out["activated"] is False
    # No spurious projection write (FR-003).
    assert s3.store[("user-bkt", "alice/user_settings/shared-connections.json")] == before


def test_acknowledge_legacy_member_is_noop():
    s3, glue, lf, cognito = install()
    _seed(s3, acknowledged=None)  # pre-073 record: members are all-active by back-compat
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    before = s3.store[("user-bkt", "alice/user_settings/shared-connections.json")]

    out = ack.acknowledge_membership("sales", "bob", "req-a", reg)

    assert out["activated"] is False
    assert s3.store[("user-bkt", "alice/user_settings/shared-connections.json")] == before


def test_acknowledge_rejects_owner():
    s3, glue, lf, cognito = install()
    _seed(s3, acknowledged=[])
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    raises(
        lambda: ack.acknowledge_membership("sales", "alice", "req-a", reg),
        AuthorizationError,
        "owner does not acknowledge",
    )


def test_acknowledge_noop_for_non_member():
    s3, glue, lf, cognito = install()
    _seed(s3, acknowledged=[])
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    out = ack.acknowledge_membership("sales", "carol", "req-a", reg)
    assert out["activated"] is False


def test_handler_uses_validated_context():
    s3, glue, lf, cognito = install()
    _seed(s3, acknowledged=[])
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    out = ack.handler({"space": "sales", "actor": "bob", "requestId": "req-a", "registry": reg}, None)
    assert out["activated"] is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} acknowledge-membership tests passed.")
    sys.exit(0)
