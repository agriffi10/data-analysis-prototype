"""Unit tests for the one-shot ever-active backfill."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import backfill_ever_active as b
from fakes import install, raises


def _seed(s3, name, status, ever=False, reason=None):
    record = {
        "version": 1,
        "name": name,
        "owner": "alice",
        "members": ["alice"],
        "status": status,
        "createdAt": "t0",
    }
    if ever:
        record["everActive"] = True
    if reason:
        record["reason"] = reason
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(record).encode()


def _stored(s3, name):
    return json.loads(s3.store[("admin-bkt", f"shared-spaces/{name}.json")])


def test_report_writes_nothing_and_apply_stamps_only_the_decidable_statuses():
    s3, glue, *_ = install()
    _seed(s3, "aaa", "active")
    _seed(s3, "bbb", "deleting")
    _seed(s3, "ccc", "failed", reason="teardown blew up")
    _seed(s3, "ddd", "provisioning")
    _seed(s3, "eee", "active", ever=True)
    glue.databases.add("ccc")
    s3.store[("shared-bkt", "ccc/data.csv")] = b"x"
    # ddd is a create that got as far as its marker and no further — which is most of them,
    # since the marker is written before the database, the grant and the outcome. Counting it
    # as data would report every failed create as holding some, and stamping a failed create
    # burns its name forever.
    glue.databases.add("ddd")
    s3.store[("shared-bkt", "ddd/DO_NOT_DELETE.txt")] = b"marker"

    report = b.backfill(mode="report")

    assert report["scanned"] == 5
    assert report["wouldStamp"] == {"active": 1}
    assert report["alreadyStamped"] == 1
    assert all("everActive" not in _stored(s3, n) for n in ("aaa", "bbb", "ccc", "ddd"))
    # Neither a failed nor a deleting record is decided by a rule. `deleting` is a human decision, not an automatic stamp: delete is gated on ownership
    # alone, so an owner can delete a never-active create and a timed-out run leaves that status
    # permanently. Stamping it unattended would burn a name with nobody ever seeing it.
    rows = {row["name"]: row for row in report["undecidable"]}
    assert set(rows) == {"bbb", "ccc", "ddd"}
    assert rows["bbb"]["status"] == "deleting" and rows["bbb"]["verdict"] == "decide"
    assert rows["ccc"]["hasDatabase"] is True and rows["ccc"]["hasData"] is True
    assert rows["ccc"]["reason"] == "teardown blew up"
    # A database and a marker, and NO data — the marker does not count.
    assert rows["ddd"]["hasDatabase"] is True and rows["ddd"]["hasData"] is False
    # Only `reserve` writes provisioning, so that answer is already known.
    assert rows["ddd"]["verdict"] == "never stamp"

    applied = b.backfill(mode="apply", request_id="req-1")

    assert applied["stamped"] == {"active": 1}
    assert _stored(s3, "aaa")["everActive"] is True
    for untouched in ("bbb", "ccc", "ddd"):
        assert "everActive" not in _stored(s3, untouched)


def test_a_second_apply_stamps_nothing_and_leaves_the_first_runs_request_id():
    s3, *_ = install()
    _seed(s3, "aaa", "active")
    b.backfill(mode="apply", request_id="req-1")

    second = b.backfill(mode="apply", request_id="req-2")

    assert second["stamped"] == {} and second["alreadyStamped"] == 1
    assert _stored(s3, "aaa")["lastRequestId"] == "req-1"


def test_stamp_takes_one_named_record_and_the_bare_invoke_reports():
    s3, *_ = install()
    _seed(s3, "ccc", "failed")
    # Seeded ACTIVE as well, or the assertion below is vacuous: a `failed` record is one that
    # apply mode would not stamp either, so flipping the handler's default from report to apply
    # would leave this test green.
    _seed(s3, "aaa", "active")

    # The default matters: an invocation with no payload is the easiest thing to do by
    # accident, and it must not mutate the registry.
    b.handler({}, None)
    assert "everActive" not in _stored(s3, "aaa")
    assert "everActive" not in _stored(s3, "ccc")

    b.handler({"mode": "stamp", "name": "ccc", "requestId": "req-1"}, None)

    assert _stored(s3, "ccc")["everActive"] is True
    raises(lambda: b.backfill(mode="stamp"), ValueError, "requires a space name")
    raises(lambda: b.backfill(mode="nonsense"), ValueError, "unknown mode")
