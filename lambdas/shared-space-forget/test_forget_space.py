"""Unit tests for the forget verb (durable "clear from my list")."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import forget_space as f
from auth import AuthorizationError
from fakes import install, raises


def _seed_cache(s3, user, entries):
    s3.store[("user-bkt", f"{user}/user_settings/shared-connections.json")] = json.dumps(
        {"version": 1, "connections": entries}
    ).encode()


def _cache(s3, user):
    return json.loads(s3.store[("user-bkt", f"{user}/user_settings/shared-connections.json")])["connections"]


# Cache-only: collision phantom (no registry record for the actor to own).
def test_forget_phantom_removes_only_actor_entry_and_slot():
    s3, _glue, _lf, cognito = install()
    cognito.users = {"alice": {"custom:shared_space_1": "sales"}}
    _seed_cache(s3, "alice", [{"name": "sales", "role": "owner", "status": "failed", "reason": "name already taken"}])

    out = f.forget_space("sales", "alice", "req-f", None)  # registry None -> phantom
    assert out["mode"] == "cache_only"
    assert _cache(s3, "alice") == []                         # entry gone
    assert cognito.users["alice"]["custom:shared_space_1"] == ""  # slot cleared


# Teardown: the actor's own failed create.
def test_forget_own_failed_space_tears_down_resources_and_frees_name():
    s3, glue, _lf, cognito = install()
    cognito.users = {"alice": {"custom:shared_space_1": "sales"}}
    registry = {"name": "sales", "owner": "alice", "members": ["alice"], "status": "failed", "reason": "boom"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    s3.store[("shared-bkt", "sales/DO_NOT_DELETE.txt")] = b"marker"
    glue.databases.add("sales")
    glue.tables["sales"] = ["t1"]
    _seed_cache(s3, "alice", [{"name": "sales", "role": "owner", "status": "failed", "reason": "boom"}])

    out = f.forget_space("sales", "alice", "req-f", registry)
    assert out["mode"] == "teardown"
    assert not any(b == "shared-bkt" and k.startswith("sales/") for (b, k) in s3.store)  # prefix gone
    assert "sales" not in glue.databases                       # DB dropped
    assert cognito.users["alice"]["custom:shared_space_1"] == ""  # slot cleared
    assert _cache(s3, "alice") == []                           # cache entry gone
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store  # registry deleted -> name freed


# Refuse: a healthy active space the actor belongs to.
def test_forget_refuses_active_space_owner():
    s3, glue, _lf, _cognito = install()
    registry = {"name": "sales", "owner": "alice", "members": ["alice"], "status": "active"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    glue.databases.add("sales")
    raises(lambda: f.forget_space("sales", "alice", "req-f", registry), AuthorizationError, "active")
    # Nothing torn down.
    assert ("admin-bkt", "shared-spaces/sales.json") in s3.store
    assert "sales" in glue.databases


def test_forget_clears_the_index_on_the_teardown_path():
    s3, _glue, _lf, cognito = install()
    cognito.users = {"alice": {"custom:shared_space_1": "sales"}}
    registry = {"name": "sales", "owner": "alice", "members": ["alice"], "status": "failed"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    s3.store[("admin-bkt", "memberships/alice.json")] = json.dumps(
        {"version": 1, "username": "alice", "spaces": [{"name": "sales", "status": "active"}]}
    ).encode()
    _seed_cache(s3, "alice", [{"name": "sales", "role": "owner", "status": "failed"}])

    assert f.forget_space("sales", "alice", "req-f", registry)["mode"] == "teardown"
    assert json.loads(s3.store[("admin-bkt", "memberships/alice.json")])["spaces"] == []


def test_forget_teardown_clears_EVERY_members_index_because_it_frees_the_name():
    # A delete that fails partway writes `failed` on a record that keeps its members, and that
    # record reaches the teardown branch — so "a failed create is single-member" does not cover
    # every case that lands here. reg.delete frees the name, and an index still naming a space
    # whose name is free is an entitlement to whatever gets created next.
    s3, glue, _lf, cognito = install()
    cognito.users = {"alice": {"custom:shared_space_1": "sales"}, "bob": {"custom:shared_space_1": "sales"}}
    registry = {"name": "sales", "owner": "alice", "members": ["alice", "bob"], "status": "failed"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    for member in ("alice", "bob"):
        s3.store[("admin-bkt", f"memberships/{member}.json")] = json.dumps(
            {"version": 1, "username": member, "spaces": [{"name": "sales", "status": "active"}]}
        ).encode()
    _seed_cache(s3, "alice", [{"name": "sales", "role": "owner", "status": "failed"}])
    glue.databases.add("sales")

    assert f.forget_space("sales", "alice", "req-f", registry)["mode"] == "teardown"
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store
    for member in ("alice", "bob"):
        assert json.loads(s3.store[("admin-bkt", f"memberships/{member}.json")])["spaces"] == []


def test_forget_clears_the_index_on_the_cache_only_path_too():
    # The cache-only path leaves the REGISTRY alone by design. Leaving the entitlement behind is
    # a different thing, and it is not the design: the slot is cleared here, so the index is too.
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}}
    s3.store[("admin-bkt", "memberships/bob.json")] = json.dumps(
        {"version": 1, "username": "bob", "spaces": [{"name": "sales", "status": "active"}]}
    ).encode()
    _seed_cache(s3, "bob", [{"name": "sales", "role": "member", "status": "active"}])

    assert f.forget_space("sales", "bob", "req-f", None)["mode"] == "cache_only"
    assert json.loads(s3.store[("admin-bkt", "memberships/bob.json")])["spaces"] == []
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} forget-space tests passed.")
    sys.exit(0)
