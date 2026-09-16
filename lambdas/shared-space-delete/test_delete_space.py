"""Unit tests for the delete-space verb (owner cascade-delete)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import delete_space as d
import membership as membership_module
import registry as teardown_registry
import teardown
from auth import AuthorizationError, authorize, member_refusal
from cpcommon import clients
from cpcommon import config as cpconfig
from fakes import install, raises


def _enable_notifications():
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
    return clients._sqs


def _sent(sqs):
    out = {}
    for m in sqs.sent:
        body = json.loads(m["MessageBody"])
        out[body["username"]] = body["message"]
    return out


def _seed_full_space(
    s3, glue, cognito, name="sales", members=("alice", "bob"), status="active", ever_active=None
):
    owner = members[0]
    record = {
        "name": name,
        "owner": owner,
        "members": list(members),
        "status": status,
        "createdAt": "t0",
    }
    # An active space is ever-active by definition; anything else says so explicitly, which is
    # what tells a failed CREATE (destroyable) from a failed DELETE (not).
    if ever_active if ever_active is not None else status == "active":
        record["everActive"] = True
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(record).encode()
    s3.store[("shared-bkt", f"{name}/DO_NOT_DELETE.txt")] = b"marker"
    s3.store[("shared-bkt", f"{name}/data/file.csv")] = b"data"
    s3.store[("shared-bkt", f"{name}/athenaresults/alice/q.csv")] = b"result"
    glue.databases.add(name)
    glue.tables[name] = ["t1", "t2"]
    cognito.users = {}
    for m in members:
        cognito.users[m] = {"custom:shared_space_1": name}
        role = "owner" if m == owner else "member"
        s3.store[("user-bkt", f"{m}/user_settings/shared-connections.json")] = json.dumps(
            {"version": 1, "connections": [{"name": name, "role": role, "status": "active"}]}
        ).encode()


def test_delete_removes_every_member_and_destroys_nothing():
    # A test that checked only the registry would pass over the point of the change: the
    # objects and the database surviving is the whole feature.
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    out = d.delete_space("sales", "alice", "req-d", reg)

    assert out["status"] == "ok" and set(out["revokedMembers"]) == {"alice", "bob"}
    for m in ("alice", "bob"):
        assert cognito.users[m]["custom:shared_space_1"] == ""
        cache = json.loads(s3.store[("user-bkt", f"{m}/user_settings/shared-connections.json")])
        assert cache["connections"] == []
    assert ("shared-bkt", "sales/data/file.csv") in s3.store
    assert "sales" in glue.databases and glue.tables["sales"] == ["t1", "t2"]
    assert lf.revokes == []
    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["members"] == [] and saved["acknowledged"] == []
    assert "owner" not in saved
    assert saved["status"] == "active" and saved["everActive"] is True
    assert saved["previousOwner"] == "alice" and saved["emptiedAt"]
    # Carried forward from the record it replaced, not rebuilt from a literal.
    assert saved["createdAt"] == "t0"


def test_the_emptied_record_is_inert_to_its_ORIGINAL_OWNER():
    """Driven as alice, not as a stranger: the original owner is the only actor who could have
    survived the clearing, so an assertion made as anyone else would pass without the mechanism.

    The two member actions moved out of `authorize` into `member_refusal`, so they are asserted
    through the predicate that decides them now — and that alone would be WEAKER than what it
    replaces. `authorize` refused because the owner field was cleared, which is what made the
    actor load-bearing; the predicate's emptied branch fires before any actor is consulted, so
    the emptied half would pass driven as a stranger too. The live-record pair below it is what
    pins the actor.
    """
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    live = json.loads(json.dumps(reg))
    d.delete_space("sales", "alice", "req-d", reg)
    emptied = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    for action in ("leave", "acknowledge_membership", "delete"):
        raises(
            lambda action=action: authorize(action, "sales", "alice", emptied),
            AuthorizationError,
        )
    for action in ("add_members", "remove_members"):
        code, _ = member_refusal("alice", "sales", action, ["bob"], emptied)
        assert code == "MemberSpaceEmptied", f"{action} on an emptied record: {code}"
        # The pair: on the LIVE record the same call is allowed for the original owner and
        # refused for anyone else, so the actor is what the assertion above is really about.
        assert member_refusal("alice", "sales", action, ["bob"], live) is None
        assert member_refusal("mallory", "sales", action, ["bob"], live)[0] == "MemberNotOwner"
    # previousOwner is for an operator to read, and no authorization path may consult it.
    assert emptied["previousOwner"] == "alice"


def test_a_never_active_space_is_still_destroyed_and_its_name_freed():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice",), status="failed")
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    d.delete_space("sales", "alice", "req-d", reg)

    assert not any(b == "shared-bkt" and k.startswith("sales/") for (b, k) in s3.store)
    assert "sales" not in glue.databases and "sales" not in glue.tables
    assert len(lf.revokes) == 2
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store


def test_an_ever_active_space_that_is_now_failed_is_emptied_not_destroyed():
    # The record a delete-that-failed leaves behind. Keying the route on live status rather
    # than the durable stamp would destroy a live workspace here.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, status="failed", ever_active=True)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    d.delete_space("sales", "alice", "req-d", reg)

    assert ("shared-bkt", "sales/data/file.csv") in s3.store
    assert "sales" in glue.databases
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])["status"] == "active"


def test_delete_fans_out_to_every_member_deduped_with_distinct_deleter_message():
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob", "carol"))
    sqs = _enable_notifications()
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    d.delete_space("sales", "alice", "req-d", reg)
    sent = _sent(sqs)
    # One per member, owner ∈ members; the deleter (alice) gets the distinct message.
    assert set(sent) == {"alice", "bob", "carol"}
    assert sent["alice"] == 'You deleted the shared workspace "sales".'
    assert sent["bob"] == 'The shared workspace "sales" was deleted.'
    assert sent["carol"] == 'The shared workspace "sales" was deleted.'
    # Deduplicated: exactly one message per member.
    assert len(sqs.sent) == 3
    assert {m["MessageDeduplicationId"] for m in sqs.sent} == {
        "req-d:delete:alice", "req-d:delete:bob", "req-d:delete:carol"
    }


def test_delete_clears_every_index_entry_BEFORE_the_name_is_freed():
    # The registry record is the name lock, so an index still naming a space whose name is free
    # is an entitlement to whatever gets created next. The drop rides the member loop, which runs
    # before reg.delete — the ORDER is what is asserted, since the end state is the same either
    # way when nothing else claims the name. Seeded never-active, because that is now the only
    # route that reaches reg.delete at all.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, status="failed")
    for member in ("alice", "bob"):
        s3.store[("admin-bkt", f"memberships/{member}.json")] = json.dumps(
            {"version": 1, "username": member, "spaces": [{"name": "sales", "status": "active"}]}
        ).encode()
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    still_indexed = {}
    real_delete = teardown_registry.delete

    def watching_delete(name):
        still_indexed.update(
            {
                m: json.loads(s3.store[("admin-bkt", f"memberships/{m}.json")])["spaces"]
                for m in ("alice", "bob")
            }
        )
        return real_delete(name)

    teardown_registry.delete = watching_delete
    try:
        d.delete_space("sales", "alice", "req-d", reg)
    finally:
        teardown_registry.delete = real_delete

    assert still_indexed == {"alice": [], "bob": []}


# ── SPEC-151 FR-003: a partial teardown must not free the name ───────────────


def test_a_key_that_could_not_be_deleted_leaves_the_registry_record_intact():
    """THE criterion. delete_space ends with reg.delete(space), commented "LAST — the name
    is now free to reuse". Before this fix, delete_objects returned HTTP 200 with a
    per-key Errors array that nobody read, so a space whose objects survived was reported
    as deleted and its name released — and the next space created with that name would
    inherit another tenant's data (SPEC-054: never a dangling half-deleted resource).
    """
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, status="failed")
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    s3.undeletable.add("sales/data/file.csv")

    raises(
        lambda: d.delete_space("sales", "alice", "req-d", reg),
        teardown.TeardownIncompleteError,
        "could not be deleted",
    )

    # The name is NOT free: the record is still there, and now says failed.
    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["status"] == "failed"
    # And the object that could not be removed is still in the bucket, which is the
    # condition the record is now protecting.
    assert ("shared-bkt", "sales/data/file.csv") in s3.store


# ── FR-008/FR-009: a membership write racing the empty, and a fault after the rewrite ────


def _add_member_behind_the_verbs_back(s3, name, member):
    record = json.loads(s3.store[("admin-bkt", f"shared-spaces/{name}.json")])
    record["members"].append(member)
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(record).encode()
    clients._cognito.users[member] = {"custom:shared_space_1": name}
    s3.store[("user-bkt", f"{member}/user_settings/shared-connections.json")] = json.dumps(
        {"version": 1, "connections": [{"name": name, "role": "member", "status": "active"}]}
    ).encode()
    s3.store[("admin-bkt", f"memberships/{member}.json")] = json.dumps(
        {"version": 1, "username": member, "spaces": [{"name": name, "status": "active"}]}
    ).encode()


def test_a_member_added_while_the_verb_runs_is_revoked_by_the_union_pass_and_told():
    # Delivery is ordered and executions are not, so an add authorized against a live record can
    # commit while this verb is mid-flight. The verb captured its roster before that, so the
    # latecomer's slot — which IS the grant — would otherwise outlive the space they were added
    # to, in a record with no owner to remove them.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    sqs = _enable_notifications()
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    # The window is between the verb's own read and the emptying rewrite: an add committing
    # inside it lands in the record that rewrite hands back, and nowhere else.
    real_empty = d.reg.empty_space

    def add_carol_then_empty(*args, **kwargs):
        _add_member_behind_the_verbs_back(s3, "sales", "carol")
        return real_empty(*args, **kwargs)

    d.reg.empty_space = add_carol_then_empty
    try:
        out = d.delete_space("sales", "alice", "req-d", reg)
    finally:
        d.reg.empty_space = real_empty

    assert "carol" in out["revokedMembers"]
    assert cognito.users["carol"]["custom:shared_space_1"] == ""
    assert json.loads(s3.store[("admin-bkt", "memberships/carol.json")])["spaces"] == []
    carol_cache = json.loads(s3.store[("user-bkt", "carol/user_settings/shared-connections.json")])
    assert carol_cache["connections"] == []
    # Told the same thing as everyone else — either choice compiles, and the silent one revokes
    # a user's access without a word.
    assert _sent(sqs)["carol"] == 'The shared workspace "sales" was deleted.'
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])["members"] == []


def test_a_fault_after_the_rewrite_hands_the_space_back_to_its_owner():
    # By this point the owner field is gone, so the ordinary failed state would be one nobody
    # can act on: delete is owner-only, leave is member-only against an empty roster, and the
    # Retry the screen offers is refused. The space has to come back owned.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    real_empty = d.reg.empty_space
    real_remove = d.cache.remove_entry

    def add_carol_then_empty(*args, **kwargs):
        _add_member_behind_the_verbs_back(s3, "sales", "carol")
        return real_empty(*args, **kwargs)

    def fail_for_the_latecomer(username, name):
        if username == "carol":
            raise RuntimeError("cognito is having a day")
        return real_remove(username, name)

    d.reg.empty_space = add_carol_then_empty
    d.cache.remove_entry = fail_for_the_latecomer
    try:
        raises(
            lambda: d.delete_space("sales", "alice", "req-d", reg),
            RuntimeError,
            "cognito is having a day",
        )
    finally:
        d.reg.empty_space = real_empty
        d.cache.remove_entry = real_remove

    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["status"] == "failed"
    assert saved["owner"] == "alice", "an ownerless failed record is one nobody can act on"
    assert saved["everActive"] is True
    # And the owner can now finish what they started.
    authorize("delete", "sales", "alice", saved)


def test_a_failed_delete_records_the_action_so_the_screen_retries_the_right_verb():
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    def boom(*_a, **_k):
        raise RuntimeError("clear_slot failed")

    # Captured BEFORE the patch: `d.membership` is the same module object every other verb
    # imports, so reading the attribute back afterwards would restore the fake to the whole suite.
    real_clear_slot = membership_module.clear_slot
    membership_module.clear_slot = boom
    try:
        raises(lambda: d.delete_space("sales", "alice", "req-d", reg), RuntimeError, "clear_slot")
    finally:
        membership_module.clear_slot = real_clear_slot

    entry = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])["connections"][0]
    assert entry["status"] == "failed" and entry["failedAction"] == "delete"
    # The captured loop failed, so the rewrite never ran and the owner was never cleared.
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])["owner"] == "alice"


# ── The destroying route's own races (FR-002) ───────────────────────────────


def test_the_destroying_route_clears_a_member_the_validator_never_saw():
    # The event's roster and a fresh read are both snapshots, and the destroying route FREES
    # THE NAME — so a slot it misses becomes a principal tag on whatever is created under that
    # name next, because the portal policy is scoped on the tag value and not on any space
    # identity. The verb clears the union of the two, not the copy it was handed.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob"), status="failed")
    stale_event_copy = {"name": "sales", "owner": "alice", "members": ["alice"], "status": "failed"}

    d.delete_space("sales", "alice", "req-d", stale_event_copy)

    assert cognito.users["bob"]["custom:shared_space_1"] == "", "bob's slot outlived the freed name"
    assert cognito.users["alice"]["custom:shared_space_1"] == ""
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store


def test_a_record_that_reappears_after_the_name_is_freed_raises():
    # A membership write that lost its race to the delete re-creates the record from its own
    # stale copy — save_members falls back to that copy when the fresh read is None, and the
    # write is create-if-absent, so it succeeds against the object we just removed. The result
    # is a name locked over resources that no longer exist, and nothing else would notice.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice",), status="failed")
    reg_copy = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    real_delete = teardown_registry.delete

    def delete_then_lose_the_race(name):
        real_delete(name)
        s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(reg_copy).encode()

    teardown_registry.delete = delete_then_lose_the_race
    try:
        raises(
            lambda: d.delete_space("sales", "alice", "req-d", reg_copy),
            teardown_registry.RegistryRecordResurrected,
            "reappeared",
        )
    finally:
        teardown_registry.delete = real_delete


def test_a_latecomer_the_fault_never_reached_is_put_BACK_on_the_roster():
    # The rewrite blanks the roster, so a latecomer whose revocation had not happened when a
    # fault landed exists in no record at all: they keep the slot that IS their grant, are never
    # told, and nobody can remove them — an owner cannot act on a roster they are absent from,
    # and they cannot leave a space that does not list them. Restoring only the owner is what
    # made that permanent, and the retry reported success with `revoked: []`.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    real_empty = d.reg.empty_space
    real_remove = d.cache.remove_entry

    def add_carol_then_empty(*args, **kwargs):
        _add_member_behind_the_verbs_back(s3, "sales", "carol")
        return real_empty(*args, **kwargs)

    def fail_for_the_latecomer(username, name):
        if username == "carol":
            raise RuntimeError("cognito is having a day")
        return real_remove(username, name)

    d.reg.empty_space = add_carol_then_empty
    d.cache.remove_entry = fail_for_the_latecomer
    try:
        raises(lambda: d.delete_space("sales", "alice", "req-d", reg), RuntimeError, "having a day")
    finally:
        d.reg.empty_space = real_empty
        d.cache.remove_entry = real_remove

    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["owner"] == "alice"
    assert saved["members"] == ["carol"], "the latecomer must be visible to the retry"

    # And the retry finishes the job: carol is revoked, told, and counted.
    sqs = _enable_notifications()
    out = d.delete_space("sales", "alice", "req-d2", saved)

    assert "carol" in out["revokedMembers"]
    assert cognito.users["carol"]["custom:shared_space_1"] == ""
    assert _sent(sqs)["carol"] == 'The shared workspace "sales" was deleted.'


def test_an_unstamped_active_record_is_stamped_before_it_is_emptied():
    # The record the backfill exists for: active, written before the field did. Every other
    # fixture here sets everActive whenever the status is active, so nothing else represents it.
    # Left unstamped, the emptied record is safe only while its status stays active — and the
    # failure path writes `failed`, at which point it becomes destroyable again and Dismiss
    # would tear down the retained data.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, ever_active=False)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert "everActive" not in reg

    d.delete_space("sales", "alice", "req-d", reg)

    assert json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])["everActive"] is True


def test_re_emptying_preserves_the_original_owner_and_the_first_emptied_time():
    # A Step Functions task retry re-runs the verb with the pre-empty event record. Recomputing
    # previousOwner from a record that no longer has an owner writes a JSON null over the only
    # trace of who owned the space, and restamping emptiedAt tells an operator the wrong hour.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    event_record = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    d.delete_space("sales", "alice", "req-d", event_record)
    first = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    d.delete_space("sales", "alice", "req-d", event_record)

    replayed = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert replayed["previousOwner"] == "alice"
    assert replayed["emptiedAt"] == first["emptiedAt"]
    assert "owner" not in replayed and replayed["status"] == "active"


def test_the_requester_loses_their_own_card_even_when_the_roster_is_empty():
    # The retry after a repaired failure runs against an emptied record, so the loop clears
    # nobody — and the one card that must not survive is the requester's own, because the
    # screen renders a deleting row from it for a workspace that is already gone. That row is
    # the entry point to the stranding this spec closes.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    restored = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    restored.update({"members": [], "previousOwner": "alice", "emptiedAt": "t1", "status": "failed"})
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(restored).encode()
    s3.store[("user-bkt", "alice/user_settings/shared-connections.json")] = json.dumps(
        {"version": 1, "connections": [{"name": "sales", "role": "owner", "status": "deleting"}]}
    ).encode()

    d.delete_space("sales", "alice", "req-d2", restored)

    alice_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert alice_cache["connections"] == [], "the requester kept a card for a space that is gone"


def test_the_delete_emits_one_notify_members_span_around_the_whole_fan_out(captured_events):
    """The success fan-out, spanned once for a space with two members rather than once each.

    The failure path's single notification is deliberately OUTSIDE this helper — it says
    something different and is not a fan-out — so this asserts the success path only.

    Args:
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    out = d.handler(
        {"space": "sales", "actor": "alice", "requestId": "req-span", "registry": reg}, None
    )

    assert out["status"] == "ok", "the span is asserted on a SUCCESSFUL run"
    root = captured_events.spans("delete")
    assert len(root) == 1, f"expected one delete root span, got {len(root)}"
    children = captured_events.child_spans("delete", name="notify-members")
    assert len(children) == 1, (
        f"delete emitted {len(children)} 'notify-members' child spans over a two-member space, "
        "expected exactly one around the whole loop"
    )
    assert children[0]["parent_span_id"] == root[0]["span_id"]


def test_a_delete_authorized_before_a_transfer_refuses_before_revoking_anyone():
    # Deleting is owner-only, so the actor is the owner the validator verified. A transfer
    # landing before the verb runs leaves it about to empty somebody else's space. The check
    # rides the deleting status — the cascade's first WRITE — so a refusal this early has
    # written nothing and revoked nobody.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob"))
    stale = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        dict(stale, owner="bob")
    ).encode()

    raises(
        lambda: d.delete_space("sales", "alice", "req-d", stale),
        teardown_registry.OwnerChanged,
    )

    record = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert record["status"] == "active" and "emptiedAt" not in record
    # Never written, rather than written and put back: the repair below is best-effort, so a
    # refusal that depends on it is only as good as the repair. lastRequestId is what tells the
    # two apart — both the deleting write and its repair stamp it.
    assert "lastRequestId" not in record
    assert cognito.users["bob"]["custom:shared_space_1"] == "sales"
    assert cognito.users["alice"]["custom:shared_space_1"] == "sales"
    assert ("user-bkt", "bob/user_settings/shared-connections.json") in s3.store


def test_a_retry_of_a_delete_that_failed_after_emptying_is_not_refused_as_a_transfer():
    # The emptying rewrite clears the owner field and keeps the original in previousOwner, so the
    # owner check answers from there. Reading the owner field alone would refuse every retry of
    # the one failure the retry exists for.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob"))
    stale = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    emptied = dict(stale, members=[], acknowledged=[], emptiedAt="t1", previousOwner="alice")
    del emptied["owner"]
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(emptied).encode()

    out = d.delete_space("sales", "alice", "req-d2", stale)

    assert out["status"] == "ok"
    assert cognito.users["alice"].get("custom:shared_space_1", "") == ""


def test_a_refused_delete_clears_the_deleting_card_the_validator_stamped():
    # The validator writes the requester's card as `deleting` before the verb runs. A refusal
    # that skipped the failure handler left it there, and the screen's Retry on that card
    # re-enqueues a delete the validator now refuses by RAISING — which reaches nobody. Alice is
    # still a member of the space she no longer owns, so her card becomes the member card.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob"))
    stale = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        dict(stale, owner="bob")
    ).encode()
    s3.store[("user-bkt", "alice/user_settings/shared-connections.json")] = json.dumps(
        {"version": 1, "connections": [{"name": "sales", "role": "owner", "status": "deleting"}]}
    ).encode()

    raises(lambda: d.delete_space("sales", "alice", "req-d", stale), teardown_registry.OwnerChanged)

    card = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert card["connections"][0]["status"] != "deleting"
    assert card["connections"][0]["role"] == "member"
    assert card["connections"][0]["owner"] == "bob"


def test_a_transfer_landing_between_the_fresh_read_and_the_first_write_is_refused_there():
    # The pre-check reads once; the deleting status is the cascade's first WRITE, so it carries
    # the same check under compare-and-swap. Nothing between them reaches the roster, and the
    # refusal has to leave alice's card usable just as the pre-check's does — it is raised
    # outside the cascade's own handler, which is where it escaped every repair once.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob"))
    stale = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    s3.store[("user-bkt", "alice/user_settings/shared-connections.json")] = json.dumps(
        {"version": 1, "connections": [{"name": "sales", "role": "owner", "status": "deleting"}]}
    ).encode()

    # Between the fresh read and the cascade's first write, which is the window the read alone
    # cannot see and the guarded write is there to close.
    real_destroyable = d.reg.is_destroyable

    def transfer_then_route(record):
        out = real_destroyable(record)
        current = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
        s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
            dict(current, owner="bob")
        ).encode()
        return out

    d.reg.is_destroyable = transfer_then_route
    try:
        raises(lambda: d.delete_space("sales", "alice", "req-d", stale), teardown_registry.OwnerChanged)
    finally:
        d.reg.is_destroyable = real_destroyable

    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["owner"] == "bob" and saved["status"] == "active"
    assert "lastRequestId" not in saved, "the refusal must not have written to bob's record"
    assert cognito.users["bob"]["custom:shared_space_1"] == "sales"
    card = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert card["connections"][0]["status"] != "deleting"


def test_the_status_repair_does_not_overwrite_the_new_owner_s_own_delete():
    # The repair exists to undo THIS run's deleting write. The new owner may have started a
    # delete of their own in the same window, and restoring active over that would hide their
    # cascade — so the repair is keyed on the record still naming this request.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob"))
    stale = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        dict(stale, owner="bob", status="deleting", lastRequestId="req-bob")
    ).encode()

    raises(lambda: d.delete_space("sales", "alice", "req-d", stale), teardown_registry.OwnerChanged)

    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["status"] == "deleting" and saved["lastRequestId"] == "req-bob"


def test_a_refused_delete_writes_nothing_even_to_a_record_with_no_ever_active_stamp():
    # The ever-active stamp is a no-op only on a record that already carries the field, and the
    # backfill exists because records without it are real. Every other fixture here stamps one
    # whenever the status is active, so the un-stamped record is the only one that can tell a
    # cascade that writes before it checks from one that checks first.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob"), ever_active=False)
    stale = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert "everActive" not in stale
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        dict(stale, owner="bob")
    ).encode()

    raises(lambda: d.delete_space("sales", "alice", "req-d", stale), teardown_registry.OwnerChanged)

    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert "everActive" not in saved, "the refused delete stamped a record it may not touch"
    assert "lastRequestId" not in saved


def test_a_retry_repairs_the_deleting_status_its_own_earlier_attempt_left():
    # The refusal is on the first write, so a run that gets refused has written nothing — which
    # would leave the repair dead if it were keyed on this attempt having written. It is keyed on
    # the RECORD instead, so the one case that reaches it is the one that needs it: an attempt
    # wrote `deleting` and died, the space changed hands, and the retry is refused. Without the
    # repair that record is frozen — the authorizer refuses an add, a transfer and a retry on
    # anything not active, so the new owner holds a space nobody can use or mend.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob"))
    stale = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        dict(stale, owner="bob", status="deleting", lastRequestId="req-d")
    ).encode()

    raises(lambda: d.delete_space("sales", "alice", "req-d", stale), teardown_registry.OwnerChanged)

    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["status"] == "active" and saved["owner"] == "bob"
    assert member_refusal("bob", "sales", "add_members", ["carol"], saved) is None
    authorize("delete", "sales", "bob", saved)
