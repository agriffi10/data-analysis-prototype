"""Unit tests for the create-space verb.

The common layer is added to sys.path here because `lambdas/conftest.py` does not list
shared-space-common among the layer roots it puts there.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import cache
import create_space as c
import membership_index
import pytest
import registry as reg
from cpcommon import clients
from fakes import install, raises


def test_create_happy_path_provisions_everything():
    s3, glue, lf, cognito = install()
    out = c.create_space("sales", "alice", "req-1")
    assert out["status"] == "active"
    assert glue.created == ["sales"]
    assert glue.parameters["sales"] == {"dataquarry.shared-space": "sales"}
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


_ALICE_CACHE = ("user-bkt", "alice/user_settings/shared-connections.json")


def _seed_sales(s3, **record):
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "lastRequestId": "req-1", **record}
    ).encode()


@pytest.mark.parametrize(
    "record, held",
    [
        pytest.param(
            {"owner": "alice", "status": "active", "everActive": True},
            lambda: cache.write_owner_projection("alice", "sales", ["alice", "bob"], [], "t0"),
            id="owned",
        ),
        pytest.param(
            {"owner": "bob", "status": "active", "everActive": True},
            lambda: cache.write_member_entry("alice", "sales", "bob", ["bob", "alice"], [], "t0"),
            id="member",
        ),
        pytest.param(
            {"owner": "alice", "status": "failed", "everActive": True},
            lambda: cache.upsert_entry(
                "alice",
                {"name": "sales", "role": "owner", "status": "failed", "reason": "x", "failedAction": "delete"},
            ),
            id="failed-delete",
        ),
    ],
)
def test_a_refused_create_leaves_a_space_already_on_the_actors_list_alone(record, held):
    """The reservation refuses a name alice already owns or belongs to, and that refusal used to
    replace her card for the space by name — a working space shown as a failed create that Retry
    collides on again and Dismiss cannot forget, or a failed delete whose Retry became a create.
    """
    s3, *_ = install()
    _seed_sales(s3, **record)
    held()
    before = s3.store[_ALICE_CACHE]

    raises(lambda: c.create_space("sales", "alice", "req-2"), reg.ProvisioningError, "name already taken")

    assert s3.store[_ALICE_CACHE] == before


@pytest.mark.parametrize(
    "prior",
    [
        pytest.param(None, id="no-card"),
        pytest.param({"name": "sales", "role": "owner", "status": "provisioning"}, id="pending"),
        pytest.param(
            {"name": "sales", "role": "owner", "status": "failed", "reason": "x", "failedAction": "create"},
            id="failed-create",
        ),
    ],
)
def test_a_refused_create_still_marks_its_own_card_failed(prior):
    s3, *_ = install()
    _seed_sales(s3, owner="bob", status="active")
    if prior is not None:
        cache.upsert_entry("alice", prior)

    raises(lambda: c.create_space("sales", "alice", "req-2"), reg.ProvisioningError, "name already taken")

    assert json.loads(s3.store[_ALICE_CACHE])["connections"] == [
        {"name": "sales", "role": "owner", "status": "failed", "reason": "name already taken", "failedAction": "create"}
    ]

def test_a_name_whose_database_is_not_this_spaces_is_refused_and_that_database_left_alone():
    """A user's personal database and a space's share one Glue namespace under the bare name, and
    a space may be named after a user. Treating "already exists" as this create's own retry
    adopted alice's database — tagged it, granted on it — and a teardown of the failed or
    provisioning space then dropped every table in it. Only a database carrying this space's
    marker is the create's own; anything else is a name that is taken."""
    s3, glue, lf, _cognito = install()
    glue.databases.add("alice")
    glue.tables["alice"] = ["orders"]

    raises(lambda: c.create_space("alice", "mallory", "req-1"), reg.ProvisioningError, "name already taken")

    assert glue.tables["alice"] == ["orders"]
    assert lf.lf_tags == [] and lf.grants == []
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/alice.json")])["status"] == "failed"


def test_a_retry_meets_the_database_its_first_attempt_created_and_carries_on():
    _s3, glue, _lf, _cognito = install()
    glue.seed_space_database("sales")

    out = c.create_space("sales", "alice", "req-1")

    assert out["status"] == "active"


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


def test_create_writes_the_owners_index_only_once_the_space_is_active():
    # reserve() writes `provisioning` and only an active space yields a session tag, so an
    # index written mid-create entitles nobody. The ORDER is what is asserted, not just the
    # end state: a write placed before finalize passes an end-state check and is still wrong.
    install()
    order = []
    real_finalize = reg.finalize
    real_record = membership_index.record
    reg_module = sys.modules["registry"]
    reg_module.finalize = lambda *a, **k: (order.append(("finalize", a[3])), real_finalize(*a, **k))[1]
    membership_index.record = lambda *a, **k: (order.append(("index", a[2])), real_record(*a, **k))[1]
    try:
        c.create_space("sales", "alice", "req-1")
    finally:
        reg_module.finalize = real_finalize
        membership_index.record = real_record

    assert order == [("finalize", "active"), ("index", "active")]
    document = json.loads(clients._s3.store[("admin-bkt", "memberships/alice.json")])
    assert document["spaces"] == [{"name": "sales", "status": "active"}]


def test_a_failed_index_write_rolls_the_create_back_rather_than_stranding_the_space():
    # The index write sits INSIDE the provisioning guard, and this is the discriminator: placed
    # after it, a failure would leave an ACTIVE space whose owner holds no index entry — and once
    # membership is sourced from the index that owner can neither reach the space nor delete it,
    # because delete is gated on membership. Inside, the ordinary rollback runs and the owner gets
    # a failed card they can retry or forget.
    install()
    real_record = membership_index.record

    def boom(*a, **k):
        raise RuntimeError("index write failed")

    membership_index.record = boom
    try:
        raises(lambda: c.create_space("sales", "alice", "req-1"), RuntimeError, "index write failed")
    finally:
        membership_index.record = real_record

    rec = json.loads(clients._s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert rec["status"] == "failed"
    assert clients._cognito.attrs.get("custom:shared_space_1", "") == ""


def _record(s3, name="sales"):
    return json.loads(s3.store[("admin-bkt", f"shared-spaces/{name}.json")])


def test_finalize_stamps_ever_active_only_when_the_outcome_is_active():
    # finalize() runs on BOTH create outcomes, so an unconditional stamp would mark every
    # failed create ever-active — which refuses its owner's legitimate retry and refuses to
    # tear it down. The FAILED path is the one that has to be driven: a round-trip through
    # the happy path alone passes either way.
    s3, *_ = install()
    reg.reserve("sales", "alice", "req-1")

    reg.finalize("sales", "alice", "req-1", "failed", "boom")
    assert "everActive" not in _record(s3)

    reg.reserve("sales", "alice", "req-2")
    reg.finalize("sales", "alice", "req-2", "active")
    assert _record(s3)["everActive"] is True


def test_finalize_carries_an_existing_ever_active_forward_onto_a_failed_outcome():
    # A different bug from the stamp, asserted separately: finalize rebuilds the record from
    # a literal, so it drops every field it does not name. It carries createdAt forward today
    # and would have dropped this one.
    s3, *_ = install()
    reg.reserve("sales", "alice", "req-1")
    reg.finalize("sales", "alice", "req-1", "active")

    reg.finalize("sales", "alice", "req-1", "failed", "boom")

    record = _record(s3)
    assert record["status"] == "failed" and record["everActive"] is True


def test_mark_ever_active_stamps_once_and_is_a_no_op_afterwards():
    s3, *_ = install()
    reg.reserve("sales", "alice", "req-1")

    assert reg.mark_ever_active("sales", "req-2") is True
    assert _record(s3)["everActive"] is True
    assert reg.mark_ever_active("sales", "req-3") is False
    assert _record(s3)["lastRequestId"] == "req-2"


def test_mark_ever_active_tolerates_a_record_that_is_gone():
    install()

    assert reg.mark_ever_active("never-existed", "req-1") is False


def test_a_failed_CREATE_may_be_retried_but_a_failed_DELETE_may_not_be_revived():
    # Two records that look identical — same owner, same failed status — and the durable stamp
    # is the only thing telling them apart. Re-provisioning the first is what the retry path
    # exists for. Re-provisioning the second resets the roster to the owner alone and hands
    # them back the previous cohort's files, in one call and with no confirmation.
    s3, *_ = install()
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "alice", "members": ["alice"], "status": "failed"}
    ).encode()

    assert reg.reserve("sales", "alice", "req-2") == "created"

    s3.store[("admin-bkt", "shared-spaces/finance.json")] = json.dumps(
        {"name": "finance", "owner": "alice", "members": ["alice", "bob"], "status": "failed", "everActive": True}
    ).encode()

    raises(lambda: reg.reserve("finance", "alice", "req-3"), reg.ProvisioningError, "name already taken")
    # Untouched — the previous cohort is still on the record an operator would restore from.
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/finance.json")])["members"] == ["alice", "bob"]


def test_save_members_and_set_status_both_preserve_the_stamp():
    # Neither names the field, so both preserve it only because they build from dict(existing).
    # A later projection-style rewrite of either would drop it with a green suite, which is
    # exactly what the field cannot survive.
    s3, *_ = install()
    record = {
        "name": "sales",
        "owner": "alice",
        "members": ["alice"],
        "status": "active",
        "everActive": True,
        "createdAt": "t0",
    }
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(record).encode()

    reg.save_members(record, "req-2", add=["bob"])
    assert _record(s3)["everActive"] is True

    reg.set_status(record, "deleting", "req-3")
    assert _record(s3)["everActive"] is True


@pytest.mark.parametrize(
    ("status", "claim_id"),
    [("deleting", "req-d"), ("failed", "req-d"), ("deleting", "req-1")],
)
def test_a_create_whose_record_a_delete_claimed_mid_provisioning_fails_and_leaves_the_claim(
    monkeypatch, status, claim_id
):
    # finalize rebuilt the record from a literal, so it overwrote the deleting status and stamped
    # the space ever-active while the delete that claimed it went on tearing it down: the owner
    # was told the space was ready, and it then vanished. It now refuses a record this create no
    # longer holds, and the failure path's own finalize refuses it too. A delete whose teardown
    # faulted writes failed over its claim, so the status alone is not the test; a request id is
    # the caller's, so neither is the id alone.
    s3, *_ = install()
    real_grant = c._grant_portal_role

    def grant_then_delete_claims(name):
        real_grant(name)
        record = json.loads(s3.store[("admin-bkt", f"shared-spaces/{name}.json")])
        s3.put_object(
            Bucket="admin-bkt",
            Key=f"shared-spaces/{name}.json",
            Body=json.dumps(dict(record, status=status, lastRequestId=claim_id)),
        )

    monkeypatch.setattr(c, "_grant_portal_role", grant_then_delete_claims)

    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.ProvisioningError, match="deleted")

    saved = _record(s3)
    assert saved["status"] == status and saved["lastRequestId"] == claim_id
    assert "everActive" not in saved


@pytest.mark.parametrize("reserved_by", [None, "bob"])
def test_a_create_whose_record_was_deleted_mid_provisioning_neither_resurrects_nor_takes_it(
    monkeypatch, reserved_by
):
    # The same literal rebuild on an absent record re-created the name the delete had just
    # freed, as active, over resources the teardown had removed; and on a record another user
    # had reserved since, it handed their name to this create's owner — even under a request id
    # that happens to match, since the caller chooses it.
    s3, *_ = install()
    real_grant = c._grant_portal_role
    bobs = {
        "name": "sales",
        "owner": "bob",
        "members": ["bob"],
        "status": "provisioning",
        "lastRequestId": "req-1",
    }

    def grant_then_delete_frees(name):
        real_grant(name)
        del s3.store[("admin-bkt", f"shared-spaces/{name}.json")]
        if reserved_by:
            s3.put_object(Bucket="admin-bkt", Key=f"shared-spaces/{name}.json", Body=json.dumps(bobs))

    monkeypatch.setattr(c, "_grant_portal_role", grant_then_delete_frees)

    raises(lambda: c.create_space("sales", "alice", "req-1"), reg.ProvisioningError, match="deleted")

    if reserved_by:
        assert _record(s3) == bobs
    else:
        assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store
