"""Unit tests for the forget verb (durable "clear from my list")."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import forget_space as f
import membership_index as forget_membership_index
import registry as forget_registry
from auth import AuthorizationError
from fakes import install, raises


def _seed_cache(s3, user, entries):
    s3.store[("user-bkt", f"{user}/user_settings/shared-connections.json")] = json.dumps(
        {"version": 1, "connections": entries}
    ).encode()


def _cache(s3, user):
    return json.loads(s3.store[("user-bkt", f"{user}/user_settings/shared-connections.json")])["connections"]


# Cache-only: collision phantom (no registry record for the actor to own).
def test_forget_phantom_removes_only_actor_entry_and_slot():
    s3, _glue, _lf, cognito = install()
    cognito.users = {"alice": {"custom:shared_space_1": "sales"}}
    _seed_cache(s3, "alice", [{"name": "sales", "role": "owner", "status": "failed", "reason": "name already taken"}])

    out = f.forget_space("sales", "alice", "req-f", None)  # registry None -> phantom
    assert out["mode"] == "cache_only"
    assert _cache(s3, "alice") == []                         # entry gone
    assert cognito.users["alice"]["custom:shared_space_1"] == ""  # slot cleared


# Teardown: the actor's own failed create.
def test_forget_own_failed_space_tears_down_resources_and_frees_name():
    s3, glue, _lf, cognito = install()
    cognito.users = {"alice": {"custom:shared_space_1": "sales"}}
    registry = {"name": "sales", "owner": "alice", "members": ["alice"], "status": "failed", "reason": "boom"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    s3.store[("shared-bkt", "sales/DO_NOT_DELETE.txt")] = b"marker"
    glue.seed_space_database("sales", ["t1"])
    _seed_cache(s3, "alice", [{"name": "sales", "role": "owner", "status": "failed", "reason": "boom"}])

    out = f.forget_space("sales", "alice", "req-f", registry)
    assert out["mode"] == "teardown"
    assert not any(b == "shared-bkt" and k.startswith("sales/") for (b, k) in s3.store)  # prefix gone
    assert "sales" not in glue.databases                       # DB dropped
    assert cognito.users["alice"]["custom:shared_space_1"] == ""  # slot cleared
    assert _cache(s3, "alice") == []                           # cache entry gone
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store  # registry deleted -> name freed


# Teardown: a never-active record can still carry MULTIPLE members — a create that was added to
# before additions were refused on a space that never provisioned. Those records reach this
# branch, so the old "a failed create is single-member" reasoning never covered it, and the
# assertions below are what guard them. A slot still holding the name after reg.delete has freed it
# is a principal tag on whatever gets created under that name next, because the portal role's
# shared-space policy is scoped on the tag VALUE, not on any space identity.
#
# The state is sampled AT reg.delete rather than after it, so the ORDER is asserted too: clearing
# after the name is freed would leave the same end state here but, on a fault partway through,
# would free the name with tags still standing — which is the bug itself, reintroduced.
def test_forget_multi_member_failed_space_clears_every_slot_BEFORE_the_name_is_freed():
    members = ("alice", "bob", "carol")
    s3, glue, _lf, cognito = install()
    cognito.users = {m: {"custom:shared_space_1": "sales"} for m in members}
    registry = {
        "name": "sales",
        "owner": "alice",
        "members": list(members),
        "status": "failed",
        "reason": "teardown left objects behind",
    }
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    s3.store[("shared-bkt", "sales/DO_NOT_DELETE.txt")] = b"marker"
    glue.seed_space_database("sales", ["t1"])
    for m in members:
        _seed_cache(s3, m, [{"name": "sales", "role": "owner" if m == "alice" else "member", "status": "active"}])

    at_delete = {}
    real_delete = forget_registry.delete

    def watching_delete(name):
        at_delete.update({m: (cognito.users[m]["custom:shared_space_1"], _cache(s3, m)) for m in members})
        return real_delete(name)

    forget_registry.delete = watching_delete
    try:
        out = f.forget_space("sales", "alice", "req-f", registry)
    finally:
        forget_registry.delete = real_delete

    assert out["mode"] == "teardown"
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store  # name freed for reuse
    assert at_delete == {m: ("", []) for m in members}, at_delete


# A fault anywhere in the fan-out must leave the ACTOR's card standing. That card is the only
# row the Connections page renders, so it is the sole affordance for asking again — without it
# the space is torn down, still holding its name via the surviving registry record, and
# invisible to the one user who could retry. The other members' cards are already gone, which
# is correct: their access is what was being withdrawn.
def test_forget_teardown_fault_leaves_the_actors_card_so_the_verb_can_be_retried():
    members = ("alice", "bob")
    s3, glue, _lf, cognito = install()
    cognito.users = {m: {"custom:shared_space_1": "sales"} for m in members}
    registry = {"name": "sales", "owner": "alice", "members": list(members), "status": "failed"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    glue.seed_space_database("sales")
    for m in members:
        _seed_cache(s3, m, [{"name": "sales", "role": "owner" if m == "alice" else "member", "status": "active"}])

    real_drop_for_all = forget_membership_index.drop_for_all
    forget_membership_index.drop_for_all = lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("index unreadable"))
    try:
        raises(lambda: f.forget_space("sales", "alice", "req-f", registry), RuntimeError, "index unreadable")
    finally:
        forget_membership_index.drop_for_all = real_drop_for_all

    assert ("admin-bkt", "shared-spaces/sales.json") in s3.store   # name still locked, not freed
    assert _cache(s3, "alice") != []                               # actor keeps the retry affordance
    assert _cache(s3, "bob") == []                                 # member's access already withdrawn


# The index fan-out takes the same roster as the slot loop, not the bare `members` list, so the
# two cannot disagree about who held a claim. They differ only for a record whose `members` omits
# its own owner — which nothing writes today, so this pins the defence rather than a live path.
# It matters because the index is the tag source once it supersedes the Cognito slots: a stale
# index entry for a freed name is the same entitlement hole through the other store.
def test_forget_teardown_index_fanout_covers_the_owner_even_if_members_omits_them():
    s3, glue, _lf, cognito = install()
    cognito.users = {m: {"custom:shared_space_1": "sales"} for m in ("alice", "bob")}
    registry = {"name": "sales", "owner": "alice", "members": ["bob"], "status": "failed"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    glue.seed_space_database("sales")
    for m in ("alice", "bob"):
        s3.store[("admin-bkt", f"memberships/{m}.json")] = json.dumps(
            {"version": 1, "username": m, "spaces": [{"name": "sales", "status": "active"}]}
        ).encode()
        _seed_cache(s3, m, [{"name": "sales", "role": "owner" if m == "alice" else "member", "status": "active"}])

    f.forget_space("sales", "alice", "req-f", registry)

    for m in ("alice", "bob"):
        assert json.loads(s3.store[("admin-bkt", f"memberships/{m}.json")])["spaces"] == [], f"{m} still indexed"


# Refuse: a healthy active space the actor belongs to.
def test_forget_refuses_active_space_owner():
    s3, glue, _lf, _cognito = install()
    registry = {"name": "sales", "owner": "alice", "members": ["alice"], "status": "active"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    glue.seed_space_database("sales")
    raises(lambda: f.forget_space("sales", "alice", "req-f", registry), AuthorizationError, "active")
    # Nothing torn down.
    assert ("admin-bkt", "shared-spaces/sales.json") in s3.store
    assert "sales" in glue.databases


def test_forget_refuses_an_active_space_on_a_string_roster_it_cannot_membership_test():
    """The forget verb is its own authorizer, and its roster read is the third of three.

    ``auth.authorize`` returns early for ``forget``, so this refusal is the whole gate — and its
    polarity is the opposite of the authorizer's. There the refusal fires when the actor is NOT
    a member, so an unreadable roster read as empty refuses everybody and fails closed. Here it
    fires when the actor IS one, so the same empty reading refuses nobody and tears into the
    cache-only path, which clears the actor's slot and index on a live space. Reading the roster
    through the shared normaliser alone would therefore have replaced a substring match with a
    silent skip.

    The reason is asserted rather than the exception class: both refusals in this branch raise
    ``AuthorizationError`` and both sentences contain "active", so a test that caught either
    would pass against a verb that took the wrong one.
    """
    s3, glue, _lf, _cognito = install()
    registry = {"name": "sales", "owner": "alice", "members": "alice,bob", "status": "active"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    glue.seed_space_database("sales")

    raises(
        lambda: f.forget_space("sales", "ali", "req-f", registry),
        AuthorizationError,
        "roster cannot be read",
    )

    assert ("admin-bkt", "shared-spaces/sales.json") in s3.store
    assert "sales" in glue.databases


def test_forget_clears_a_card_for_an_EMPTIED_space_which_is_active_with_a_blank_roster():
    """The record shape that tells the two roster helpers apart, in the verb that must not confuse them.

    ``empty_space`` writes ``members: []`` with ``status: "active"`` and the owner popped, so an
    emptied space is live, readable, and names nobody. Reading it with ``roster`` instead of
    ``roster_is_readable`` collapses "nobody is a member" into "the roster could not be read" and
    refuses the forget — which strands the card of everyone left holding one, and there is no
    second door, since forget is not an operator action. That confusion is the single mistake the
    two-helper split exists to prevent, and this is the only fixture in the repo that sees it.
    """
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}}
    registry = {
        "name": "sales",
        "members": [],
        "acknowledged": [],
        "status": "active",
        "previousOwner": "alice",
        "emptiedAt": "t1",
    }
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()

    result = f.forget_space("sales", "bob", "req-f", registry)

    assert result["mode"] == "cache_only"
    assert cognito.users["bob"].get("custom:shared_space_1", "") == ""


def test_forget_tears_down_a_never_active_space_whose_roster_is_unreadable():
    """The new refusal is narrowed to an ACTIVE space, and the narrowing is load-bearing.

    Dropping the ``status == "active"`` half would widen the refusal across the teardown and
    cache-only paths — the two that exist to clear a card nobody else can — and it would widen in
    the denying direction, which is the one that costs a user something.
    """
    s3, glue, _lf, cognito = install()
    cognito.users = {"alice": {"custom:shared_space_1": "sales"}}
    registry = {"name": "sales", "owner": "alice", "members": "alice", "status": "failed"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    glue.seed_space_database("sales")

    result = f.forget_space("sales", "alice", "req-f", registry)

    assert result["mode"] == "teardown"
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store


def test_forget_still_refuses_a_real_member_of_a_live_space():
    """The positive control: a well-formed roster keeps the refusal it always had."""
    s3, glue, _lf, _cognito = install()
    registry = {"name": "sales", "owner": "alice", "members": ["alice", "bob"], "status": "active"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    glue.seed_space_database("sales")

    raises(
        lambda: f.forget_space("sales", "bob", "req-f", registry),
        AuthorizationError,
        "use Delete (owner) or Leave (member)",
    )


def test_forget_clears_the_index_on_the_teardown_path():
    s3, _glue, _lf, cognito = install()
    cognito.users = {"alice": {"custom:shared_space_1": "sales"}}
    registry = {"name": "sales", "owner": "alice", "members": ["alice"], "status": "failed"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    s3.store[("admin-bkt", "memberships/alice.json")] = json.dumps(
        {"version": 1, "username": "alice", "spaces": [{"name": "sales", "status": "active"}]}
    ).encode()
    _seed_cache(s3, "alice", [{"name": "sales", "role": "owner", "status": "failed"}])

    assert f.forget_space("sales", "alice", "req-f", registry)["mode"] == "teardown"
    assert json.loads(s3.store[("admin-bkt", "memberships/alice.json")])["spaces"] == []


def test_forget_teardown_clears_EVERY_members_index_because_it_frees_the_name():
    # A never-active record can keep several members — one added before additions to an
    # unprovisioned space were refused — so "a failed create is single-member" never covered
    # every case that lands here. reg.delete frees the name, and an index still naming a space
    # whose name is free is an entitlement to whatever gets created next.
    s3, glue, _lf, cognito = install()
    cognito.users = {"alice": {"custom:shared_space_1": "sales"}, "bob": {"custom:shared_space_1": "sales"}}
    registry = {"name": "sales", "owner": "alice", "members": ["alice", "bob"], "status": "failed"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    for member in ("alice", "bob"):
        s3.store[("admin-bkt", f"memberships/{member}.json")] = json.dumps(
            {"version": 1, "username": member, "spaces": [{"name": "sales", "status": "active"}]}
        ).encode()
    _seed_cache(s3, "alice", [{"name": "sales", "role": "owner", "status": "failed"}])
    glue.seed_space_database("sales")

    assert f.forget_space("sales", "alice", "req-f", registry)["mode"] == "teardown"
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store
    for member in ("alice", "bob"):
        assert json.loads(s3.store[("admin-bkt", f"memberships/{member}.json")])["spaces"] == []


def test_forget_clears_the_index_on_the_cache_only_path_too():
    # The cache-only path leaves the REGISTRY alone by design. Leaving the entitlement behind is
    # a different thing, and it is not the design: the slot is cleared here, so the index is too.
    s3, _glue, _lf, cognito = install()
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}}
    s3.store[("admin-bkt", "memberships/bob.json")] = json.dumps(
        {"version": 1, "username": "bob", "spaces": [{"name": "sales", "status": "active"}]}
    ).encode()
    _seed_cache(s3, "bob", [{"name": "sales", "role": "member", "status": "active"}])

    assert f.forget_space("sales", "bob", "req-f", None)["mode"] == "cache_only"
    assert json.loads(s3.store[("admin-bkt", "memberships/bob.json")])["spaces"] == []
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store


def test_forget_as_the_OWNER_of_a_was_active_now_failed_space_tears_down_NOTHING():
    # THE data-loss path. A delete that fails partway leaves a live workspace in `failed`, and
    # the Connections page renders Dismiss on any failed row — which is this verb. Keyed on live
    # status, Dismiss would have run the full teardown on a workspace whose files are intact.
    # A never-active fixture passes over it, which is why this one is ever-active.
    s3, glue, _lf, cognito = install()
    cognito.users = {"alice": {"custom:shared_space_1": "sales"}, "bob": {"custom:shared_space_1": "sales"}}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "alice", "members": ["alice", "bob"], "status": "failed", "everActive": True}
    ).encode()
    s3.store[("shared-bkt", "sales/data/file.csv")] = b"data"
    glue.seed_space_database("sales")
    s3.store[("user-bkt", "alice/user_settings/shared-connections.json")] = json.dumps(
        {"version": 1, "connections": [{"name": "sales", "role": "owner", "status": "failed"}]}
    ).encode()
    registry = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    out = f.forget_space("sales", "alice", "req-f", registry)

    assert out["mode"] == "kept"
    assert ("shared-bkt", "sales/data/file.csv") in s3.store
    assert "sales" in glue.databases
    assert ("admin-bkt", "shared-spaces/sales.json") in s3.store
    # It clears NOTHING — the row it would otherwise delete is the only affordance for retrying
    # the delete, and the slot is what a retry still needs.
    assert cognito.users["alice"]["custom:shared_space_1"] == "sales"
    kept = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert kept["connections"][0]["name"] == "sales"


def test_forget_raises_when_the_record_reappears_after_the_name_is_freed():
    # The same race as the delete verb's, on the other route that frees a name. A membership
    # write that lost to this teardown re-creates the record from its own stale copy, leaving a
    # name locked over a prefix and a database that are already gone.
    s3, glue, _lf, cognito = install()
    cognito.users = {"alice": {"custom:shared_space_1": "sales"}}
    registry = {"name": "sales", "owner": "alice", "members": ["alice"], "status": "failed"}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(registry).encode()
    glue.seed_space_database("sales")
    _seed_cache(s3, "alice", [{"name": "sales", "role": "owner", "status": "failed"}])
    real_delete = forget_registry.delete

    def delete_then_lose_the_race(name):
        real_delete(name)
        s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(registry).encode()

    forget_registry.delete = delete_then_lose_the_race
    try:
        raises(
            lambda: f.forget_space("sales", "alice", "req-f", registry),
            forget_registry.RegistryRecordResurrected,
            "reappeared",
        )
    finally:
        forget_registry.delete = real_delete


def test_forget_teardown_clears_a_member_the_validator_never_saw():
    # Same union as the delete verb's destroying route, and for the same reason: this branch
    # frees the name, so a slot it misses is an entitlement to whatever is created next.
    s3, glue, _lf, cognito = install()
    cognito.users = {m: {"custom:shared_space_1": "sales"} for m in ("alice", "bob")}
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "alice", "members": ["alice", "bob"], "status": "failed"}
    ).encode()
    glue.seed_space_database("sales")
    for m in ("alice", "bob"):
        _seed_cache(s3, m, [{"name": "sales", "role": "owner" if m == "alice" else "member", "status": "active"}])
    stale_event_copy = {"name": "sales", "owner": "alice", "members": ["alice"], "status": "failed"}

    f.forget_space("sales", "alice", "req-f", stale_event_copy)

    assert cognito.users["bob"]["custom:shared_space_1"] == "", "bob's slot outlived the freed name"
