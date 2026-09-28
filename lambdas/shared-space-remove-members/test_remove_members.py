"""Unit tests for the remove-members verb."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import registry as remove_registry
import remove_members as r
from cpcommon.errors import TerminalError
from fakes import install, raises


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


def test_remove_members_clears_slot_registry_and_cache_leaves_data():
    s3, glue, _lf, cognito = install()
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}}
    reg = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg)
    s3.store[("user-bkt", "bob/user_settings/shared-connections.json")] = json.dumps(
        {"version": 1, "connections": [{"name": "sales", "role": "member", "status": "active"}]}
    ).encode()

    out = r.remove_members("sales", ["bob"], "req-3", reg)
    assert out["removed"] == ["bob"]
    assert cognito.users["bob"]["custom:shared_space_1"] == ""
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg2["members"] == ["alice"]
    bob_cache = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])
    assert bob_cache["connections"] == []
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert owner_cache["connections"][0]["members"] == [{"username": "alice", "status": "active"}]
    assert glue.created == []


def test_remove_members_never_removes_the_owner():
    """Defence in depth since the validator began refusing the whole request by name: the drop
    here is what made that refusal necessary — it reported success having removed nobody — and
    it stays because the verb must not depend on the predicate having run."""
    s3, _glue, _lf, _cognito = install()
    reg = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg)

    out = r.remove_members("sales", ["alice"], "req-3", reg)
    assert out["removed"] == []
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert "alice" in reg2["members"]


def test_a_removed_member_loses_their_index_entry_while_the_space_stays_active():
    # An emptied space is a legitimate, permanent state: the record stays active with no members.
    # So nothing may infer membership from status — the entry has to actually go.
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}}
    reg = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg)
    s3.store[("admin-bkt", "memberships/bob.json")] = json.dumps(
        {"version": 1, "username": "bob", "spaces": [{"name": "sales", "status": "active"}]}
    ).encode()

    r.remove_members("sales", ["bob"], "req-3", reg)

    assert json.loads(s3.store[("admin-bkt", "memberships/bob.json")])["spaces"] == []
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])["status"] == "active"


# ── FR-006: the verb refuses a refused request, and records who asked ────────


def test_a_refused_context_reaching_the_verb_is_a_TERMINAL_refusal_not_a_removal():
    """The router's Choice is the fast path; this is the fence. Reaching the handler with a
    refusal on the context means the routing did not hold, and a removal that ran anyway would
    revoke someone's access on a request the plane had already decided against."""
    s3, *_ = install()
    reg_doc = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg_doc)
    before = dict(s3.store)

    raises(
        lambda: r.handler(
            {
                "space": "sales",
                "requestId": "r1",
                "registry": reg_doc,
                "payload": {"members": ["bob"]},
                "refusal": {"code": "MemberNotOwner", "message": "no"},
            },
            None,
        ),
        TerminalError,
        "MemberNotOwner",
    )
    assert s3.store == before, "a refused removal wrote something"


def test_an_operator_driven_removal_is_attributable_to_an_actor_and_an_origin(captured_events):
    """This verb emitted no actor at all, so an operator-driven removal was attributable to
    nobody. `@traced` clears baggage per invocation, so the origin is re-stamped inside the
    handler or the span records the owner removing people from their own space."""
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}}
    reg_doc = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg_doc)

    r.handler(
        {
            "space": "sales",
            "requestId": "r1",
            "registry": reg_doc,
            "origin": "operator",
            "payload": {"members": ["bob"]},
        },
        None,
    )

    removed = [e for e in captured_events.events if e.get("message") == "members removed"]
    assert removed and removed[0]["fields"]["actor"] == "alice", removed
    origins = {
        event["fields"]["origin"]
        for event in captured_events.events
        if "origin" in (event.get("fields") or {})
    }
    assert origins == {"operator"}, f"the span recorded {origins}"


def test_the_remove_emits_a_child_span_for_the_fan_out_and_the_notifications(captured_events):
    """This verb's two bounded call sites, both around a LOOP rather than inside one.

    THE FIXTURE HAS TO MAKE BOTH LOOPS RUN, and the two loops are driven by different sets. The
    notification loop iterates the members REMOVED, so removing two covers it. The roster fan-out
    iterates the members who REMAIN, skipping the owner — so a fixture that removes everyone but
    the owner runs it zero times, and a per-member plant would emit zero spans and be caught for
    the wrong reason, then pass silently the day one member survived. Five members, two removed,
    leaves two non-owners for the fan-out to write.

    Args:
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    s3, _glue, _lf, cognito = install()
    cognito.users = {
        name: {"custom:shared_space_1": "sales"}
        for name in ("bob", "carol", "dave", "erin")
    }
    reg = _active_reg(members=["alice", "bob", "carol", "dave", "erin"])
    _seed_reg(s3, reg)

    r.handler(
        {
            "space": "sales",
            "actor": "alice",
            "requestId": "req-span",
            "registry": reg,
            "payload": {"members": ["bob", "carol"]},
        },
        None,
    )

    root = captured_events.spans("remove-members")
    assert len(root) == 1, f"expected one remove-members root span, got {len(root)}"
    for name in ("write-roster", "notify-members"):
        children = captured_events.child_spans("remove-members", name=name)
        assert len(children) == 1, (
            f"remove-members emitted {len(children)} {name!r} child spans, expected exactly one"
        )
        assert children[0]["parent_span_id"] == root[0]["span_id"]


def test_the_roster_fans_out_under_the_owner_the_commit_carries():
    # A removal carries no expected owner — it revokes rather than grants, so refusing one would
    # strand a member who slipped through. That leaves the fan-out as the only thing that can go
    # wrong here: from the validator's snapshot it told carol's members the space was alice's.
    s3, _glue, _lf, cognito = install()
    reg = _active_reg(members=["alice", "bob", "carol"])
    _seed_reg(s3, reg)
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}, "carol": {}}
    _seed_reg(s3, dict(reg, owner="carol"))

    r.remove_members("sales", ["bob"], "req-r", reg)

    alice_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert alice_cache["connections"][0]["owner"] == "carol"


def _cards(s3, *members):
    out = {}
    for m in members:
        key = ("user-bkt", f"{m}/user_settings/shared-connections.json")
        out[m] = [c["role"] for c in json.loads(s3.store[key])["connections"]] if key in s3.store else None
    return out


def test_a_remove_naming_the_member_a_transfer_just_made_owner_is_refused_before_anything_is_cleared():
    # The validator refuses a removal naming the owner, whole, because partly serving the request
    # is worse than saying so. A transfer committing after that check made one of the names the
    # owner, and the verb went on to strip the new owner of the roster, the slot and the card.
    s3, _glue, _lf, cognito = install()
    reg = _active_reg(members=["alice", "bob", "carol"])
    _seed_reg(s3, dict(reg, owner="bob"))
    cognito.users = {m: {"custom:shared_space_1": "sales"} for m in ("alice", "bob", "carol")}

    raises(
        lambda: r.remove_members("sales", ["bob", "carol"], "req-r", reg),
        remove_registry.OwnerChanged,
    )

    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["owner"] == "bob" and saved["members"] == ["alice", "bob", "carol"]
    assert {m: cognito.users[m]["custom:shared_space_1"] for m in ("bob", "carol")} == {
        "bob": "sales",
        "carol": "sales",
    }


def test_a_transfer_landing_after_the_fresh_read_gives_back_the_owner_alone(monkeypatch):
    # The roster write's refusal comes after every named slot is cleared. Only the new owner is
    # given theirs back: nothing else can re-issue it, while carol's can be re-issued by an add,
    # and giving hers back could re-grant somebody a concurrent removal had just taken off.
    s3, _glue, _lf, cognito = install()
    reg = _active_reg(members=["alice", "bob", "carol"])
    _seed_reg(s3, reg)
    cognito.users = {m: {"custom:shared_space_1": "sales"} for m in ("alice", "bob", "carol")}
    real_clear = r.membership.clear_slot
    fired = []

    def clear_then_transfer(username, name):
        real_clear(username, name)
        if not fired:
            fired.append(True)
            s3.put_object(
                Bucket="admin-bkt", Key="shared-spaces/sales.json", Body=json.dumps(dict(reg, owner="bob"))
            )

    monkeypatch.setattr(r.membership, "clear_slot", clear_then_transfer)

    raises(
        lambda: r.remove_members("sales", ["bob", "carol"], "req-r", reg),
        remove_registry.OwnerChanged,
    )

    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["owner"] == "bob" and saved["members"] == ["alice", "bob", "carol"]
    assert {m: cognito.users[m]["custom:shared_space_1"] for m in ("bob", "carol")} == {
        "bob": "sales",
        "carol": "",
    }
    assert _cards(s3, "bob", "carol") == {"bob": ["owner"], "carol": None}


def test_a_removal_committing_after_an_owner_restore_still_revokes_the_restored_slot(monkeypatch):
    # alice's removal of bob cleared his slot and stalled before its roster write. In that gap
    # the space went to bob and back, and bob's refused leave gave him his slot back while he
    # owned it. alice's write then committed against alice as owner and took bob off the roster,
    # leaving him a slot, an owner card and a grant no roster shows. A removal now revokes again
    # after its own commit, which is what makes a grant confirmed by a later read safe.
    s3, _glue, _lf, cognito = install()
    reg = _active_reg(members=["alice", "bob", "carol"])
    _seed_reg(s3, reg)
    cognito.users = {m: {"custom:shared_space_1": "sales"} for m in ("alice", "bob", "carol")}
    real_save = remove_registry.save_members
    fired = []

    def owner_goes_to_bob_and_back_first(*args, **kwargs):
        if not fired:
            fired.append(True)
            key = "shared-spaces/sales.json"
            s3.put_object(Bucket="admin-bkt", Key=key, Body=json.dumps(dict(reg, owner="bob")))
            r.membership.reinstate_owner(["bob"], "sales")
            assert cognito.users["bob"]["custom:shared_space_1"] == "sales"
            s3.put_object(Bucket="admin-bkt", Key=key, Body=json.dumps(reg))
        return real_save(*args, **kwargs)

    monkeypatch.setattr(remove_registry, "save_members", owner_goes_to_bob_and_back_first)

    out = r.remove_members("sales", ["bob"], "req-r", reg)

    assert fired and out["removed"] == ["bob"]
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])["members"] == ["alice", "carol"]
    assert cognito.users["bob"]["custom:shared_space_1"] == ""
    assert _cards(s3, "bob")["bob"] in (None, [])


def test_a_stalled_queue_holds_the_notices_for_one_deadline_not_a_cap_per_member(stalled_sends, caplog):
    """The notices run after the registry commit, so they share one budget: two start before its
    deadline and every later one is refused, where a budget per send would start them all."""
    s3, _glue, _lf, cognito = install()
    members = [f"user{i:02d}" for i in range(12)]
    cognito.users = {m: {"custom:shared_space_1": "sales"} for m in members}
    reg = _active_reg(members=["alice", *members])
    _seed_reg(s3, reg)
    stalled_sends.install()

    out = r.remove_members("sales", members, "req-3", reg)

    assert out["removed"] == members
    assert stalled_sends.started == 2
    assert stalled_sends.reasons(caplog.records) == ["notifications: a call ran past 0.05s"] * 2 + ["notifications ran out of time"] * (len(members) - 2)
