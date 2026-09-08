"""Unit tests for the remove-members verb."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

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

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} remove-members tests passed.")
    sys.exit(0)


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
