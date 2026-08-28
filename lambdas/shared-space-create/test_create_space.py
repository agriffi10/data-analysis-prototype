"""Unit tests for the create-space verb.

Runnable as a plain script or under pytest; the common layer is added to sys.path so
the verb's imports resolve locally.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import create_space as c
import registry as reg
from cpcommon import clients
from cpcommon import config as cpconfig
from fakes import install, raises


def _enable_notifications():
    """Point the emit helper at a queue so notify is no longer a no-op; return the
    FakeSqs install() already wired onto clients._sqs."""
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
    return clients._sqs


def test_create_happy_path_provisions_everything():
    s3, glue, lf, cognito = install()
    out = c.create_space("sales", "alice", "req-1")
    assert out["status"] == "active"
    assert glue.created == ["sales"]
    assert len(lf.grants) == 2
    assert cognito.attrs["custom:shared_space_1"] == "sales"
    rec = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["status"] == "active" and rec["owner"] == "alice"
    # finalize() preserves the createdAt stamped by reserve (full rewrite would drop it).
    assert rec["createdAt"]
    assert ("shared-bkt", "sales/DO_NOT_DELETE.txt") in s3.store
    cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    entry = cache["connections"][0]
    assert {k: entry[k] for k in ("name", "role", "status", "members")} == {
        "name": "sales",
        "role": "owner",
        "status": "active",
        "members": [{"username": "alice", "status": "active"}],
    }
    # createdAt is carried from the registry (a real timestamp) — just assert it's there.
    assert entry["createdAt"]


def test_create_tag_failure_records_terminal_failed():
    # add_lf_tags_to_resource reports problems in Failures (it does not raise); a
    # non-empty Failures must fail the create (recorded terminal `failed`), never a
    # silent success that leaves a DB the control-plane roles cannot use.
    s3, _glue, lf, _cognito = install()
    lf.tag_failures = [{"LFTag": {"TagKey": "portal-managed"}, "Error": {"ErrorCode": "x"}}]
    raises(lambda: c.create_space("sales", "alice", "req-1"), RuntimeError, "portal-managed")
    rec = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["status"] == "failed"
    # Tag precedes the portal-role grant, so the grant is not reached.
    assert lf.grants == []


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


def test_create_failure_after_slot_rolls_back_slot():
    install()
    from cpcommon import clients

    # The slot is assigned, then a later provisioning step fails: the except path must
    # clear the slot so a failed create doesn't leak one toward the membership cap.
    def boom(*a, **k):
        raise RuntimeError("grant failed")

    clients._lf.grant_permissions = boom
    raises(lambda: c.create_space("sales", "alice", "req-1"), RuntimeError, "grant failed")
    # Slot 1 was assigned to "sales", then rolled back to empty.
    assert clients._cognito.attrs.get("custom:shared_space_1", "") == ""
    rec = json.loads(clients._s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["status"] == "failed"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} create-space tests passed.")
    sys.exit(0)


# ── SPEC-151 FR-008: a Glue transient during create is retryable ────────────
