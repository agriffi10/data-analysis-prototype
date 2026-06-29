"""Unit tests for the create-space verb (SPEC-051; SPEC-062). Plain-script or pytest;
the common layer is added to sys.path so the verb's imports resolve locally."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import create_space as c  # noqa: E402
import registry as reg  # noqa: E402
from fakes import install, raises  # noqa: E402


def test_create_happy_path_provisions_everything():
    s3, glue, lf, cognito = install()
    out = c.create_space("sales", "alice", "req-1")
    assert out["status"] == "active"
    assert glue.created == ["sales"]
    assert len(lf.grants) == 2
    assert cognito.attrs["custom:shared_space_1"] == "sales"
    rec = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["status"] == "active" and rec["owner"] == "alice"
    assert ("shared-bkt", "sales/DO_NOT_DELETE.txt") in s3.store
    cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert cache["connections"] == [
        {"name": "sales", "role": "owner", "status": "active", "members": ["alice"]}
    ]


def test_create_name_collision_fails():
    s3, *_ = install()
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "bob", "lastRequestId": "other", "status": "active"}
    ).encode()
    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.ProvisioningError, "name already taken")


def test_create_replay_same_request_is_idempotent():
    s3, glue, *_ = install()
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "alice", "lastRequestId": "req-1", "status": "active"}
    ).encode()
    out = c.create_space("sales", "alice", "req-1")
    assert out["status"] == "active" and out.get("replay") is True
    assert glue.created == []


def test_create_slot_full_fails_and_records_failure():
    s3, glue, lf, cognito = install(
        cognito_attrs={"custom:shared_space_1": "a", "custom:shared_space_2": "b"},
        max_memberships=2,
    )
    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.ProvisioningError, "membership limit reached")
    rec = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["status"] == "failed" and "membership limit" in rec["reason"]
    cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert cache["connections"][0]["status"] == "failed"
    assert glue.created == []


def test_create_slot_assignment_is_replay_safe():
    install(cognito_attrs={"custom:shared_space_2": "sales"})
    import clients

    clients._s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "alice", "lastRequestId": "req-1", "status": "provisioning"}
    ).encode()
    out = c.create_space("sales", "alice", "req-1")  # replay (provisioning -> re-run steps)
    assert out["status"] == "active"
    assert clients._cognito.attrs["custom:shared_space_2"] == "sales"
    assert "custom:shared_space_1" not in clients._cognito.attrs


def test_handler_uses_validated_context():
    install()
    out = c.handler({"space": "sales", "actor": "alice", "requestId": "req-1"}, None)
    assert out["status"] == "active" and out["owner"] == "alice"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} create-space tests passed.")
    sys.exit(0)
