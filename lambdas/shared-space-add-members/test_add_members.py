"""Unit tests for the add-members verb."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import add_members as a
import registry as reg
from cpcommon import clients
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError
from fakes import install, raises


def _enable_notifications():
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
    return clients._sqs


def _sent(sqs):
    """(recipient, message) for each enqueued notification, in order."""
    out = []
    for m in sqs.sent:
        body = json.loads(m["MessageBody"])
        out.append((body["username"], body["message"]))
    return out


def _active_reg(name="sales", owner="alice", members=None):
    return {
        "name": name,
        "owner": owner,
        "members": members if members is not None else [owner],
        "status": "active",
        "createdAt": "t0",
        "lastRequestId": "r0",
    }


def _seed_reg(s3, reg):
    s3.store[("admin-bkt", f"shared-spaces/{reg['name']}.json")] = json.dumps(reg).encode()


def test_add_members_assigns_slot_registry_cache_and_owner_projection():
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {}}
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = a.add_members("sales", ["bob"], "req-2", reg)
    assert out["added"] == ["bob"]
    assert out["ignoredUnknown"] == [] and out["skippedAtLimit"] == []
    assert cognito.users["bob"]["custom:shared_space_1"] == "sales"
    bob_cache = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])
    # SPEC-075: bob's own entry now carries the full roster (owner active, bob pending
    # until he acks), same projection the owner sees.
    assert bob_cache["connections"] == [
        {
            "name": "sales",
            "role": "member",
            "status": "active",
            "owner": "alice",
            "members": [
                {"username": "alice", "status": "active"},
                {"username": "bob", "status": "pending"},
            ],
            "createdAt": "t0",
        }
    ]
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert set(reg2["members"]) == {"alice", "bob"} and reg2["owner"] == "alice"
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    # bob is newly added -> pending until he signs in and acks; alice (owner) is active.
    assert owner_cache["connections"][0]["members"] == [
        {"username": "alice", "status": "active"},
        {"username": "bob", "status": "pending"},
    ]


def test_add_members_skips_at_limit_target_and_still_adds_others():
    s3, _glue, _lf, cognito = install(max_memberships=2)
    cognito.users = {
        "full": {"custom:shared_space_1": "x", "custom:shared_space_2": "y"},
        "bob": {},
    }
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = a.add_members("sales", ["full", "bob"], "req-2", reg)
    assert out["skippedAtLimit"] == ["full"] and out["added"] == ["bob"]
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert set(reg2["members"]) == {"alice", "bob"}


def test_add_member_notifies_added_user():
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {}}
    sqs = _enable_notifications()
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    a.add_members("sales", ["bob"], "req-2", reg)
    assert _sent(sqs) == [("bob", 'You\'ve been added to the shared space "sales".')]


def test_added_members_get_an_index_entry_and_skipped_ones_do_not():
    # The index is written from what the registry committed, not from what was requested — an
    # unknown user and a user at their cap are both "not added", and an entry for either would
    # be an entitlement to a space they are not in.
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {}}
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = a.add_members("sales", ["bob", "nosuchuser"], "req-9", reg)
    assert out["added"] == ["bob"] and out["ignoredUnknown"] == ["nosuchuser"]

    document = json.loads(s3.store[("admin-bkt", "memberships/bob.json")])
    assert document["spaces"] == [{"name": "sales", "status": "active"}]
    assert ("admin-bkt", "memberships/nosuchuser.json") not in s3.store


# ── The three refusals, and the slots they must give back ────────────────────


def test_adding_to_an_EMPTIED_space_is_refused_and_gives_the_slot_back():
    # The window is real: delivery is ordered but executions are not, so an add authorized
    # against a live record can commit after a delete has emptied it. Without the guard the
    # member holds a live grant to a supposedly deleted space, in a record with no owner — so
    # nobody can remove them and nobody can delete it.
    s3, _glue, _lf, cognito = install()
    emptied = _active_reg(members=[])
    del emptied["owner"]
    emptied["previousOwner"] = "alice"
    emptied["emptiedAt"] = "t1"
    _seed_reg(s3, emptied)
    cognito.users = {"bob": {}}

    raises(lambda: a.add_members("sales", ["bob"], "req-a", _active_reg()), reg.SpaceHasNoOwner)

    # The slot is the grant, so leaving it assigned is worse than the state being prevented.
    assert cognito.users["bob"].get("custom:shared_space_1", "") == ""
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])["members"] == []


def test_adding_to_a_space_that_never_provisioned_is_refused():
    # `authorize` gates delete and add on ownership alone — there is no status check anywhere —
    # so without this an owner can add members to a failed create, and the slot is stamped
    # before the roster is written. That would put somebody else's data in a space the
    # destroying route is still allowed to tear down.
    s3, _glue, _lf, cognito = install()
    never_active = _active_reg()
    never_active["status"] = "failed"
    _seed_reg(s3, never_active)
    cognito.users = {"bob": {}}

    raises(lambda: a.add_members("sales", ["bob"], "req-a", never_active), reg.SpaceNeverActive)

    assert cognito.users["bob"].get("custom:shared_space_1", "") == ""


def test_a_was_active_now_failed_space_still_accepts_members():
    # The complement of the test above, and the reason the guard keys on the durable stamp
    # rather than on live status: this record is a delete that failed, its data is intact, and
    # its owner is mid-recovery. Freezing adds on it would be a regression.
    s3, _glue, _lf, cognito = install()
    recovering = _active_reg()
    recovering["status"] = "failed"
    recovering["everActive"] = True
    _seed_reg(s3, recovering)
    cognito.users = {"bob": {}}

    out = a.add_members("sales", ["bob"], "req-a", recovering)

    assert out["added"] == ["bob"]
    assert cognito.users["bob"]["custom:shared_space_1"] == "sales"


def test_the_rollback_leaves_a_member_a_concurrent_run_already_committed():
    # Assigning a slot is idempotent and hands back an existing one without writing, so a
    # re-add of somebody another run just committed lands in this run's "added" list. Revoking
    # them would take away access they legitimately hold.
    s3, _glue, _lf, cognito = install()
    emptied = _active_reg(members=["carol"])
    del emptied["owner"]
    emptied["emptiedAt"] = "t1"
    _seed_reg(s3, emptied)
    cognito.users = {"bob": {}, "carol": {"custom:shared_space_1": "sales"}}

    raises(lambda: a.add_members("sales", ["bob", "carol"], "req-a", _active_reg()), reg.SpaceHasNoOwner)

    assert cognito.users["bob"].get("custom:shared_space_1", "") == ""
    assert cognito.users["carol"]["custom:shared_space_1"] == "sales"


def test_adding_to_a_space_whose_delete_failed_AFTER_it_emptied_is_refused():
    # The one record where the owner is back but the members are gone: a fault in the delete's
    # latecomer pass restores `owner` so the space stays retryable, and that restore is what
    # makes this reachable. Without the emptied stamp being checked, the owner-present guard
    # passes and the owner can hand a NEW user live access over the previous cohort's retained
    # files — the revival this spec closes, through a door the no-owner guard does not cover.
    s3, _glue, _lf, cognito = install()
    restored = _active_reg(members=[])
    restored["status"] = "failed"
    restored["everActive"] = True
    restored["previousOwner"] = "alice"
    restored["emptiedAt"] = "t1"
    _seed_reg(s3, restored)
    cognito.users = {"mallory": {}}

    raises(lambda: a.add_members("sales", ["mallory"], "req-a", restored), reg.SpaceAlreadyEmptied)

    assert cognito.users["mallory"].get("custom:shared_space_1", "") == ""
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])["members"] == []


# ── FR-006: the verb refuses a refused request, and records who asked ────────


def test_a_refused_context_reaching_the_verb_is_a_TERMINAL_refusal_not_an_add():
    """The router's Choice sends a refused request to the notifier instead of here, so reaching
    the handler means the routing did not hold. One action over, the plane page already records
    why the same fence is not optional for a transfer; here the failure is a stranger gaining
    live access to a space's data.
    """
    s3, _glue, _lf, cognito = install()
    cognito.users = {"mallory": {}}
    reg_doc = _active_reg(members=["alice"])
    _seed_reg(s3, reg_doc)
    before = dict(s3.store)

    raises(
        lambda: a.handler(
            {
                "space": "sales",
                "requestId": "r1",
                "registry": reg_doc,
                "payload": {"members": ["mallory"]},
                "refusal": {"code": "MemberNotOwner", "message": "no"},
            },
            None,
        ),
        TerminalError,
        "MemberNotOwner",
    )
    assert s3.store == before, "a refused add wrote something"
    assert "custom:shared_space_1" not in cognito.users["mallory"]


def test_an_operator_driven_add_is_not_recorded_as_the_owner_adding_to_their_own_space(
    captured_events,
):
    """`@traced` clears observability baggage per invocation, so the origin has to be re-stamped
    inside the handler or the span describes the owner doing this to their own space."""
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {}}
    reg_doc = _active_reg(members=["alice"])
    _seed_reg(s3, reg_doc)

    a.handler(
        {
            "space": "sales",
            "requestId": "r1",
            "registry": reg_doc,
            "origin": "operator",
            "payload": {"members": ["bob"]},
        },
        None,
    )

    origins = {
        event["fields"]["origin"]
        for event in captured_events.events
        if "origin" in (event.get("fields") or {})
    }
    assert origins == {"operator"}, f"the span recorded {origins}"


def test_an_operator_add_of_an_unknown_user_still_names_them_TO_THE_OWNER():
    """The diagnostic goes to the space's owner — who, in the case that motivates an operator
    file, is exactly the person whose absence prompted it. Pinned rather than assumed, because
    it is the only channel either fact travels on, and an operator sees neither.
    """
    s3, _glue, _lf, cognito = install(max_memberships=1)
    cognito.users = {"bob": {"custom:shared_space_1": "other"}}
    sqs = _enable_notifications()
    reg_doc = _active_reg(members=["alice"])
    _seed_reg(s3, reg_doc)

    out = a.handler(
        {
            "space": "sales",
            "requestId": "r1",
            "registry": reg_doc,
            "origin": "operator",
            "payload": {"members": ["nosuchuser", "bob"]},
        },
        None,
    )

    assert out["ignoredUnknown"] == ["nosuchuser"] and out["skippedAtLimit"] == ["bob"]
    messages = [message for who, message in _sent(sqs) if who == "alice"]
    assert any("nosuchuser" in m and "no such user" in m for m in messages), messages
    assert any("bob" in m and "shared-space limit" in m for m in messages), messages


def test_the_add_emits_a_child_span_for_the_roster_fan_out_and_the_notifications(
    captured_events,
):
    """The two bounded call sites this plane has, both around a LOOP rather than inside one.

    The shared layer buys shared-space nothing: every durable operation it performs runs through
    a function its callers invoke per member or per recipient. So its spans go around the whole
    fan-out and the whole notification loop, in its own code.

    Parentage is asserted rather than presence alone: a span with a null parent is what a step
    placed where context does not reach emits, and it reads as instrumented while being
    unattributable.

    TWO members, not one, and that is the fixture doing work. Both spans wrap a loop, so with a
    single member a span around the loop and a span around its body emit exactly one span each
    and the assertion cannot tell the correct instrumentation from the prohibited kind.

    Args:
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {}, "carol": {}}
    reg_doc = _active_reg(members=["alice"])
    _seed_reg(s3, reg_doc)

    a.handler(
        {
            "space": "sales",
            "requestId": "r1",
            "registry": reg_doc,
            "payload": {"members": ["bob", "carol"]},
        },
        None,
    )

    root = captured_events.spans("add-members")
    assert len(root) == 1, f"expected one add-members root span, got {len(root)}"
    for name in ("write-roster", "notify-members"):
        children = captured_events.child_spans("add-members", name=name)
        assert len(children) == 1, (
            f"add-members emitted {len(children)} {name!r} child spans, expected exactly one"
        )
        assert children[0]["parent_span_id"] == root[0]["span_id"]


def test_a_delete_between_the_commit_and_the_fan_out_leaves_no_index_entry():
    # The grant-bearing writes land BEFORE the registry commit, so a delete that empties the
    # space after it finds the new member in the record empty_space hands back and revokes them
    # as a latecomer. Written the other way round the add re-created the entry after the
    # revocation, over a record an emptied space deliberately leaves at status "active" — which
    # the API's index source reads as a live space.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-delete"))
    import delete_space as d

    s3, _glue, _lf, cognito = install()
    cognito.users = {"alice": {}, "bob": {}}
    record = _active_reg(members=["alice"])
    record["everActive"] = True
    _seed_reg(s3, record)

    # Staged the INSTANT the commit returns, which is the only point that discriminates: hooking
    # anything later — the roster fan-out, say — puts the delete's revocation after the old index
    # write too, so the old ordering passes and the guard proves nothing.
    fired = []
    real_save = a.reg.save_members

    def commit_then_delete(*args, **kwargs):
        committed = real_save(*args, **kwargs)
        if not fired:
            fired.append(True)
            d.delete_space("sales", "alice", "req-del", json.loads(json.dumps(record)))
        return committed

    a.reg.save_members = commit_then_delete
    try:
        a.add_members("sales", ["bob"], "req-add", json.loads(json.dumps(record)))
    finally:
        a.reg.save_members = real_save

    assert fired == [True]
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])["emptiedAt"]
    assert json.loads(s3.store[("admin-bkt", "memberships/bob.json")])["spaces"] == []
    assert cognito.users["bob"].get("custom:shared_space_1", "") == ""


def test_an_add_authorized_before_a_transfer_is_refused_after_it():
    # A former owner's addition is authorized against the record the validator read. A transfer
    # landing before the commit makes it an addition to somebody else's space, so the commit
    # re-checks the owner and both grants are handed back.
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {}}
    transferred = _active_reg(members=["alice", "carol"], owner="carol")
    _seed_reg(s3, transferred)

    raises(
        lambda: a.add_members("sales", ["bob"], "req-a", _active_reg(members=["alice", "carol"])),
        reg.OwnerChanged,
    )

    assert cognito.users["bob"].get("custom:shared_space_1", "") == ""
    assert json.loads(s3.store[("admin-bkt", "memberships/bob.json")])["spaces"] == []
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])["members"] == [
        "alice",
        "carol",
    ]


def test_a_commit_that_fails_without_refusing_still_gives_the_grants_back():
    # An exhausted CAS or an S3 fault leaves exactly the orphan a refusal would: both grants
    # written, the member on no roster, so no delete's latecomer sweep will ever name them.
    # Catching only MembershipRefused left that door open once the index write moved ahead of
    # the commit.
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {}}
    record = _active_reg(members=["alice"])
    _seed_reg(s3, record)

    real_save = a.reg.save_members
    a.reg.save_members = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cas exhausted"))
    try:
        raises(lambda: a.add_members("sales", ["bob"], "req-a", record), RuntimeError, "cas exhausted")
    finally:
        a.reg.save_members = real_save

    assert cognito.users["bob"].get("custom:shared_space_1", "") == ""
    assert json.loads(s3.store[("admin-bkt", "memberships/bob.json")])["spaces"] == []


def test_an_add_committing_onto_a_deleting_record_writes_a_non_granting_entry():
    # The authorizer only lets an ACTIVE record reach this verb, so the pre-commit write can
    # only ever stamp "active". A delete that has written its deleting status but not yet
    # emptied still accepts the delta, and the API's index source stamps a tag for any entry
    # reading active — so the committed status is written back when it narrows.
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {}}
    record = _active_reg(members=["alice"])
    _seed_reg(s3, dict(record, status="deleting", everActive=True))

    a.add_members("sales", ["bob"], "req-a", record)

    entry = json.loads(s3.store[("admin-bkt", "memberships/bob.json")])["spaces"][0]
    assert entry == {"name": "sales", "status": "deleting"}


def test_an_add_that_adds_nobody_is_a_no_op_even_after_a_transfer():
    # The owner re-check sits INSIDE the addition branch. A delta that adds nobody grants
    # nothing, so it needs no re-authorization — checked outside, a request whose names were all
    # already members would turn an idempotent no-op into a refusal, and the roster would still
    # be fanned out under whichever owner the commit carries.
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {}, "carol": {}}
    stale = _active_reg(members=["alice", "bob", "carol"])
    _seed_reg(s3, dict(stale, owner="carol"))

    out = a.add_members("sales", ["bob"], "req-a", stale)

    assert out["added"] == [] and out["ignoredUnknown"] == []
    alice_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert alice_cache["connections"][0]["owner"] == "carol"


def test_a_stalled_queue_holds_the_notices_for_one_deadline_not_a_cap_per_member(stalled_sends, caplog):
    """The notices run after the registry commit, so they share one budget: two start before its
    deadline and every later one is refused, where a budget per send would start them all."""
    s3, _glue, _lf, cognito = install()
    members = [f"user{i:02d}" for i in range(12)]
    cognito.users = {m: {} for m in members}
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)
    stalled_sends.install()

    out = a.add_members("sales", members, "req-2", reg)

    reasons = stalled_sends.reasons(caplog.records)
    assert out["added"] == members
    assert stalled_sends.started == 2
    assert len(reasons) >= len(members)
    assert reasons == ["notifications: a call ran past 0.05s"] * 2 + ["notifications ran out of time"] * (len(reasons) - 2)
