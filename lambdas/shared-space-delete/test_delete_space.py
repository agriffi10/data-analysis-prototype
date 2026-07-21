"""Unit tests for the delete-space verb (owner cascade-delete)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

from cpcommon import clients  # noqa: E402
from cpcommon import config as cpconfig  # noqa: E402
import delete_space as d  # noqa: E402
import teardown  # noqa: E402
from fakes import install, raises  # noqa: E402


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


def test_delete_idempotent_tolerant_of_partial_prior_progress():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    glue.databases.discard("sales")
    glue.tables.pop("sales", None)
    for key in [k for (b, k) in list(s3.store) if b == "shared-bkt"]:
        s3.store.pop(("shared-bkt", key), None)

    out = d.delete_space("sales", "alice", "req-d", reg)
    assert out["status"] == "ok"
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store
    for m in ("alice", "bob"):
        assert cognito.users[m]["custom:shared_space_1"] == ""


def test_delete_records_failure_and_reraises_without_deleting_registry():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    orig = teardown.drop_database
    try:
        def boom(name):
            raise RuntimeError("glue throttled")

        teardown.drop_database = boom
        raises(lambda: d.delete_space("sales", "alice", "req-d", reg), RuntimeError, "throttled")
    finally:
        teardown.drop_database = orig
    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["status"] == "failed" and "throttled" in saved["reason"]
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert owner_cache["connections"][0]["status"] == "failed"


def test_delete_fans_out_to_every_member_deduped_with_distinct_deleter_message():
    s3, glue, lf, cognito = install()
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


def test_delete_failure_notifies_owner_with_reason():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    sqs = _enable_notifications()
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    orig = teardown.drop_database
    try:
        def boom(name):
            raise RuntimeError("glue throttled")

        teardown.drop_database = boom
        raises(lambda: d.delete_space("sales", "alice", "req-d", reg), RuntimeError, "throttled")
    finally:
        teardown.drop_database = orig
    # A failed cascade notifies ONLY the owner (not the member fan-out, which is past the
    # terminal success) — the owner otherwise hears nothing about the failure.
    assert len(sqs.sent) == 1
    msg = sqs.sent[0]
    assert msg["MessageGroupId"] == "alice"
    assert msg["MessageDeduplicationId"] == "req-d:delete-failed:alice"
    body = json.loads(msg["MessageBody"])
    assert body["username"] == "alice"
    assert body["message"].startswith('We couldn\'t delete the shared workspace "sales":')
    # SPEC-106 FR-009: the notification carries friendly text, never the raw AWS error.
    assert "throttled" not in body["message"]
    assert "contact the Administrator" in body["message"]


def test_delete_swallows_emit_failure_and_still_succeeds():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    _enable_notifications()

    class Boom:
        def send_message(self, **kw):
            raise RuntimeError("sqs down")

    clients._sqs = Boom()
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    out = d.delete_space("sales", "alice", "req-d", reg)  # must not raise
    assert out["status"] == "ok"
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store


def test_handler_uses_validated_context():
    s3, glue, lf, cognito = install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    out = d.handler({"space": "sales", "actor": "alice", "requestId": "req-d", "registry": reg}, None)
    assert out["status"] == "ok"
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} delete-space tests passed.")
    sys.exit(0)
