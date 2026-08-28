"""Unit tests for the validate-authorize Lambda (token verification is stubbed)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import auth
import validate as v
from cpcommon import clients
from cpcommon import config as cpconfig
from fakes import install, raises


def _enable_notifications():
    """Point the emit helper at a queue so notify is no longer a no-op; return the
    FakeSqs install() already wired onto clients._sqs."""
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
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


# Intent recording: the durable pending cache entry + start notification (create/delete).


if __name__ == "__main__":
    fns = [v_ for k, v_ in sorted(globals().items()) if k.startswith("test_") and callable(v_)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} validate tests passed.")
    sys.exit(0)
