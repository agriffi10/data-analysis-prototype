"""Unit tests for the file-ops inspect-source Lambda.

What this verb owes is a plan that describes exactly what the operation will touch, and a per-item
outcome for everything it could not. The cases below are the ones where a plausible implementation
is silently wrong: a folder past its pagination boundary, an exclusion that empties a legal copy, a
duplicate that collapses into a placeholder, and an item an earlier verb already decided.

Runnable under pytest or directly: python3 test_file_ops_inspect_source.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-ops-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_ops_inspect_source as m
import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError
from focommon import notify

_EXECUTION = "arn:aws:states:us-east-1:1:execution:file-ops:run-1"


class _S3Error(Exception):
    """A botocore-shaped fault, so the code under test classifies it the way it would in Lambda."""

    def __init__(self, code, status=404):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
        super().__init__(code)


class _FakeS3:
    """An S3 that pages at a thousand keys, exactly as the real one does."""

    def __init__(self, objects, admin=None):
        self._objects = objects
        self._admin = admin or {}
        self.puts = []
        self.pages = 0

    def get_paginator(self, name):
        objects = self._objects
        outer = self

        class _P:
            def paginate(self, Bucket, Prefix):
                keys = sorted(k for k in objects if k.startswith(Prefix))
                for start in range(0, max(len(keys), 1), 1000):
                    outer.pages += 1
                    yield {
                        "Contents": [
                            {"Key": k, "Size": objects[k], "ETag": f'"{k}-etag"'}
                            for k in keys[start : start + 1000]
                        ]
                    }

        return _P()

    def head_object(self, Bucket, Key):
        if Key not in self._objects:
            raise _S3Error("NoSuchKey")
        return {"ContentLength": self._objects[Key], "ETag": f'"{Key}-etag"'}

    def get_object(self, Bucket, Key):
        if Key not in self._admin:
            raise _S3Error("NoSuchKey")

        class _Body:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

        return {"Body": _Body(self._admin[Key])}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        self._admin[Key] = Body
        return {}


def _install(objects, admin=None):
    fake = _FakeS3(objects, admin)
    clients._s3 = fake
    return fake


def _event(items=None, operation="move", outcomes=None, destination=True):
    event = {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "operation": operation,
        "execution": {"arn": _EXECUTION},
        "source": {
            "bucket": "user-bkt",
            "root": "alice/",
            "items": items or [{"kind": "folder", "key": "alice/reports/"}],
        },
        "destination": None,
        "onConflict": None,
        "submittedAt": None,
        "outcomes": outcomes or [],
    }
    if destination and operation != "delete":
        event["destination"] = {"bucket": "user-bkt", "root": "alice/", "prefix": "alice/out/"}
        event["onConflict"] = "refuse"
        event["submittedAt"] = "2026-08-20T10:00:00+00:00"
    return event


def _plan(fake):
    return json.loads(fake.puts[-1]["Body"])


@pytest.fixture(autouse=True)
def _quiet_notifications(monkeypatch):
    """The failure path enqueues a notification; the tests are about the plan, not the message."""
    monkeypatch.setattr(notify, "emit_notification", lambda *a, **kw: None)


# ── Expansion, relative keys and destinations ────────────────────────────────


def test_a_folders_objects_keep_their_structure_under_the_destination():
    """The relative-key rule: a folder arrives with its shape intact, one level under where it was
    dropped, whatever depth it lived at."""
    fake = _install({"alice/reports/2026/q1.csv": 91234, "alice/reports/notes.txt": 12})

    result = m.handler(_event(), None)

    objects = _plan(fake)["items"][0]["objects"]
    assert [o["destKey"] for o in objects] == [
        "alice/out/reports/2026/q1.csv",
        "alice/out/reports/notes.txt",
    ]
    assert [o["relKey"] for o in objects] == ["2026/q1.csv", "notes.txt"]
    assert result["objectCount"] == 2
    assert result["totalBytes"] == 91246


# ── The closed exclusion set ─────────────────────────────────────────────────


def test_the_portal_managed_folders_are_swept_out_of_an_expansion_that_reaches_them_from_ABOVE():
    """The second anchor, and a deliberate second rule rather than a duplicate: the selection rules
    anchor on the item the user named and none of them looks up.

    **The input is one the front door cannot produce, and that is the point rather than a flaw in
    the test.** The only strict ancestor of these two folders is the space root, which the selection
    rules refuse as an item — so this asserts the second half of a pair that closes the ancestor
    class from both ends, and it is what would catch the day the first half was relaxed.
    """
    fake = _install(
        {
            "alice/reports/a.csv": 1,
            "alice/user_settings/inbox.json": 1,
            "alice/athenaresults/r.csv": 1,
        }
    )

    m.handler(_event([{"kind": "folder", "key": "alice/"}]), None)

    assert [o["srcKey"] for o in _plan(fake)["items"][0]["objects"]] == ["alice/reports/a.csv"]


# ── Identity, overlaps and duplicates ────────────────────────────────────────


def test_one_item_containing_another_refuses_the_WHOLE_request():
    """Copying an object twice and silently dropping one are both worse than a clear refusal, and
    neither of the two items is the wrong one."""
    _install({"alice/reports/a.csv": 1})

    with pytest.raises(TerminalError) as err:
        m.handler(
            _event(
                [
                    {"kind": "folder", "key": "alice/reports/"},
                    {"kind": "file", "key": "alice/reports/a.csv"},
                ]
            )
        , None)

    assert err.value.reason == "overlapping_items"


def test_a_duplicate_is_kind_AND_key_never_the_key_alone():
    """One key can arrive with two kinds — a folder key is normalised to a trailing slash and a file
    key is not — and collapsing on the key alone carried a zero-byte placeholder and none of the
    folder's contents while reporting success, with the outcome depending on list order."""
    _install({"alice/reports/": 0, "alice/reports/a.csv": 1})

    with pytest.raises(TerminalError) as err:
        m.handler(
            _event(
                [
                    {"kind": "file", "key": "alice/reports/"},
                    {"kind": "folder", "key": "alice/reports/"},
                ]
            )
        , None)

    assert err.value.reason == "overlapping_items"


# ── Per-item outcomes ────────────────────────────────────────────────────────


def test_a_missing_file_fails_ITS_ITEM_and_the_rest_proceed():
    """The browser has always carried on with the rest, and a select-all must still do what it may.
    file-send fails the whole request here on purpose; this plane deliberately does not."""
    fake = _install({"alice/reports/a.csv": 1})

    result = m.handler(
        _event(
            [
                {"kind": "file", "key": "alice/gone.csv"},
                {"kind": "folder", "key": "alice/reports/"},
            ]
        )
    , None)

    assert [(o["itemKey"], o["outcome"]) for o in result["outcomes"]] == [
        ("alice/gone.csv", "source_missing"),
        ("alice/reports/", "cleared"),
    ]
    assert [item["itemKey"] for item in _plan(fake)["items"]] == ["alice/reports/"]


# ── The caps ─────────────────────────────────────────────────────────────────


def test_the_object_cap_is_enforced_INSIDE_the_walk(monkeypatch):
    """A cap checked afterwards is one the verb has already paid for: the list it bounds accumulates
    in memory as it grows, so the check that exists to refuse a folder would run after the
    allocation that exhausts the Lambda.

    **Asserted on the NUMBER the refusal names**, which is the only externally visible difference
    between the two implementations: a check inside the walk can only say what it had reached and
    that it was still counting, where one after it would name the true total.
    """
    monkeypatch.setattr(m, "FILE_OPS_MAX_OBJECTS", 5)
    _install({f"alice/reports/f{n:04d}.csv": 1 for n in range(3000)})

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "too_many_objects"
    assert "reached 6 objects and was still counting" in err.value.detail
    assert "3000" not in err.value.detail


# ── The plan ─────────────────────────────────────────────────────────────────


def test_the_plan_goes_to_S3_and_only_its_pointer_and_counts_ride_on_the_state():
    """At the object cap the list is tens of megabytes against a 256 KB payload limit."""
    fake = _install({"alice/reports/a.csv": 4})

    result = m.handler(_event(), None)

    assert result["planKey"] == "file-ops/req-1/plan.json"
    assert fake.puts[-1]["Bucket"] == "admin-bkt"
    assert "objects" not in json.dumps(result)


def test_the_portal_managed_folders_swept_from_an_expansion_are_exactly_these_two():
    """The two folders swept out of an expansion at a space root, spelled out."""
    assert m._PORTAL_MANAGED_FOLDERS == ("athenaresults", "user_settings")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
