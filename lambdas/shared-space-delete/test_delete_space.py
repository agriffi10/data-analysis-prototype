"""Unit tests for the delete-space verb (SPEC-054 cascade; SPEC-062)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import delete_space as d  # noqa: E402
from fakes import install, raises  # noqa: E402


def _seed_full_space(s3, glue, cognito, name="sales", members=("alice", "bob")):
    owner = members[0]
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(
        {"name": name, "owner": owner, "members": list(members), "status": "active", "createdAt": "t0"}
    ).encode()
    s3.store[("shared-bkt", f"{name}/DO_NOT_DELETE.txt")] = b"marker"
    s3.store[("shared-bkt", f"{name}/data/file.csv")] = b"data"
    s3.store[("shared-bkt", f"{name}/athenaresults/alice/q.csv")] = b"result"
    glue.databases.add(name)
    glue.tables[name] = ["t1", "t2"]
    cognito.users = {}
    for m in members:
        cognito.users[m] = {"custom:shared_space_1": name}
        role = "owner" if m == owner else "member"
        s3.store[("user-bkt", f"{m}/user_settings/shared-connections.json")] = json.dumps(
            {"version": 1, "connections": [{"name": name, "role": role, "status": "active"}]}
        ).encode()


def test_delete_cascades_files_tables_db_members_and_registry_frees_name():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    out = d.delete_space("sales", "alice", "req-d", reg)
    assert out["status"] == "ok" and set(out["revokedMembers"]) == {"alice", "bob"}
    assert not any(b == "shared-bkt" and k.startswith("sales/") for (b, k) in s3.store)
    assert "sales" not in glue.databases and "sales" not in glue.tables
    assert len(lf.revokes) == 2
    for m in ("alice", "bob"):
        assert cognito.users[m]["custom:shared_space_1"] == ""
        cache = json.loads(s3.store[("user-bkt", f"{m}/user_settings/shared-connections.json")])
        assert cache["connections"] == []
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store


def test_delete_idempotent_tolerant_of_partial_prior_progress():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    glue.databases.discard("sales")
    glue.tables.pop("sales", None)
    for key in [k for (b, k) in list(s3.store) if b == "shared-bkt"]:
        s3.store.pop(("shared-bkt", key), None)

    out = d.delete_space("sales", "alice", "req-d", reg)
    assert out["status"] == "ok"
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store
    for m in ("alice", "bob"):
        assert cognito.users[m]["custom:shared_space_1"] == ""


def test_delete_records_failure_and_reraises_without_deleting_registry():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    orig = d._drop_database
    try:
        def boom(name):
            raise RuntimeError("glue throttled")

        d._drop_database = boom
        raises(lambda: d.delete_space("sales", "alice", "req-d", reg), RuntimeError, "throttled")
    finally:
        d._drop_database = orig
    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["status"] == "failed" and "throttled" in saved["reason"]
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert owner_cache["connections"][0]["status"] == "failed"


def test_handler_uses_validated_context():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    out = d.handler({"space": "sales", "actor": "alice", "requestId": "req-d", "registry": reg}, None)
    assert out["status"] == "ok"
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} delete-space tests passed.")
    sys.exit(0)
