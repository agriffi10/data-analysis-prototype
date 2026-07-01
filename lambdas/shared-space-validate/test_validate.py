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
import cache  # noqa: E402
import clients  # noqa: E402
import config  # noqa: E402
import validate as v  # noqa: E402
from fakes import install, raises  # noqa: E402


def _enable_notifications():
    """Point the emit helper at a queue so notify is no longer a no-op; return the
    FakeSqs install() already wired onto clients._sqs."""
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
    return clients._sqs


_PENDING_KEY = ("user-bkt", "alice/user_settings/shared-connections.json")


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


# ── Durable pending record + "creating…" notification (create only) ──────────
def test_validate_create_records_pending_and_notifies():
    s3, *_ = install()
    sqs = _enable_notifications()
    orig = auth.verified_username
    try:
        _stub_actor("alice")
        ctx = v.handler(_event("create", "sales"), None)
        # Still returns the same validated context — no contract change.
        assert ctx["action"] == "create" and ctx["actor"] == "alice" and ctx["registry"] is None
        # The space is durably recorded as `provisioning` in the creator's cache.
        entry = json.loads(s3.store[_PENDING_KEY])["connections"][0]
        assert entry == {"name": "sales", "role": "owner", "status": "provisioning"}
        # ...and paired with a "creating…" notification to the creator.
        assert len(sqs.sent) == 1
        msg = sqs.sent[0]
        assert msg["MessageGroupId"] == "alice"
        assert msg["MessageDeduplicationId"] == "r1:create-pending:alice"
        assert json.loads(msg["MessageBody"]) == {
            "action": "create",
            "username": "alice",
            "message": 'Creating shared workspace "sales"…',
        }
    finally:
        auth.verified_username = orig


def test_validate_delete_records_deleting_and_notifies():
    s3, *_ = install()
    _seed_reg(s3, name="sales", owner="alice", members=("alice", "bob"))
    sqs = _enable_notifications()
    orig = auth.verified_username
    try:
        _stub_actor("alice")  # the owner (delete is owner-only)
        ctx = v.handler(_event("delete", "sales"), None)
        assert ctx["action"] == "delete" and ctx["actor"] == "alice"
        # The owner's card shows a durable `deleting` state instead of flipping to active.
        entry = json.loads(s3.store[_PENDING_KEY])["connections"][0]
        assert entry == {"name": "sales", "role": "owner", "status": "deleting"}
        assert len(sqs.sent) == 1
        msg = sqs.sent[0]
        assert msg["MessageDeduplicationId"] == "r1:delete-pending:alice"
        assert json.loads(msg["MessageBody"]) == {
            "action": "create",
            "username": "alice",
            "message": 'Deleting shared workspace "sales"…',
        }
    finally:
        auth.verified_username = orig


def test_validate_non_owner_delete_records_nothing():
    s3, *_ = install()
    _seed_reg(s3, name="sales", owner="alice", members=["alice"])
    sqs = _enable_notifications()
    orig = auth.verified_username
    try:
        _stub_actor("mallory")  # not the owner — authorize raises before any side effect
        raises(lambda: v.handler(_event("delete", "sales"), None), auth.AuthorizationError, "owner-only")
        assert ("user-bkt", "mallory/user_settings/shared-connections.json") not in s3.store
        assert sqs.sent == []
    finally:
        auth.verified_username = orig


def test_validate_non_create_records_nothing():
    s3, *_ = install()
    _seed_reg(s3, members=["alice"])
    sqs = _enable_notifications()
    orig = auth.verified_username
    try:
        _stub_actor("alice")  # owner
        v.handler(_event("add_members", "sales", members=["bob"]), None)
        # Non-create actions target an existing space already in the cache — the
        # validator writes/notifies nothing (the verb owns those side effects).
        assert _PENDING_KEY not in s3.store
        assert sqs.sent == []
    finally:
        auth.verified_username = orig


def test_validate_pending_cache_failure_does_not_block_create():
    install()
    sqs = _enable_notifications()
    orig_actor = auth.verified_username
    orig_pending = cache.write_owner_pending
    try:
        _stub_actor("alice")

        def boom(*a, **k):
            raise RuntimeError("s3 down")

        cache.write_owner_pending = boom
        # A failed pending write is swallowed: the create still validates AND the
        # "creating…" notification still fires (the active/failed write is the backstop).
        ctx = v.handler(_event("create", "sales"), None)
        assert ctx["action"] == "create" and ctx["actor"] == "alice"
        assert len(sqs.sent) == 1
        assert sqs.sent[0]["MessageDeduplicationId"] == "r1:create-pending:alice"
    finally:
        auth.verified_username = orig_actor
        cache.write_owner_pending = orig_pending


def test_validate_forged_token_records_nothing():
    s3, *_ = install()
    sqs = _enable_notifications()
    orig = auth.verified_username
    try:
        def boom(tok):
            raise auth.AuthorizationError("token verification failed")

        auth.verified_username = boom
        raises(lambda: v.handler(_event("create"), None), auth.AuthorizationError, "verification failed")
        # Verification precedes the pending write, so a forged token records nothing.
        assert _PENDING_KEY not in s3.store
        assert sqs.sent == []
    finally:
        auth.verified_username = orig


if __name__ == "__main__":
    fns = [v_ for k, v_ in sorted(globals().items()) if k.startswith("test_") and callable(v_)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} validate tests passed.")
    sys.exit(0)
