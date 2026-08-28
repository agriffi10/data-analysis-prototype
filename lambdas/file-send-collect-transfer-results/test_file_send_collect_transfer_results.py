"""Unit tests for the file-send collect-transfer-results Lambda (SPEC-166 FR-003).

Attribution is where per-recipient isolation lives now that the fan-out is over
(recipient x object) pairs, so these tests are about who is told what: a recipient with one
failed item did not receive the send, a recipient the guard already refused keeps its own
reason, and an export that cannot be attributed fails the whole request rather than reporting
success. Runnable under pytest or directly:
python3 test_file_send_collect_transfer_results.py.
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

import file_send_collect_transfer_results as m
import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError

_MANIFEST_KEY = "file-send/req-1/results/run/manifest.json"


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return payload if isinstance(payload := self._payload, bytes) else json.dumps(payload).encode()


class _FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, **kwargs):
        try:
            return {"Body": _Body(self.objects[kwargs["Key"]])}
        except KeyError as err:
            raise _S3Error("NoSuchKey") from err


def _setup(objects=None):
    clients._s3 = _FakeS3(objects or {})
    sent = []
    m.notify.emit_notification = lambda user, message, **kw: sent.append((user, message))
    return sent


def _cleared(kind, name):
    return {
        "status": "ok",
        "recipient": {"kind": kind, "name": name, "destBucket": "user-bkt", "destRoot": f"{name}/"},
        "reason": "",
        "detail": "",
    }


def _refused(kind, name, reason, detail=""):
    return {
        "status": "failed",
        "recipient": {"kind": kind, "name": name},
        "reason": reason,
        "detail": detail,
    }


def _event(guard_results, item_count=2, map_run=True):
    event = {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "items": []},
        "objectCount": 2,
        "guardResults": guard_results,
        "transfer": {
            "manifestBucket": "admin-bkt",
            "manifestKey": "file-send/req-1/transfer-manifest.jsonl",
            "resultsBucket": "admin-bkt",
            "resultsPrefix": "file-send/req-1/results",
            "itemCount": item_count,
        },
    }
    if map_run:
        event["mapRun"] = {"ResultWriterDetails": {"Bucket": "admin-bkt", "Key": _MANIFEST_KEY}}
    return event


def _succeeded(copied, failures=()):
    return [{"Output": json.dumps({"copied": copied, "failures": list(failures)})}]


def _export(records, group="SUCCEEDED"):
    return {
        _MANIFEST_KEY: {"ResultFiles": {group: [{"Key": f"file-send/req-1/results/{group}_0.json"}]}},
        f"file-send/req-1/results/{group}_0.json": records,
    }


def test_a_clean_transfer_leaves_every_recipient_ok():
    _setup(_export(_succeeded(2)))

    outcomes = m.handler(_event([_cleared("user", "bob")]), None)["outcomes"]

    assert outcomes == [
        {"kind": "user", "name": "bob", "status": "ok", "reason": "", "detail": "", "failedItems": 0}
    ]


def test_one_failed_item_fails_that_recipient_and_only_that_recipient():
    """FR-003 AC1. A recipient is ``ok`` only when NONE of its items failed: a folder silently
    short of a file is the outcome this plane must never report as a success."""
    _setup(_export(_succeeded(3, [{"recipient": "bob", "kind": "user", "reason": "copy_failed"}])))

    outcomes = m.handler(
        _event([_cleared("user", "bob"), _cleared("user", "carol")], item_count=4), None
    )["outcomes"]

    assert [(o["name"], o["status"], o["failedItems"]) for o in outcomes] == [
        ("bob", "failed", 1),
        ("carol", "ok", 0),
    ]


def test_an_export_short_of_the_manifests_items_fails_the_whole_request():
    """FR-003 AC5. An export can be well-formed and still cover only some of the batches, and a
    partial export read as a clean run tells every recipient the send went well without having
    checked."""
    _setup(_export(_succeeded(1)))

    with pytest.raises(TerminalError) as caught:
        m.handler(_event([_cleared("user", "bob")], item_count=2), None)

    assert caught.value.reason == "transfer_results_unreadable"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
