"""Unit tests for the create-space verb.

Runnable as a plain script or under pytest; the common layer is added to sys.path so
the verb's imports resolve locally.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

from cpcommon import clients  # noqa: E402
from cpcommon import config as cpconfig  # noqa: E402
import create_space as c  # noqa: E402
import registry as reg  # noqa: E402
from fakes import install, raises  # noqa: E402


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


def test_create_tags_database_portal_managed():
    # The shared DB is tagged portal-managed=true so the control-plane execution roles
    # get CREATE_TABLE on it via TBAC (they are granted on the tag, not per-DB).
    _s3, _glue, lf, _cognito = install()
    c.create_space("sales", "alice", "req-1")
    assert lf.lf_tags == [
        ({"Database": {"Name": "sales"}}, [{"TagKey": "portal-managed", "TagValues": ["true"]}])
    ]


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


def test_create_slot_assignment_is_replay_safe():
    install(cognito_attrs={"custom:shared_space_2": "sales"})
    from cpcommon import clients

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


def test_create_success_notifies_creator_ready():
    install()
    sqs = _enable_notifications()
    c.create_space("sales", "alice", "req-1")
    assert len(sqs.sent) == 1
    msg = sqs.sent[0]
    assert msg["MessageGroupId"] == "alice"
    assert msg["MessageDeduplicationId"] == "req-1:create-active:alice"
    body = json.loads(msg["MessageBody"])
    assert body == {
        "action": "create",
        "username": "alice",
        "message": 'Your shared workspace "sales" is ready.',
    }


def test_create_failure_notifies_creator_with_reason():
    install(
        cognito_attrs={"custom:shared_space_1": "a", "custom:shared_space_2": "b"},
        max_memberships=2,
    )
    sqs = _enable_notifications()
    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.ProvisioningError, "membership limit")
    assert len(sqs.sent) == 1
    body = json.loads(sqs.sent[0]["MessageBody"])
    assert body["username"] == "alice"
    assert body["message"].startswith('We couldn\'t create shared workspace "sales":')
    assert "membership limit reached" in body["message"]


def test_create_failure_scrubs_raw_aws_error_from_notification_and_cache():
    # SPEC-106 FR-009: a raw AWS/boto failure (not a deliberate ProvisioningError)
    # must NOT leak into the actor's notification or the cache `reason` the
    # Connections card shows — but the registry `failed` record keeps it for operators.
    s3, *_ = install()
    from cpcommon import clients

    clients._lf.grant_permissions = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("AccessDenied on glue:xyz"))
    sqs = _enable_notifications()
    raises(lambda: c.create_space("sales", "alice", "req-1"), RuntimeError, "AccessDenied")

    body = json.loads(sqs.sent[0]["MessageBody"])
    assert "AccessDenied" not in body["message"]
    assert "contact the Administrator" in body["message"]
    entry = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])["connections"][0]
    assert entry["status"] == "failed" and "AccessDenied" not in entry["reason"]
    # The registry keeps the raw reason for operators.
    rec = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["status"] == "failed" and "AccessDenied" in rec["reason"]


def test_create_collision_notifies_creator_and_leaves_record():
    s3, *_ = install()
    sqs = _enable_notifications()
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "bob", "lastRequestId": "other", "status": "active"}
    ).encode()
    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.ProvisioningError, "name already taken")
    # A reserve collision still notifies the actor...
    assert len(sqs.sent) == 1
    body = json.loads(sqs.sent[0]["MessageBody"])
    assert body["username"] == "alice"
    assert body["message"].startswith('We couldn\'t create shared workspace "sales":')
    assert "name already taken" in body["message"]
    # ...but must NOT rewrite the colliding owner's registry record.
    rec = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["owner"] == "bob" and rec["status"] == "active"


def test_create_collision_marks_actor_cache_failed():
    s3, *_ = install()
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "bob", "lastRequestId": "other", "status": "active"}
    ).encode()
    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.ProvisioningError, "name already taken")
    # The actor's OWN cache entry is marked failed (so the phantom `provisioning` the
    # validator wrote becomes a dismissible `failed`) — without touching bob's record.
    entry = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])["connections"][0]
    assert entry["name"] == "sales" and entry["status"] == "failed"
    assert "name already taken" in entry["reason"]
    rec = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["owner"] == "bob" and rec["status"] == "active"


def test_create_owner_retry_after_failure_succeeds():
    s3, glue, *_ = install()
    # A prior failed attempt left a failed reservation owned by alice.
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "alice", "lastRequestId": "old", "status": "failed", "reason": "boom"}
    ).encode()
    out = c.create_space("sales", "alice", "req-2")
    assert out["status"] == "active"
    rec = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["status"] == "active" and rec["lastRequestId"] == "req-2"
    assert glue.created == ["sales"]


def test_create_replay_emits_nothing():
    s3, *_ = install()
    sqs = _enable_notifications()
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "alice", "lastRequestId": "req-1", "status": "active"}
    ).encode()
    c.create_space("sales", "alice", "req-1")  # replay of an already-active create
    assert sqs.sent == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} create-space tests passed.")
    sys.exit(0)
