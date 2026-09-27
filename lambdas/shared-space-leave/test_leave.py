"""Unit tests for the leave verb."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import leave as l
import registry as leave_registry
from cpcommon import clients
from cpcommon import config as cpconfig
from fakes import install, raises


def _seed_full_space(s3, glue, cognito, name="sales", members=("alice", "bob")):
    owner = members[0]
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(
        {"name": name, "owner": owner, "members": list(members), "status": "active", "createdAt": "t0"}
    ).encode()
    s3.store[("shared-bkt", f"{name}/DO_NOT_DELETE.txt")] = b"marker"
    glue.seed_space_database(name, ["t1", "t2"])
    cognito.users = {}
    for m in members:
        cognito.users[m] = {"custom:shared_space_1": name}
        role = "owner" if m == owner else "member"
        s3.store[("user-bkt", f"{m}/user_settings/shared-connections.json")] = json.dumps(
            {"version": 1, "connections": [{"name": name, "role": role, "status": "active"}]}
        ).encode()


def test_leave_clears_slot_cache_registry_and_owner_projection_leaves_data():
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    out = l.leave_space("sales", "bob", "req-l", reg)
    assert out["left"] is True
    assert cognito.users["bob"]["custom:shared_space_1"] == ""
    bob_cache = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])
    assert bob_cache["connections"] == []
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg2["members"] == ["alice"]
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert owner_cache["connections"][0]["members"] == [{"username": "alice", "status": "active"}]
    assert ("shared-bkt", "sales/DO_NOT_DELETE.txt") in s3.store
    assert "sales" in glue.databases and glue.tables["sales"] == ["t1", "t2"]


def test_leave_idempotent_for_non_member():
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice",))
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    out = l.leave_space("sales", "carol", "req-l", reg)
    assert out["left"] is False
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg2["members"] == ["alice"]


def test_leaving_drops_the_actors_index_entry_and_nobody_elses():
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    for member in ("alice", "bob"):
        s3.store[("admin-bkt", f"memberships/{member}.json")] = json.dumps(
            {"version": 1, "username": member, "spaces": [{"name": "sales", "status": "active"}]}
        ).encode()
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    l.leave_space("sales", "bob", "req-l", reg)

    assert json.loads(s3.store[("admin-bkt", "memberships/bob.json")])["spaces"] == []
    owner = json.loads(s3.store[("admin-bkt", "memberships/alice.json")])
    assert owner["spaces"] == [{"name": "sales", "status": "active"}]


def test_the_roster_fans_out_under_the_owner_the_commit_carries():
    # A leave is authorized on the actor's own membership, so it carries no expected owner and a
    # transfer landing before its commit is not refused. Fanning out from the validator's
    # snapshot then told carol's members the space was still alice's.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob", "carol"))
    stale = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    transferred = dict(stale, owner="carol")
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(transferred).encode()

    l.leave_space("sales", "bob", "req-l", stale)

    # alice holds a MEMBER card now, and a member card is the one that names the owner.
    alice_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert alice_cache["connections"][0]["owner"] == "carol"
    assert alice_cache["connections"][0]["role"] == "member"


def test_a_leave_committed_against_an_emptied_space_writes_no_card_back():
    # The emptying rewrite clears the owner field, so the commit hands back a record with none.
    # Fanning out anyway re-created a card for a space the delete had just cleared from every
    # list, and wrote the owner projection under a falsy key.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob"))
    stale = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    emptied = dict(stale, members=[], acknowledged=[], emptiedAt="t1", previousOwner="alice")
    del emptied["owner"]
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(emptied).encode()
    del s3.store[("user-bkt", "alice/user_settings/shared-connections.json")]

    l.leave_space("sales", "bob", "req-l", stale)

    assert ("user-bkt", "alice/user_settings/shared-connections.json") not in s3.store
    # The key is f"{username}/...", so an ownerless projection lands under the string "None".
    assert [k for k in s3.store if k[0] == "user-bkt" and k[1].startswith("None/")] == []


def test_the_owner_told_about_a_leave_is_the_one_the_commit_carries():
    # The notification names an owner too, one line past the fan-out, and it was reading the same
    # stale snapshot: the former owner was told somebody left a space that is no longer theirs,
    # and the new owner was told nothing.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob", "carol"))
    cpconfig.NOTIFICATIONS_QUEUE_URL = "https://sqs/notifications.fifo"
    sqs = clients._sqs
    stale = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        dict(stale, owner="carol")
    ).encode()

    l.leave_space("sales", "bob", "req-l", stale)

    told = [json.loads(m["MessageBody"])["username"] for m in sqs.sent]
    assert told == ["carol"]


def test_a_leave_landing_after_the_space_was_transferred_to_the_leaver_is_refused_and_undone():
    # bob's leave was authorized while alice owned the space, and her transfer to him committed
    # before his roster write. Completing it left an owner who is not a member, holding no slot
    # and no card, and the add normalises an owner out, so nobody could give him either back.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito, members=("alice", "bob", "carol"))
    stale = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(dict(stale, owner="bob")).encode()

    raises(lambda: l.leave_space("sales", "bob", "req-l", stale), leave_registry.OwnerChanged)

    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["owner"] == "bob" and saved["members"] == ["alice", "bob", "carol"]
    assert cognito.users["bob"]["custom:shared_space_1"] == "sales"
    card = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])
    assert [(c["name"], c["role"]) for c in card["connections"]] == [("sales", "owner")]
