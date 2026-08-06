"""Unit tests for the shared-space common layer.

Runs under pytest or as a plain script (`python3 test_common.py`); the JS CI does not
run Python. Clients are faked (fakes.install); token verification is not exercised
here (it's stubbed in the validator's tests).
"""

import json

import auth
import cache
import membership
import notify
import pytest
import registry as reg
from cpcommon import config as cpconfig
from fakes import FakeS3, FakeUserNotFound, install, raises

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


def test_acknowledge_membership_member_only():
    # SPEC-073: a member may acknowledge; the owner and non-members may not.
    assert auth.authorize("acknowledge_membership", "sales", "bob", REG) is None
    raises(
        lambda: auth.authorize("acknowledge_membership", "sales", "alice", REG),
        auth.AuthorizationError,
        "owner does not acknowledge",
    )
    raises(
        lambda: auth.authorize("acknowledge_membership", "sales", "mallory", REG),
        auth.AuthorizationError,
        "not a member",
    )


def test_effective_acknowledged_back_compat():
    # Legacy record (no `acknowledged`) -> all non-owner members treated as active.
    assert reg.effective_acknowledged(REG) == ["bob"]
    # Explicit field is honoured verbatim.
    assert reg.effective_acknowledged({**REG, "acknowledged": []}) == []
    assert reg.effective_acknowledged({**REG, "acknowledged": ["bob"]}) == ["bob"]


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
    _s3, *_ = install()
    assert reg.reserve("sales", "alice", "req-1") == "created"
    assert reg.reserve("sales", "alice", "req-1") == "replay"


def test_reserve_owner_can_retry_own_failed():
    _s3, *_ = install()
    assert reg.reserve("sales", "alice", "req-1") == "created"
    reg.finalize("sales", "alice", "req-1", "failed", "boom")
    # The owner retrying after a failed create re-reserves the name (fresh request).
    assert reg.reserve("sales", "alice", "req-2") == "created"
    rec = reg.load("sales")
    assert rec["status"] == "provisioning" and rec["lastRequestId"] == "req-2"


def test_reserve_failed_still_blocks_a_different_owner():
    _s3, *_ = install()
    assert reg.reserve("sales", "alice", "req-1") == "created"
    reg.finalize("sales", "alice", "req-1", "failed", "boom")
    # A failed reservation is only retryable by its own owner; others still collide.
    raises(lambda: reg.reserve("sales", "bob", "req-2"), reg.ProvisioningError, "name already taken")


def test_finalize_and_load_roundtrip():
    _s3, *_ = install()
    reg.finalize("sales", "alice", "req-1", "active")
    loaded = reg.load("sales")
    assert loaded["status"] == "active" and loaded["members"] == ["alice"]
    assert reg.load("ghost") is None


def test_save_members_and_set_status_and_delete():
    s3, *_ = install()
    base = {"name": "sales", "owner": "alice", "members": ["alice"], "status": "active", "createdAt": "t0"}
    reg.save_members(base, "req-2", add=["bob"])
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
    reg.save_members(base, "req-2", add=["bob"])
    rec = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["createdAt"]  # healed, no longer blank


# ── Registry write-concurrency (SPEC-082) ─────────────────────────────────────────


def test_registry_set_status_cas_preserves_concurrent_member_add():
    """FR-001: set_status's conditional write loses to a concurrent add-members that
    commits first, so it re-reads and re-applies its status change on the FRESH record —
    both changes survive (the add is not lost, and status still lands)."""
    from cpcommon import clients
    from fakes import FakeS3

    class RacyS3(FakeS3):
        _injected = False

        def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
            if not self._injected and IfMatch is not None and Key == "shared-spaces/sales.json":
                self._injected = True  # a concurrent add-members commits, advancing the ETag
                current = json.loads(self.store[(Bucket, Key)])
                current["members"] = current["members"] + ["bob"]
                super().put_object(Bucket=Bucket, Key=Key, Body=json.dumps(current).encode())
            return super().put_object(Bucket, Key, Body, IfNoneMatch=IfNoneMatch, IfMatch=IfMatch, **kw)

    install()
    clients._s3 = RacyS3()
    reg.finalize("sales", "alice", "req-1", "active")  # members=[alice], status=active
    reg.set_status(reg.load("sales"), "deleting", "req-3")
    rec = reg.load("sales")
    assert rec["status"] == "deleting"  # our change applied after the retry
    assert rec["members"] == ["alice", "bob"]  # concurrent add preserved (no lost update)


def test_registry_save_members_cas_retries_and_preserves_untouched_field():
    """FR-001: save_members re-reads fresh on a 412, so a concurrent writer's change to
    a field it doesn't touch survives while its own members change still lands."""
    from cpcommon import clients
    from fakes import FakeS3

    class RacyS3(FakeS3):
        _injected = False

        def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
            if not self._injected and IfMatch is not None and Key == "shared-spaces/sales.json":
                self._injected = True
                current = json.loads(self.store[(Bucket, Key)])
                current["extra"] = "concurrent"  # a field save_members doesn't rewrite
                super().put_object(Bucket=Bucket, Key=Key, Body=json.dumps(current).encode())
            return super().put_object(Bucket, Key, Body, IfNoneMatch=IfNoneMatch, IfMatch=IfMatch, **kw)

    install()
    clients._s3 = RacyS3()
    reg.finalize("sales", "alice", "req-1", "active")
    reg.save_members(reg.load("sales"), "req-2", add=["bob"])
    rec = reg.load("sales")
    assert rec["members"] == ["alice", "bob"]  # our change landed after the retry
    assert rec["extra"] == "concurrent"  # concurrent field survived the re-read


def test_registry_cas_exhausts_after_persistent_contention():
    """FR-001: unbounded contention raises a typed RuntimeError (non-swallowed), so the
    Step Function records a terminal failure rather than a silent success/lost write."""
    from cpcommon import clients
    from fakes import FakeS3

    class AlwaysRacyS3(FakeS3):
        def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
            if IfMatch is not None and Key == "shared-spaces/sales.json":
                current = json.loads(self.store[(Bucket, Key)])  # a competitor always wins first
                current["members"] = [*current.get("members", []), "x"]
                super().put_object(Bucket=Bucket, Key=Key, Body=json.dumps(current).encode())
            return super().put_object(Bucket, Key, Body, IfNoneMatch=IfNoneMatch, IfMatch=IfMatch, **kw)

    install()
    clients._s3 = AlwaysRacyS3()
    reg.finalize("sales", "alice", "req-1", "active")
    raises(lambda: reg.set_status(reg.load("sales"), "deleting", "req-3"), RuntimeError, "exhausted")


def test_reserve_failed_retry_is_conditional_under_contention():
    """FR-002: the owner's failed-create retry overwrites CONDITIONALLY, so a sibling
    retry that commits first makes this one 412 and re-read (not a blind double-write) —
    the loser gets a typed ProvisioningError and the sibling's record stands."""
    from cpcommon import clients
    from fakes import FakeS3

    def _as_bytes(body):
        return body if isinstance(body, (bytes, bytearray)) else body.encode()

    class RacyS3(FakeS3):
        _injected = False

        def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
            # Fire only for alice's own conditional failed-retry overwrite (req-2), not
            # for the earlier reserve/finalize writes.
            if not self._injected and IfMatch is not None and b"req-2" in _as_bytes(Body):
                self._injected = True
                sibling = {
                    "version": 1, "name": "sales", "owner": "alice", "members": ["alice"],
                    "status": "provisioning", "createdAt": "t0", "lastRequestId": "req-sibling",
                }
                super().put_object(Bucket=Bucket, Key=Key, Body=json.dumps(sibling).encode())
            return super().put_object(Bucket, Key, Body, IfNoneMatch=IfNoneMatch, IfMatch=IfMatch, **kw)

    install()
    clients._s3 = RacyS3()
    reg.reserve("sales", "alice", "req-1")
    reg.finalize("sales", "alice", "req-1", "failed", "boom")  # leaves a failed reservation
    raises(lambda: reg.reserve("sales", "alice", "req-2"), reg.ProvisioningError, "name already taken")
    assert reg.load("sales")["lastRequestId"] == "req-sibling"  # sibling stands; no double-write


# ── Shared CAS primitive (SPEC-082 FR-003) — tested independent of any caller ──────


def test_casio_precondition_detection():
    import casio
    from fakes import FakeClientError

    assert casio.is_precondition(FakeClientError("PreconditionFailed"))
    assert casio.is_precondition(FakeClientError("412"))
    assert not casio.is_precondition(FakeClientError("InternalError"))
    assert not casio.is_precondition(RuntimeError("boom"))  # no .response -> code ""


def test_casio_cas_mutate_reapplies_on_precondition():
    import casio
    from fakes import FakeClientError

    state = {"value": 0, "etag": "e0"}
    calls = {"n": 0}

    def read():
        return state["value"], state["etag"]

    def write(value, etag):
        calls["n"] += 1
        if calls["n"] == 1:
            state["value"], state["etag"] = 5, "e1"  # a competitor moved the value
            raise FakeClientError("PreconditionFailed")
        state["value"], state["etag"] = value, "e2"

    result = casio.cas_mutate(read, lambda v: v + 1, write, label="t")
    assert result == 6 and calls["n"] == 2  # re-read saw 5, applied +1


def test_casio_cas_mutate_skips_write_on_noop():
    import casio

    def write(value, etag):
        raise AssertionError("no-op must not write")

    assert casio.cas_mutate(lambda: ([1, 2], "e"), lambda v: v, write, label="t") == [1, 2]


def test_casio_cas_mutate_exhausts_and_reraises_nonprecondition():
    import casio
    from fakes import FakeClientError

    def always_412(value, etag):
        raise FakeClientError("412")

    raises(
        lambda: casio.cas_mutate(lambda: (0, "e"), lambda v: v + 1, always_412, label="t", max_attempts=3),
        RuntimeError,
        "exhausted",
    )

    def broken(value, etag):
        raise FakeClientError("InternalError")

    # A non-precondition write error propagates immediately (no retry, no swallow).
    raises(lambda: casio.cas_mutate(lambda: (0, "e"), lambda v: v + 1, broken, label="t"), FakeClientError)


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
    cache.write_owner_projection("alice", "sales", ["alice", "bob"], ["bob"])
    owner = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])["connections"]
    assert owner[0]["members"] == [
        {"username": "alice", "status": "active"},
        {"username": "bob", "status": "active"},
    ] and owner[0]["role"] == "owner"


def _conns(s3, username):
    return json.loads(s3.store[("user-bkt", f"{username}/user_settings/shared-connections.json")])["connections"]


def test_write_member_entry_carries_roster_and_status():
    """SPEC-075: a member's entry now includes the same {username,status} roster the
    owner sees, plus role/owner/createdAt."""
    s3, *_ = install()
    cache.write_member_entry("bob", "sales", "alice", ["alice", "bob", "cara"], ["bob"], "2026-07-03")
    entry = _conns(s3, "bob")[0]
    assert entry["role"] == "member" and entry["owner"] == "alice" and entry["createdAt"] == "2026-07-03"
    assert entry["members"] == [
        {"username": "alice", "status": "active"},  # owner always active
        {"username": "bob", "status": "active"},  # acknowledged
        {"username": "cara", "status": "pending"},  # not yet acked
    ]


def test_write_roster_to_all_fans_out_to_owner_and_every_member():
    """SPEC-075 FR-002: the owner and every member get the full roster; the owner is
    skipped as a member recipient (they get the owner projection, not a member entry)."""
    s3, *_ = install()
    cache.write_roster_to_all(["alice", "bob", "cara"], "sales", "alice", ["bob"])
    owner = _conns(s3, "alice")[0]
    assert owner["role"] == "owner"
    for member in ("bob", "cara"):
        entry = _conns(s3, member)[0]
        assert entry["role"] == "member" and entry["owner"] == "alice"
        assert entry["members"] == owner["members"]  # everyone sees the same roster


def test_write_roster_to_all_is_best_effort_per_member():
    """FR-002: one member's cache write failing is logged and skipped, never aborting
    the fan-out — the remaining members and the owner still get the roster."""
    from cpcommon import clients
    from fakes import FakeClientError, FakeS3

    class FlakyS3(FakeS3):
        def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
            if Key == "bob/user_settings/shared-connections.json":
                raise FakeClientError("InternalError")  # bob's cache is broken
            return super().put_object(Bucket, Key, Body, IfNoneMatch=IfNoneMatch, IfMatch=IfMatch, **kw)

    install()
    clients._s3 = FlakyS3()
    cache.write_roster_to_all(["alice", "bob", "cara"], "sales", "alice", [])
    # cara + the owner still landed despite bob failing.
    assert ("user-bkt", "cara/user_settings/shared-connections.json") in clients._s3.store
    assert ("user-bkt", "alice/user_settings/shared-connections.json") in clients._s3.store
    assert ("user-bkt", "bob/user_settings/shared-connections.json") not in clients._s3.store


def test_cache_cas_retries_and_preserves_concurrent_write():
    """The fix: two overlapping executions writing the same user's cache must not
    lose-update. RacyS3 commits a competing entry between our read and our first
    write (advancing the ETag), so the conditional PutObject fails once; the CAS loop
    re-reads and reapplies, and BOTH entries survive."""
    from cpcommon import clients
    from fakes import FakeS3

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
    from cpcommon import clients
    from fakes import FakeClientError, FakeS3

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
    from cpcommon import clients
    from fakes import FakeClientError, FakeS3

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
    from cpcommon import clients
    from fakes import FakeSqs

    clients._sqs = FakeSqs()
    notify.emit_notification("alice", "hi")
    assert clients._sqs.sent == []  # nothing sent


def test_notify_sends_when_queue_set():
    install()
    from cpcommon import clients
    from fakes import FakeSqs

    clients._sqs = FakeSqs()
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
    notify.emit_notification("alice", "hi", dedup_id="d1")
    assert len(clients._sqs.sent) == 1
    msg = clients._sqs.sent[0]
    assert msg["MessageGroupId"] == "alice" and msg["MessageDeduplicationId"] == "d1"
    body = json.loads(msg["MessageBody"])
    assert body == {"action": "create", "username": "alice", "message": "hi"}
    cpconfig.NOTIFICATIONS_QUEUE_URL = ""  # reset


def test_notify_swallows_errors():
    install()

    from cpcommon import clients

    class Boom:
        def send_message(self, **kw):
            raise RuntimeError("sqs down")

    clients._sqs = Boom()
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
    notify.emit_notification("alice", "hi")  # must not raise
    cpconfig.NOTIFICATIONS_QUEUE_URL = ""


if __name__ == "__main__":
    import sys

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} common-layer tests passed.")
    sys.exit(0)


# -- SPEC-134: the narrative -----------------------------------------------------------


def test_a_failed_roster_fan_out_names_the_stale_member_and_the_counts(captured_events):
    """FR-005. Five members, the THIRD one's cache broken — the exact shape that leaves a
    roster looking correct to four people and stale to one, invisible from either side.

    Per-member events are acceptable here and prohibited in the log sweep, and the difference
    is structural rather than a matter of taste: membership is capped at ten Cognito attribute
    slots, so this fan-out can emit at most ten events. The sweep's per-message count is
    unbounded AND it emits into the queue it drains.
    """
    from cpcommon import clients
    from fakes import FakeClientError, FakeS3

    members = ["alice", "bob", "cara", "dan", "erin"]

    class FlakyS3(FakeS3):
        def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
            if Key == "cara/user_settings/shared-connections.json":
                raise FakeClientError("InternalError")
            return super().put_object(Bucket, Key, Body, IfNoneMatch=IfNoneMatch, IfMatch=IfMatch, **kw)

    install()
    clients._s3 = FlakyS3()

    cache.write_roster_to_all(members, "sales", "alice", [])

    per_member = captured_events.messages("roster fan-out failed for one member")
    assert len(per_member) == 1
    assert per_member[0]["level"] == "WARNING"
    assert per_member[0]["fields"]["member"] == "cara"

    summary = captured_events.messages("roster fanned out")
    assert len(summary) == 1
    # alice is the owner (written separately), so the fan-out covers bob/cara/dan/erin.
    assert summary[0]["fields"]["written"] == 3
    assert summary[0]["fields"]["failed"] == 1
    assert summary[0]["fields"]["stale_members"] == ["cara"]

    # And the premise: the other four still landed.
    for member in ("bob", "dan", "erin", "alice"):
        assert ("user-bkt", f"{member}/user_settings/shared-connections.json") in clients._s3.store


def test_the_fan_out_event_count_is_bounded_by_the_slot_cap(captured_events):
    """The bound that makes per-member acceptable, asserted rather than asserted-about."""
    from cpcommon import clients

    install()
    members = [f"user{n}" for n in range(membership.config.MAX_SHARED_MEMBERSHIPS)]

    cache.write_roster_to_all(members, "sales", members[0], [])
    assert clients._s3

    assert len(captured_events.levels()) <= membership.config.MAX_SHARED_MEMBERSHIPS + 1


def test_slot_assignment_reports_the_slot_and_the_occupancy(captured_events):
    install()

    membership.assign_or_find_slot("bob", "sales")

    assigned = captured_events.messages("membership slot assigned")
    assert assigned and assigned[0]["fields"]["slot"] >= 1
    assert assigned[0]["fields"]["slots_cap"] == membership.config.MAX_SHARED_MEMBERSHIPS
    assert assigned[0]["fields"]["store"] == "cognito"


def test_slot_exhaustion_is_an_error_with_a_stable_reason(captured_events):
    """A notification cannot be counted; "how often are people hitting the cap" is a product
    question that needs a field.
    """
    from cpcommon import clients

    install()
    cap = membership.config.MAX_SHARED_MEMBERSHIPS
    # Every slot already taken by a DIFFERENT space, so no early idempotent return.
    clients._cognito.users["bob"] = {
        membership._slot_attr(k): f"space{k}" for k in range(1, cap + 1)
    }

    with pytest.raises(membership.ProvisioningError):
        membership.assign_or_find_slot("bob", "sales")

    exhausted = captured_events.messages("membership slots exhausted")
    assert exhausted and exhausted[0]["level"] == "ERROR"
    assert exhausted[0]["fields"]["reason"] == "membership-limit-reached"
    assert exhausted[0]["fields"]["slots_cap"] == cap


# ── SPEC-151 FR-003: teardown surfaces per-key failures before the name is freed ──
#
# delete_objects and batch_delete_table both return HTTP 200 with a per-item Errors
# array — a denied key does not raise. Discarding that response made a PARTIAL teardown
# indistinguishable from a complete one, and delete_space then ran reg.delete(space),
# commented "LAST — the name is now free to reuse". The next space created with that
# name would inherit another tenant's objects. SPEC-054 states as an acceptance
# criterion that teardown leaves "never a dangling … half-deleted resource".


def test_delete_shared_prefix_raises_when_a_key_could_not_be_deleted():
    import teardown

    s3, _, _, _ = install()
    s3.store[("shared-bkt", "sales/a.csv")] = b"x"
    s3.store[("shared-bkt", "sales/locked.csv")] = b"x"
    s3.undeletable.add("sales/locked.csv")

    with pytest.raises(teardown.TeardownIncompleteError) as err:
        teardown.delete_shared_prefix("sales")

    # A COUNT, never the key: this message reaches logs and the registry `failed` record,
    # and the field rule binds what a call site chooses to emit (SPEC-132).
    assert "1 object" in str(err.value)
    assert "locked.csv" not in str(err.value)


def test_delete_shared_prefix_still_deletes_everything_it_can():
    """A denial on one key must not strand the rest of the space's objects."""
    import teardown

    s3, _, _, _ = install()
    s3.store[("shared-bkt", "sales/a.csv")] = b"x"
    s3.store[("shared-bkt", "sales/locked.csv")] = b"x"
    s3.undeletable.add("sales/locked.csv")

    raises(lambda: teardown.delete_shared_prefix("sales"), teardown.TeardownIncompleteError)

    assert ("shared-bkt", "sales/a.csv") not in s3.store
    assert ("shared-bkt", "sales/locked.csv") in s3.store


def test_a_fully_successful_prefix_delete_is_silent():
    import teardown

    s3, _, _, _ = install()
    s3.store[("shared-bkt", "sales/a.csv")] = b"x"

    teardown.delete_shared_prefix("sales")

    assert ("shared-bkt", "sales/a.csv") not in s3.store


def test_drop_database_raises_before_dropping_a_db_whose_tables_survived():
    """Dropping a database whose tables survived is how the catalog and the bucket start
    disagreeing — so the raise comes BEFORE delete_database, not after."""
    import teardown

    _, glue, _, _ = install()
    glue.databases.add("sales")
    glue.tables["sales"] = ["orders", "locked"]
    glue.undroppable.add("locked")

    with pytest.raises(teardown.TeardownIncompleteError) as err:
        teardown.drop_database("sales")

    assert "1 table" in str(err.value)
    assert "locked" not in str(err.value)
    assert "sales" in glue.databases  # the database is still there


def test_a_fully_successful_database_drop_is_silent():
    import teardown

    _, glue, _, _ = install()
    glue.databases.add("sales")
    glue.tables["sales"] = ["orders"]

    teardown.drop_database("sales")

    assert "sales" not in glue.databases


# ── SPEC-153 FR-002: the continuation branches actually execute ──────────────
#
# Until now no test in the fleet mentioned ContinuationToken, NextToken or IsTruncated:
# the fakes ACCEPTED a token and ignored it, hard-coding IsTruncated: False. So the three
# continuation assignments in teardown.py and the 100-table batching had never run, in a
# teardown whose whole job is to leave nothing behind. A space large enough to paginate is
# exactly the space where a silently-truncated walk frees a name over live objects.


def test_a_prefix_spanning_several_pages_is_deleted_whole():
    """The listing walk must follow every page, not stop at the first."""
    import teardown

    s3, _, _, _ = install()
    for i in range(7):  # > page_size (2), and not a multiple of it
        s3.store[("shared-bkt", f"sales/f{i}.csv")] = b"x"

    teardown.delete_shared_prefix("sales")

    assert not [k for (b, k) in s3.store if k.startswith("sales/")]


def test_the_listing_walk_survives_deleting_each_page_as_it_goes():
    """A denial on the FIRST page must not hide the pages behind it.

    ``delete_shared_prefix`` deletes each page before requesting the next, so the walk is
    over a shrinking prefix. An offset-based continuation would skip keys here; a
    start-after marker does not. Every page is attempted before the raise, so the count is
    whole and the survivors are exactly the undeletable ones.
    """
    import teardown

    s3, _, _, _ = install()
    for i in range(7):
        s3.store[("shared-bkt", f"sales/f{i}.csv")] = b"x"
    s3.undeletable.add("sales/f0.csv")  # first page

    with pytest.raises(teardown.TeardownIncompleteError) as err:
        teardown.delete_shared_prefix("sales")

    assert "1 object" in str(err.value)
    assert [k for (b, k) in s3.store if k.startswith("sales/")] == ["sales/f0.csv"]


def test_a_database_of_more_than_a_hundred_tables_is_dropped_in_batches():
    """``batch_delete_table`` caps at 100, so the range() batching is load-bearing —
    and the tables are collected across many get_tables pages before any drop happens."""
    import teardown

    _, glue, _, _ = install()
    glue.databases.add("sales")
    glue.tables["sales"] = [f"t{i:03d}" for i in range(250)]
    batches = []
    original = glue.batch_delete_table

    def _recording(DatabaseName, TablesToDelete):
        batches.append(len(TablesToDelete))
        return original(DatabaseName=DatabaseName, TablesToDelete=TablesToDelete)

    glue.batch_delete_table = _recording

    teardown.drop_database("sales")

    assert batches == [100, 100, 50]
    assert "sales" not in glue.databases


# ── SPEC-151 FR-005: the racing 409 is a lost race, not a hard error ─────────
#
# A failed If-Match yields 412 PreconditionFailed; a failed If-None-Match: * raced
# against another create yields 409 ConditionalRequestConflict. casio matched only the
# 412, so a genuinely SIMULTANEOUS write failed hard where the sequential duplicate
# worked. Both twins (dqcommon.index_store, log-sweep) already handle 409 and explain why.


def test_is_precondition_recognises_both_the_412_and_the_racing_409():
    import casio
    from fakes import FakeClientError

    assert casio.is_precondition(FakeClientError("PreconditionFailed"))
    assert casio.is_precondition(FakeClientError("412"))
    assert casio.is_precondition(FakeClientError("ConditionalRequestConflict"))
    assert casio.is_precondition(FakeClientError("409"))
    # Anything else is still a real error and must keep propagating.
    assert not casio.is_precondition(FakeClientError("AccessDenied"))
    assert not casio.is_precondition(FakeClientError("NoSuchKey"))


def test_a_reserve_losing_a_simultaneous_create_resolves_instead_of_failing_hard():
    """The 409 path: another writer created the record between this one's read and its
    conditional put. Before the fix the ClientError escaped reserve untouched; now it
    reaches _resolve_reserve_collision, which classifies it.

    Asserted via the RESOLVER'S OWN VERDICT, not a return value: with a different owner
    holding the name the correct answer is ProvisioningError("name already taken"). That
    the caller sees that, rather than a raw ClientError, is the whole fix — a lost race
    is now a decision instead of a crash.
    """
    s3, _, _, _ = install()
    real_put = s3.put_object
    calls = {"n": 0}

    def racing_put(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
                {"name": "sales", "owner": "zoe", "status": "active", "members": ["zoe"]}
            ).encode()
            raise fakes_client_error_409()
        return real_put(**kw)

    s3.put_object = racing_put
    raises(lambda: reg.reserve("sales", "alice", "req-1"), reg.ProvisioningError, "already taken")


def test_a_reserve_losing_to_its_own_replay_is_reported_as_a_replay():
    """The same request arriving twice concurrently: the resolver recognises its own
    requestId and reports `replay` rather than failing the second delivery."""
    s3, _, _, _ = install()
    real_put = s3.put_object
    calls = {"n": 0}

    def racing_put(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
                {
                    "name": "sales",
                    "owner": "alice",
                    "status": "active",
                    "members": ["alice"],
                    "lastRequestId": "req-1",
                }
            ).encode()
            raise fakes_client_error_409()
        return real_put(**kw)

    s3.put_object = racing_put
    assert reg.reserve("sales", "alice", "req-1") == "replay"


def fakes_client_error_409():
    from fakes import FakeClientError

    return FakeClientError("ConditionalRequestConflict")


def test_cache_cas_retries_on_a_409_rather_than_re_raising():
    s3, _, _, _ = install()
    real_put = s3.put_object
    calls = {"n": 0}

    def racing_put(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise fakes_client_error_409()
        return real_put(**kw)

    s3.put_object = racing_put
    cache.upsert_entry("alice", {"name": "sales", "role": "owner", "status": "active"})

    assert calls["n"] == 2  # lost once, retried, committed
    stored = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert [c["name"] for c in stored["connections"]] == ["sales"]


# ── SPEC-151 FR-004: save_members applies a delta, never a stale roster ──────
#
# It used to take the roster the CALLER computed from event["registry"] — a snapshot read
# before the request began — and assign it over the freshly-read record. So the CAS
# re-read the record and then overwrote the one field it exists to protect. Nothing
# serializes these requests: the Pipe is FIRE_AND_FORGET and the group id is one global
# constant, which casio's own module docstring says outright.


class _EtagRotatingS3(FakeS3):
    """Commits a concurrent writer's change between the read and the conditional put.

    Drives the CAS through a real second pass: the first If-Match write loses to a
    record that changed underneath it, so `apply` runs again against the NEW value. A
    delta survives that; a computed roster does not.
    """

    def __init__(self, mutate):
        super().__init__()
        self._mutate = mutate
        self._injected = False

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
        if not self._injected and IfMatch is not None and Key == "shared-spaces/sales.json":
            self._injected = True
            current = json.loads(self.store[(Bucket, Key)])
            super().put_object(
                Bucket=Bucket, Key=Key, Body=json.dumps(self._mutate(current)).encode()
            )
        return super().put_object(Bucket, Key, Body, IfNoneMatch=IfNoneMatch, IfMatch=IfMatch, **kw)


def _seed_registry(s3, members, **over):
    record = {
        "name": "sales",
        "owner": "alice",
        "members": list(members),
        "status": "active",
        "createdAt": "t0",
        **over,
    }
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(record).encode()
    return record


def test_an_add_does_not_undo_a_concurrent_remove():
    """THE defect. Two overlapping requests on one space were last-write-wins: the add
    wrote back a roster computed before the remove happened, reinstating the removed
    member."""
    from cpcommon import clients

    install()

    def concurrent_remove(record):
        record["members"] = [m for m in record["members"] if m != "carol"]
        return record

    s3 = _EtagRotatingS3(concurrent_remove)
    clients._s3 = s3
    snapshot = _seed_registry(s3, ["alice", "carol"])

    reg.save_members(snapshot, "req-add", add=["bob"])

    committed = reg.load("sales")
    # Both took effect: carol's removal survived, bob's addition landed.
    assert committed["members"] == ["alice", "bob"]


def test_a_remove_does_not_undo_a_concurrent_add():
    """The other interleaving."""
    from cpcommon import clients

    install()

    def concurrent_add(record):
        record["members"] = [*record["members"], "dave"]
        return record

    s3 = _EtagRotatingS3(concurrent_add)
    clients._s3 = s3
    snapshot = _seed_registry(s3, ["alice", "carol"])

    reg.save_members(snapshot, "req-remove", remove=["carol"])

    committed = reg.load("sales")
    assert committed["members"] == ["alice", "dave"]


def test_a_membership_write_does_not_revive_a_deleting_space():
    """status used to be forced to "active" on every membership write, so a request racing
    a delete returned a `deleting` space to `active` — and the cascade then ran against a
    record claiming to be healthy."""
    s3, *_ = install()
    snapshot = _seed_registry(s3, ["alice", "bob"])
    reg.set_status(snapshot, "deleting", "req-del")

    reg.save_members(snapshot, "req-add", add=["carol"])

    assert reg.load("sales")["status"] == "deleting"


def test_a_newly_added_member_is_pending_not_acknowledged():
    """SPEC-073 is unchanged by the delta. The ordering inside `apply` is load-bearing: a
    pre-SPEC-073 record has no `acknowledged` field, so reading effective_acknowledged
    AFTER the add would sweep the new member in and show them active immediately."""
    s3, *_ = install()
    snapshot = _seed_registry(s3, ["alice", "bob"])  # no `acknowledged` key

    committed = reg.save_members(snapshot, "req-add", add=["carol"])

    assert "bob" in committed["acknowledged"]  # pre-073 member, treated as acknowledged
    assert "carol" not in committed["acknowledged"]  # newly added -> pending


def test_a_removed_member_drops_out_of_acknowledged_too():
    """So a later re-add starts them at `pending` again."""
    s3, *_ = install()
    snapshot = _seed_registry(s3, ["alice", "bob"], acknowledged=["bob"])

    committed = reg.save_members(snapshot, "req-remove", remove=["bob"])

    assert committed["members"] == ["alice"]
    assert committed["acknowledged"] == []


def test_acknowledging_a_membership_a_concurrent_remove_revoked_does_not_recreate_it():
    """The acknowledge verb is the fourth caller, and the only one that ADDS to
    acknowledged. It must not resurrect a membership that no longer exists."""
    from cpcommon import clients

    install()

    def concurrent_remove(record):
        record["members"] = [m for m in record["members"] if m != "bob"]
        return record

    s3 = _EtagRotatingS3(concurrent_remove)
    clients._s3 = s3
    snapshot = _seed_registry(s3, ["alice", "bob"], acknowledged=[])

    committed = reg.save_members(snapshot, "req-ack", acknowledge=["bob"])

    assert committed["members"] == ["alice"]
    assert "bob" not in committed["acknowledged"]


# ── SPEC-151 FR-008: Glue transients on the shared-space paths ──────────────


def _glue_raising(code):
    """A FakeGlue whose get_tables raises a botocore-shaped fault."""
    import types as _types

    from fakes import FakeEntityNotFound

    class _Boom(Exception):
        def __init__(self):
            super().__init__(code)
            self.response = {"Error": {"Code": code}}

    class _Glue:
        exceptions = _types.SimpleNamespace(
            EntityNotFoundException=FakeEntityNotFound, AlreadyExistsException=Exception
        )

        def get_tables(self, DatabaseName, NextToken=None):
            raise _Boom()

        def create_database(self, DatabaseInput):
            raise _Boom()

    return _Glue()


def test_drop_database_maps_a_glue_transient_so_the_cascade_can_retry():
    """A Glue hiccup here is worse than elsewhere: a failed cascade deliberately does NOT
    free the name (FR-003), so an unmapped transient left the user with a space stuck in
    `failed` over something the state machine's Retry would have absorbed."""
    import teardown
    from cpcommon import clients
    from cpcommon.errors import TransientError

    install()
    clients._glue = _glue_raising("InternalServiceException")

    with pytest.raises(TransientError):
        teardown.drop_database("sales")


def test_drop_database_leaves_a_deterministic_glue_fault_alone():
    """Retrying InvalidInputException changes nothing — it must not be dressed as transient."""
    import teardown
    from cpcommon import clients
    from cpcommon.errors import TransientError

    install()
    clients._glue = _glue_raising("InvalidInputException")

    # The TYPE is the assertion here, and it is a negative one: whatever propagates, it must
    # not have been dressed as retryable. `match=` still pins that the original Glue fault is
    # what came back rather than some unrelated failure on the way to it.
    with pytest.raises(Exception, match="InvalidInputException") as err:
        teardown.drop_database("sales")
    assert not isinstance(err.value, TransientError)
