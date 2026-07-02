"""Unit tests for the shared-space common layer.

Runs under pytest or as a plain script (`python3 test_common.py`); the JS CI does not
run Python. Clients are faked (fakes.install); token verification is not exercised
here (it's stubbed in the validator's tests).
"""

import json

import auth
import cache
import config
import membership
import notify
import registry as reg
from fakes import install, raises, FakeUserNotFound

REG = {"name": "sales", "owner": "alice", "members": ["alice", "bob"], "status": "active"}


def test_create_allowed_for_any_actor():
    assert auth.authorize("create", "sales", "zoe", None) is None


def test_owner_only_denies_non_owner():
    raises(lambda: auth.authorize("delete", "sales", "bob", REG), auth.AuthorizationError, "owner-only")


def test_leave_denied_for_owner_and_non_member():
    raises(lambda: auth.authorize("leave", "sales", "alice", REG), auth.AuthorizationError, "owner cannot leave")
    raises(lambda: auth.authorize("leave", "sales", "mallory", REG), auth.AuthorizationError, "not a member")


def test_leave_allowed_for_member():
    assert auth.authorize("leave", "sales", "bob", REG) is None


def test_missing_space_denied():
    raises(lambda: auth.authorize("delete", "ghost", "alice", None), auth.AuthorizationError, "does not exist")


def test_unknown_action_rejected():
    raises(lambda: auth.authorize("nuke", "sales", "alice", REG), auth.AuthorizationError, "unknown action")


def test_reserve_creates_then_collides():
    s3, *_ = install()
    assert reg.reserve("sales", "alice", "req-1") == "created"
    rec = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["status"] == "provisioning" and rec["owner"] == "alice"
    # A different request for the same name collides.
    raises(lambda: reg.reserve("sales", "bob", "req-2"), reg.ProvisioningError, "name already taken")


def test_reserve_same_request_is_replay():
    s3, *_ = install()
    assert reg.reserve("sales", "alice", "req-1") == "created"
    assert reg.reserve("sales", "alice", "req-1") == "replay"


def test_reserve_owner_can_retry_own_failed():
    s3, *_ = install()
    assert reg.reserve("sales", "alice", "req-1") == "created"
    reg.finalize("sales", "alice", "req-1", "failed", "boom")
    # The owner retrying after a failed create re-reserves the name (fresh request).
    assert reg.reserve("sales", "alice", "req-2") == "created"
    rec = reg.load("sales")
    assert rec["status"] == "provisioning" and rec["lastRequestId"] == "req-2"


def test_reserve_failed_still_blocks_a_different_owner():
    s3, *_ = install()
    assert reg.reserve("sales", "alice", "req-1") == "created"
    reg.finalize("sales", "alice", "req-1", "failed", "boom")
    # A failed reservation is only retryable by its own owner; others still collide.
    raises(lambda: reg.reserve("sales", "bob", "req-2"), reg.ProvisioningError, "name already taken")


def test_finalize_and_load_roundtrip():
    s3, *_ = install()
    reg.finalize("sales", "alice", "req-1", "active")
    loaded = reg.load("sales")
    assert loaded["status"] == "active" and loaded["members"] == ["alice"]
    assert reg.load("ghost") is None


def test_save_members_and_set_status_and_delete():
    s3, *_ = install()
    base = {"name": "sales", "owner": "alice", "members": ["alice"], "status": "active", "createdAt": "t0"}
    reg.save_members(base, ["alice", "bob"], "req-2")
    rec = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["members"] == ["alice", "bob"]
    assert rec["createdAt"] == "t0"  # preserved when present
    reg.set_status(base, "deleting", "req-3")
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])["status"] == "deleting"
    reg.delete("sales")
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store


def test_save_members_heals_missing_created_at():
    s3, *_ = install()
    # A record written before createdAt was stamped.
    base = {"name": "sales", "owner": "alice", "members": ["alice"], "status": "active"}
    reg.save_members(base, ["alice", "bob"], "req-2")
    rec = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["createdAt"]  # healed, no longer blank


def test_assign_slot_then_replay_safe():
    _, _, _, cognito = install()
    cognito.users = {"bob": {}}
    assert membership.assign_or_find_slot("bob", "sales") == 1
    assert cognito.users["bob"]["custom:shared_space_1"] == "sales"
    # Re-run returns the same slot, no reassignment.
    cognito.updates.clear()
    assert membership.assign_or_find_slot("bob", "sales") == 1
    assert cognito.updates == []


def test_assign_slot_limit_raises():
    _, _, _, cognito = install(max_memberships=1)
    cognito.users = {"bob": {"custom:shared_space_1": "other"}}
    raises(lambda: membership.assign_or_find_slot("bob", "sales"), reg.ProvisioningError, "membership limit")


def test_assign_slot_unknown_user_raises():
    _, _, _, cognito = install()
    cognito.users = {"bob": {}}
    raises(lambda: membership.assign_or_find_slot("ghost", "sales"), FakeUserNotFound)


def test_clear_slot_idempotent():
    _, _, _, cognito = install()
    cognito.users = {"bob": {"custom:shared_space_2": "sales"}}
    membership.clear_slot("bob", "sales")
    assert cognito.users["bob"]["custom:shared_space_2"] == ""
    membership.clear_slot("bob", "sales")  # already cleared -> no-op
    membership.clear_slot("ghost", "sales")  # absent user -> no-op


def test_cache_upsert_remove_and_owner_projection():
    s3, *_ = install()
    cache.upsert_entry("bob", {"name": "sales", "role": "member", "status": "active"})
    cache.upsert_entry("bob", {"name": "ops", "role": "member", "status": "active"})
    conns = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])["connections"]
    assert {c["name"] for c in conns} == {"sales", "ops"}
    # Upsert by name replaces, doesn't duplicate.
    cache.upsert_entry("bob", {"name": "sales", "role": "member", "status": "failed"})
    conns = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])["connections"]
    assert sum(1 for c in conns if c["name"] == "sales") == 1
    cache.remove_entry("bob", "sales")
    conns = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])["connections"]
    assert {c["name"] for c in conns} == {"ops"}
    cache.write_owner_projection("alice", "sales", ["alice", "bob"])
    owner = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])["connections"]
    assert owner[0]["members"] == ["alice", "bob"] and owner[0]["role"] == "owner"


def test_cache_cas_retries_and_preserves_concurrent_write():
    """The fix: two overlapping executions writing the same user's cache must not
    lose-update. RacyS3 commits a competing entry between our read and our first
    write (advancing the ETag), so the conditional PutObject fails once; the CAS loop
    re-reads and reapplies, and BOTH entries survive."""
    from fakes import FakeS3
    import clients

    key = "bob/user_settings/shared-connections.json"

    class RacyS3(FakeS3):
        def __init__(self):
            super().__init__()
            self._injected = False

        def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
            if not self._injected and Key == key:
                self._injected = True  # one competing commit, before our first write
                competing = {"version": 1, "connections": [{"name": "ops", "role": "member", "status": "active"}]}
                super().put_object(Bucket=Bucket, Key=Key, Body=json.dumps(competing).encode())
            return super().put_object(Bucket, Key, Body, IfNoneMatch=IfNoneMatch, IfMatch=IfMatch, **kw)

    install()
    clients._s3 = RacyS3()
    cache.upsert_entry("bob", {"name": "sales", "role": "member", "status": "active"})
    conns = json.loads(clients._s3.store[("user-bkt", key)])["connections"]
    assert {c["name"] for c in conns} == {"sales", "ops"}, conns


def test_cache_read_treats_accessdenied_as_absent():
    """Hardening: when the role lacks s3:ListBucket, a missing object returns 403
    AccessDenied (not NoSuchKey). _read must treat that as absent and create."""
    from fakes import FakeS3, FakeClientError
    import clients

    class NoListBucketS3(FakeS3):
        def get_object(self, Bucket, Key):
            if (Bucket, Key) not in self.store:
                raise FakeClientError("AccessDenied")  # missing key, no ListBucket
            return super().get_object(Bucket, Key)

    install()
    clients._s3 = NoListBucketS3()
    cache.upsert_entry("bob", {"name": "sales", "role": "member", "status": "active"})
    conns = json.loads(clients._s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])["connections"]
    assert [c["name"] for c in conns] == ["sales"]


def test_cache_read_propagates_unexpected_error():
    """A non-absence S3 error must propagate (never silently overwrite real data)."""
    from fakes import FakeS3, FakeClientError
    import clients

    class BrokenS3(FakeS3):
        def get_object(self, Bucket, Key):
            raise FakeClientError("InternalError")

    install()
    clients._s3 = BrokenS3()
    raises(
        lambda: cache.upsert_entry("bob", {"name": "sales", "role": "member", "status": "active"}),
        FakeClientError,
    )


def test_cache_remove_absent_writes_nothing():
    """Removing from a non-existent cache stays a true no-op (no empty object written)."""
    s3, *_ = install()
    cache.remove_entry("bob", "sales")
    assert ("user-bkt", "bob/user_settings/shared-connections.json") not in s3.store


def test_notify_is_noop_when_queue_unset():
    install()  # NOTIFICATIONS_QUEUE_URL = ""
    from fakes import FakeSqs

    import clients

    clients._sqs = FakeSqs()
    notify.emit_notification("alice", "hi")
    assert clients._sqs.sent == []  # nothing sent


def test_notify_sends_when_queue_set():
    install()
    from fakes import FakeSqs

    import clients

    clients._sqs = FakeSqs()
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
    notify.emit_notification("alice", "hi", dedup_id="d1")
    assert len(clients._sqs.sent) == 1
    msg = clients._sqs.sent[0]
    assert msg["MessageGroupId"] == "alice" and msg["MessageDeduplicationId"] == "d1"
    body = json.loads(msg["MessageBody"])
    assert body == {"action": "create", "username": "alice", "message": "hi"}
    config.NOTIFICATIONS_QUEUE_URL = ""  # reset


def test_notify_swallows_errors():
    install()

    import clients

    class Boom:
        def send_message(self, **kw):
            raise RuntimeError("sqs down")

    clients._sqs = Boom()
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
    notify.emit_notification("alice", "hi")  # must not raise
    config.NOTIFICATIONS_QUEUE_URL = ""


if __name__ == "__main__":
    import sys

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} common-layer tests passed.")
    sys.exit(0)
