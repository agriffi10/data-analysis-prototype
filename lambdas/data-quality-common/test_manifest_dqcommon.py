"""Tests for dqcommon.manifest — the manifest read shared by the SPEC-111/112 verbs.

The fault classification is the whole point of this module: a retryable S3 fault must
reach the Step Function as a TransientError (so the Retry re-runs the verb), and anything
else must be a typed terminal rather than a bare exception the SFN records as opaque.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import pytest
from cpcommon.errors import TerminalError, TransientError
from dqcommon import manifest, messages

MANIFEST = {"format": "csv", "partitionKeys": [], "files": [{"key": "a.csv", "size": 1, "columns": []}]}


class _FakeClientError(Exception):
    """Mimics botocore's ClientError enough for cpcommon.errors.error_code.

    botocore ships in the Lambda RUNTIME but is not a test dependency of this repo, so the
    suites fake it (same shape as the inspect-source suite's).
    """

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _FakeS3:
    def __init__(self, body=None, error=None):
        self._body = body
        self._error = error
        self.calls = []

    def get_object(self, Bucket, Key):  # boto3 kwarg casing
        self.calls.append((Bucket, Key))
        if self._error:
            raise self._error
        return {"Body": _Body(self._body)}


def _install(monkeypatch, fake):
    monkeypatch.setattr(manifest.clients, "s3", lambda: fake)
    return fake


def test_it_returns_the_parsed_manifest(monkeypatch):
    fake = _install(monkeypatch, _FakeS3(body=json.dumps(MANIFEST).encode()))
    assert manifest.load("bkt", "alice/_data-quality-reports/r/manifest.json") == MANIFEST
    assert fake.calls == [("bkt", "alice/_data-quality-reports/r/manifest.json")]


def test_a_retryable_fault_is_transient(monkeypatch):
    """A one-off SlowDown must not fail a request whose inspection work is already done."""
    _install(monkeypatch, _FakeS3(error=_FakeClientError("SlowDown")))
    with pytest.raises(TransientError):
        manifest.load("bkt", "k")


def test_a_missing_manifest_is_a_terminal(monkeypatch):
    """No retry fixes a manifest that isn't there — inspect-source already wrote it."""
    _install(monkeypatch, _FakeS3(error=_FakeClientError("NoSuchKey")))
    with pytest.raises(TerminalError) as exc:
        manifest.load("bkt", "k")
    assert exc.value.reason == messages.INVALID_REQUEST


def test_an_access_denied_is_a_terminal(monkeypatch):
    _install(monkeypatch, _FakeS3(error=_FakeClientError("AccessDenied")))
    with pytest.raises(TerminalError) as exc:
        manifest.load("bkt", "k")
    assert exc.value.reason == messages.INVALID_REQUEST


def test_a_corrupt_manifest_is_a_typed_terminal_not_a_bare_valueerror(monkeypatch):
    """A bare ValueError would be recorded by the SFN as an opaque failure, and its raw
    text would become the user-facing reason (the leak SPEC-106 FR-008 forbids)."""
    _install(monkeypatch, _FakeS3(body=b"{not json"))
    with pytest.raises(TerminalError) as exc:
        manifest.load("bkt", "k")
    assert exc.value.reason == messages.INVALID_REQUEST
