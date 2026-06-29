"""Unit tests for the validate-authorize Lambda (SPEC-056; SPEC-062).

Token verification is stubbed (auth.verified_username); the validator's job is to
parse the record, derive the actor, load the registry, authorize, and emit the
validated context — a failed check raises before any verb context is produced.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import auth  # noqa: E402
import validate as v  # noqa: E402
from fakes import install, raises  # noqa: E402


def _event(action="create", space="sales", token="tok", members=None):
    body = {
        "schemaVersion": 1,
        "requestId": "r1",
        "action": action,
        "actor": "spoofed",
        "space": space,
        "idToken": token,
    }
    if members is not None:
        body["payload"] = {"members": members}
    return [{"body": json.dumps(body)}]


def _seed_reg(s3, name="sales", owner="alice", members=("alice", "bob")):
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(
        {"name": name, "owner": owner, "members": list(members), "status": "active"}
    ).encode()


def _stub_actor(name):
    auth.verified_username = lambda tok: name


def test_validate_create_emits_context_with_token_actor():
    install()
    orig = auth.verified_username
    try:
        _stub_actor("alice")  # ignores the body "spoofed" actor
        ctx = v.handler(_event("create", "sales"), None)
        assert ctx == {
            "action": "create",
            "actor": "alice",
            "space": "sales",
            "payload": {},
            "registry": None,
            "requestId": "r1",
        }
    finally:
        auth.verified_username = orig


def test_validate_add_members_loads_registry_and_authorizes_owner():
    s3, *_ = install()
    _seed_reg(s3, members=["alice"])
    orig = auth.verified_username
    try:
        _stub_actor("alice")  # the owner
        ctx = v.handler(_event("add_members", "sales", members=["bob"]), None)
        assert ctx["action"] == "add_members" and ctx["actor"] == "alice"
        assert ctx["payload"] == {"members": ["bob"]}
        assert ctx["registry"]["owner"] == "alice"
    finally:
        auth.verified_username = orig


def test_validate_rejects_non_owner_before_context():
    s3, *_ = install()
    _seed_reg(s3, members=["alice"])
    orig = auth.verified_username
    try:
        _stub_actor("mallory")  # not the owner
        raises(lambda: v.handler(_event("delete", "sales"), None), auth.AuthorizationError, "owner-only")
    finally:
        auth.verified_username = orig


def test_validate_forged_token_rejected():
    install()
    orig = auth.verified_username
    try:
        def boom(tok):
            raise auth.AuthorizationError("token verification failed")

        auth.verified_username = boom
        raises(lambda: v.handler(_event("create"), None), auth.AuthorizationError, "verification failed")
    finally:
        auth.verified_username = orig


def test_validate_bad_schema_version_rejected():
    install()
    raises(
        lambda: v.handler([{"body": json.dumps({"schemaVersion": 99, "action": "create"})}], None),
        auth.AuthorizationError,
        "schemaVersion",
    )


def test_validate_missing_space_for_non_create_rejected():
    install()  # no registry seeded
    orig = auth.verified_username
    try:
        _stub_actor("alice")
        raises(lambda: v.handler(_event("delete", "ghost"), None), auth.AuthorizationError, "does not exist")
    finally:
        auth.verified_username = orig


if __name__ == "__main__":
    fns = [v_ for k, v_ in sorted(globals().items()) if k.startswith("test_") and callable(v_)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} validate tests passed.")
    sys.exit(0)
