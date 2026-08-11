"""Unit tests for the file-send inspect-source Lambda (SPEC-165).

The expansion rules and the caps have their own suite in ``file-send-common``; this file
exercises them THROUGH the real handler, and covers what only the verb can carry: the plan
pointer coming back on the state, the object list not coming back with it, and the sender being
notified before the Catch records a refusal. Runnable under pytest or directly:
python3 test_file_send_inspect_source.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-send-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_inspect_source as m
import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError
from fscommon import notify


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, objects):
        self._objects = objects
        self.puts = []

    def get_paginator(self, name):
        objects = self._objects

        class _P:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": k, "Size": s}
                        for k, s in sorted(objects.items())
                        if k.startswith(Prefix)
                    ]
                }

        return _P()

    def head_object(self, Bucket, Key):
        if Key not in self._objects:
            raise _S3Error("NoSuchKey")
        return {"ContentLength": self._objects[Key]}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        return {}


def _install(objects):
    fake = _FakeS3(objects)
    clients._s3 = fake
    return fake


def _event(items=None):
    return {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "source": {
            "bucket": "user-bkt",
            "root": "alice/",
            "items": items or [{"kind": "folder", "key": "alice/reports/"}],
        },
        "recipients": [{"kind": "user", "name": "bob"}],
    }


@pytest.fixture
def notified(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, message, **kw: sent.append((user, message)))
    monkeypatch.setattr(m.notify, "emit_notification", lambda user, message, **kw: sent.append((user, message)))
    return sent


def test_the_state_carries_the_plans_KEY_and_its_totals():
    _install({"alice/reports/q1.csv": 10, "alice/reports/2026/q2.csv": 20})

    result = m.handler(_event(), None)

    assert result["copyPlanKey"] == "file-send/req-1/copy-plan.json"
    assert result["objectCount"] == 2
    assert result["totalBytes"] == 30


def test_the_validated_request_is_threaded_through_unchanged():
    """SPEC-166's states read the recipients and the source off this same object, so a verb that
    returned only its own additions would strand them."""
    _install({"alice/reports/q1.csv": 10})
    event = _event()

    result = m.handler(event, None)

    assert result["requestId"] == event["requestId"]
    assert result["actor"] == event["actor"]
    assert result["recipients"] == event["recipients"]
    assert result["source"] == event["source"]


def test_no_object_key_comes_back_on_the_state():
    """THE POINT OF THE POINTER. At the caps the object list is two orders of magnitude over the
    256 KB payload limit, so a key leaking onto the state is not a style problem — it is the
    beginning of the failure the plan exists to avoid, and it would first appear at scale."""
    _install({"alice/reports/q1.csv": 10, "alice/reports/2026/q2.csv": 20})

    result = m.handler(_event(), None)

    serialised = json.dumps(result)
    assert "q1.csv" not in serialised
    assert "objects" not in result


def test_the_plan_is_written_before_the_state_is_returned():
    _install({"alice/reports/q1.csv": 10})
    fake = clients._s3

    result = m.handler(_event(), None)

    assert [p["Key"] for p in fake.puts] == [result["copyPlanKey"]]
    assert json.loads(fake.puts[0]["Body"])["sender"] == "alice"


def test_a_refusal_notifies_the_sender_before_it_raises(notified):
    """The decorator's emit, which is what keeps a whole-request refusal from reaching the user
    as silence plus a failed execution they cannot see."""
    _install({"alice/empty/DO_NOT_DELETE.txt": 180})

    with pytest.raises(TerminalError) as caught:
        m.handler(_event([{"kind": "folder", "key": "alice/empty/"}]), None)

    assert caught.value.reason == "nothing_to_send"
    assert notified == [("alice", "Couldn't send: there was nothing to send in what you selected.")]


def test_a_refusal_writes_no_plan(notified):
    """Every cap and layout rule fires before the write, so a refused send leaves nothing
    behind — no orphan object in the admin bucket for a request that never ran."""
    fake = _install({"alice/reports/q1.csv": 10})

    with pytest.raises(TerminalError):
        m.handler(
            _event(
                [
                    {"kind": "folder", "key": "alice/reports/"},
                    {"kind": "file", "key": "alice/reports/q1.csv"},
                ]
            ),
            None,
        )

    assert fake.puts == []


def test_the_refusal_message_names_the_colliding_name(notified):
    """The token path end to end: the raise site supplies the sender's own folder name and the
    resolver fills it, so the sentence says which selection to change."""
    _install({"alice/x/reports/q1.csv": 10, "alice/y/reports/q2.csv": 10})

    with pytest.raises(TerminalError):
        m.handler(
            _event(
                [
                    {"kind": "folder", "key": "alice/x/reports/"},
                    {"kind": "folder", "key": "alice/y/reports/"},
                ]
            ),
            None,
        )

    assert '"reports"' in notified[0][1]


def test_a_shared_space_source_is_expanded_in_its_own_bucket():
    _install({"sales/reports/q1.csv": 10})
    event = _event()
    event["source"] = {
        "bucket": "shared-bkt",
        "root": "sales/",
        "items": [{"kind": "folder", "key": "sales/reports/"}],
    }

    result = m.handler(event, None)

    assert result["objectCount"] == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── SPEC-166 FR-005: the transfer caps ──────────────────────────────────────


def _recipients(count):
    return [{"kind": "user", "name": f"user{n}"} for n in range(count)]


def test_the_transfer_item_cap_counts_objects_TIMES_recipients(monkeypatch):
    """The bound neither per-source cap can express: 2 objects is legal and so are 3 recipients,
    and every manifest item is a full copy."""
    monkeypatch.setattr(m, "SEND_MAX_TRANSFER_ITEMS", 5)
    _install({"alice/reports/q1.csv": 10, "alice/reports/q2.csv": 10})
    event = {**_event(), "recipients": _recipients(3)}

    with pytest.raises(TerminalError) as caught:
        m.handler(event, None)

    assert caught.value.reason == "too_many_transfer_items"


def test_the_transfer_byte_cap_counts_bytes_TIMES_recipients(monkeypatch):
    """Table-share's own ceiling was short by a factor of its recipient cap for exactly this
    reason: the Map moves the source once PER RECIPIENT."""
    monkeypatch.setattr(m, "SEND_MAX_TRANSFER_BYTES", 50)
    _install({"alice/reports/q1.csv": 20})
    event = {**_event(), "recipients": _recipients(3)}

    with pytest.raises(TerminalError) as caught:
        m.handler(event, None)

    assert caught.value.reason == "transfer_too_large"


def test_a_transfer_exactly_at_the_caps_is_allowed(monkeypatch):
    monkeypatch.setattr(m, "SEND_MAX_TRANSFER_ITEMS", 2)
    monkeypatch.setattr(m, "SEND_MAX_TRANSFER_BYTES", 20)
    _install({"alice/reports/q1.csv": 10})
    event = {**_event(), "recipients": _recipients(2)}

    assert m.handler(event, None)["objectCount"] == 1


def test_the_transfer_caps_are_measured_on_the_REQUESTED_recipients(monkeypatch):
    """Before the guard, deliberately. Counting only the recipients who clear their conflict
    check would let the expensive half of the work happen first — the guard is one listing per
    recipient — and would make a refusal depend on what someone else's inbox happens to hold."""
    monkeypatch.setattr(m, "SEND_MAX_TRANSFER_ITEMS", 2)
    _install({"alice/reports/q1.csv": 10})
    event = {**_event(), "recipients": [{"kind": "user", "name": "ghost", "invalid": "unknown_user"}] * 1 + _recipients(2)}

    with pytest.raises(TerminalError) as caught:
        m.handler(event, None)

    assert caught.value.reason == "too_many_transfer_items"


def test_no_plan_is_written_when_the_transfer_caps_refuse(monkeypatch, notified):
    """A refused send leaves nothing behind — and the caps sit AFTER the expansion, so this is
    the one ordering worth pinning: the plan write must come after them, not before."""
    monkeypatch.setattr(m, "SEND_MAX_TRANSFER_ITEMS", 2)
    fake = _install({"alice/reports/q1.csv": 10})

    with pytest.raises(TerminalError):
        m.handler({**_event(), "recipients": _recipients(50)}, None)

    assert fake.puts == []
    assert notified and notified[0][0] == "alice"
