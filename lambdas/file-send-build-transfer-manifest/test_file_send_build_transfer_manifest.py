"""Unit tests for the file-send build-transfer-manifest Lambda (SPEC-166 FR-002).

Drives the real handler against a fake S3, so the manifest asserted here is the bytes that
would reach the Map's ``ItemReader``. Runnable under pytest or directly:
python3 test_file_send_build_transfer_manifest.py.
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

import file_send_build_transfer_manifest as m
import pytest
from cpcommon import clients
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError, TransientError
from fscommon import notify

_PLAN = {
    "source": {"bucket": "user-bkt", "root": "alice/"},
    "sender": "alice",
    "objects": [
        {"item": "reports", "relKey": "2026/q1.csv", "srcKey": "alice/reports/2026/q1.csv", "size": 91234},
        {"item": "notes.txt", "relKey": "", "srcKey": "alice/notes.txt", "size": 512},
    ],
    "objectCount": 2,
    "totalBytes": 91746,
}


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, plan=None, put_error=None, get_error=None):
        self._plan = _PLAN if plan is None else plan
        self._put_error = put_error
        self._get_error = get_error
        self.puts = []

    def get_object(self, Bucket, Key):
        if self._get_error:
            raise _S3Error(self._get_error)

        class _B:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return self._payload

        return {"Body": _B(json.dumps(self._plan).encode())}

    def put_object(self, Bucket, Key, Body, ContentType):
        if self._put_error:
            raise _S3Error(self._put_error)
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        return {}


def _install(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


def _cleared(kind, name, root):
    return {
        "status": "ok",
        "recipient": {"kind": kind, "name": name, "destBucket": "user-bkt" if kind == "user" else "shared-bkt", "destRoot": root},
        "reason": "",
        "detail": "",
    }


def _event(guard_results):
    return {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "items": []},
        "copyPlanKey": "file-send/req-1/copy-plan.json",
        "objectCount": 2,
        "totalBytes": 91746,
        "guardResults": guard_results,
    }


def _lines(fake):
    return [json.loads(line) for line in fake.puts[0]["Body"].decode().splitlines()]


def test_one_line_per_recipient_and_object():
    fake = _install()

    result = m.handler(_event([_cleared("user", "bob", "bob/"), _cleared("space", "finance", "finance/")]), None)

    assert result["transfer"]["itemCount"] == 4
    assert len(_lines(fake)) == 4


def test_every_destination_is_the_shared_layout():
    """FR-002 AC1. The keys are the ones a recipient sees forever, so they are asserted whole
    rather than by prefix — a folder item keeps its structure, a file item arrives as a file."""
    fake = _install()

    m.handler(_event([_cleared("user", "bob", "bob/")]), None)

    assert sorted(line["destKey"] for line in _lines(fake)) == [
        "bob/shared_files/alice/notes.txt",
        "bob/shared_files/alice/reports/2026/q1.csv",
    ]


def test_a_line_carries_everything_the_engine_copies_and_attributes_by():
    """The manifest is the ONLY thing the batch copier and the collector see: the copier indexes
    the four location fields, and attribution is by the ``(kind, name)`` PAIR because nothing
    stops a shared space being named after a user."""
    fake = _install()

    m.handler(_event([_cleared("user", "bob", "bob/")]), None)

    line = next(line for line in _lines(fake) if line["srcKey"].endswith("notes.txt"))
    assert line == {
        "recipient": "bob",
        "kind": "user",
        "srcBucket": "user-bkt",
        "srcKey": "alice/notes.txt",
        "destBucket": "user-bkt",
        "destKey": "bob/shared_files/alice/notes.txt",
        "size": 512,
    }


def test_a_refused_recipient_contributes_no_lines():
    """FR-002 AC2. Its terminal outcome was decided before this verb ran, and a line here would
    copy for a recipient the guard had just refused."""
    fake = _install()
    refused = {"status": "failed", "recipient": {"kind": "user", "name": "carol"}, "reason": "conflict", "detail": "notes.txt"}

    result = m.handler(_event([_cleared("user", "bob", "bob/"), refused]), None)

    assert result["transfer"]["itemCount"] == 2
    assert {line["recipient"] for line in _lines(fake)} == {"bob"}


def test_the_recipients_objects_are_adjacent_in_the_manifest():
    """The batcher batches by count over the file's order, so a recipient-major manifest makes a
    batch usually belong to ONE recipient — a whole-batch failure then costs one recipient
    rather than eight."""
    fake = _install()

    m.handler(_event([_cleared("user", "bob", "bob/"), _cleared("user", "carol", "carol/")]), None)

    assert [line["recipient"] for line in _lines(fake)] == ["bob", "bob", "carol", "carol"]


def test_no_manifest_is_written_when_every_recipient_was_refused():
    """The ordinary "everybody already had it" send, not an error. The plan is not even read: the
    object would be an empty file the Map is about to be told to skip."""
    fake = _install()
    refused = {"status": "failed", "recipient": {"kind": "user", "name": "carol"}, "reason": "conflict", "detail": "notes.txt"}

    result = m.handler(_event([refused]), None)

    assert result["transfer"]["itemCount"] == 0
    assert result["transfer"]["manifestKey"] == ""
    assert fake.puts == []


def test_the_results_prefix_is_reported_on_both_paths():
    """The collector is reached whether or not the Map ran, so the block it reads must have the
    same shape either way."""
    _install()
    refused = {"status": "failed", "recipient": {"kind": "user", "name": "carol"}, "reason": "conflict", "detail": ""}

    skipped = m.handler(_event([refused]), None)["transfer"]
    copied = m.handler(_event([_cleared("user", "bob", "bob/")]), None)["transfer"]

    assert skipped["resultsPrefix"] == copied["resultsPrefix"] == "file-send/req-1/results"
    assert skipped["resultsBucket"] == copied["resultsBucket"] == cpconfig.ADMIN_BUCKET


def test_the_guard_results_are_carried_for_the_collector():
    """Every recipient's outcome — including the refused ones that contributed no lines — is
    shaped downstream from these records, so dropping them here would lose the refusals."""
    _install()
    refused = {"status": "failed", "recipient": {"kind": "user", "name": "carol"}, "reason": "conflict", "detail": "notes.txt"}

    result = m.handler(_event([_cleared("user", "bob", "bob/"), refused]), None)

    assert result["guardResults"] == [_cleared("user", "bob", "bob/"), refused]


def test_the_manifest_carries_no_trailing_newline():
    """A blank final line is a line the JSONL reader may hand back as an empty item, and an
    empty item reaches the copier as a transfer with no source."""
    fake = _install()

    m.handler(_event([_cleared("user", "bob", "bob/")]), None)

    assert not fake.puts[0]["Body"].decode().endswith("\n")


def test_an_unreadable_plan_fails_the_whole_request_and_notifies():
    """A manifest that cannot be built completely must not be built partially — and this IS a
    whole-request verb, so its decorator is what tells the sender before the Catch records it."""
    _install(get_error="NoSuchKey")
    sent = []
    notify.emit_notification = lambda user, message, **kw: sent.append((user, message))

    with pytest.raises(TerminalError):
        m.handler(_event([_cleared("user", "bob", "bob/")]), None)

    assert sent and sent[0][0] == "alice"


def test_a_throttled_write_is_transient_so_the_state_retries_the_verb():
    """Safe because the key is a pure function of the request id: the retry overwrites the first
    attempt's object rather than leaving two manifests behind."""
    _install(put_error="SlowDown")

    with pytest.raises(TransientError):
        m.handler(_event([_cleared("user", "bob", "bob/")]), None)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
