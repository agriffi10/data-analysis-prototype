"""Unit tests for the delete-space verb (owner cascade-delete)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import delete_space as d
import registry as teardown_registry
import teardown
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


def _seed_full_space(s3, glue, cognito, name="sales", members=("alice", "bob")):
    owner = members[0]
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(
        {"name": name, "owner": owner, "members": list(members), "status": "active", "createdAt": "t0"}
    ).encode()
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


def test_delete_cascades_files_tables_db_members_and_registry_frees_name():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    out = d.delete_space("sales", "alice", "req-d", reg)
    assert out["status"] == "ok" and set(out["revokedMembers"]) == {"alice", "bob"}
    assert not any(b == "shared-bkt" and k.startswith("sales/") for (b, k) in s3.store)
    assert "sales" not in glue.databases and "sales" not in glue.tables
    assert len(lf.revokes) == 2
    for m in ("alice", "bob"):
        assert cognito.users[m]["custom:shared_space_1"] == ""
        cache = json.loads(s3.store[("user-bkt", f"{m}/user_settings/shared-connections.json")])
        assert cache["connections"] == []
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store


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
    # way when nothing else claims the name.
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
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

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} delete-space tests passed.")
    sys.exit(0)


# ── SPEC-151 FR-003: a partial teardown must not free the name ───────────────


def test_a_key_that_could_not_be_deleted_leaves_the_registry_record_intact():
    """THE criterion. delete_space ends with reg.delete(space), commented "LAST — the name
    is now free to reuse". Before this fix, delete_objects returned HTTP 200 with a
    per-key Errors array that nobody read, so a space whose objects survived was reported
    as deleted and its name released — and the next space created with that name would
    inherit another tenant's data (SPEC-054: never a dangling half-deleted resource).
    """
    s3, glue, _lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
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
