"""Unit tests for what a verb after inspect-source may trust: the manifest read back, and the decision carried.

The S3 client is faked rather than the loader, because the containment under test lives inside the
loader and most verb suites replace the loader with a stub.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError
from dqcommon import manifest, messages, sql

BUCKET = "dq-user-bkt"
KEY = "alice/_data-quality-reports/r-1/manifest.json"


class _FakeS3:
    """Serves one manifest body, built from keys or given whole."""

    def __init__(self, files=(), body=None):
        document = {"files": [{"key": k, "size": 1, "columns": []} for k in files]}
        self.body = body if body is not None else json.dumps(document).encode()

    def get_object(self, Bucket, Key):  # boto3's kwarg casing
        return {"Body": _Body(self.body)}


class _Body:
    """A streaming body that is read whole, as the loader reads it."""

    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


@pytest.mark.parametrize(
    "files",
    [["bob/private.csv"], ["alice/sales-2024/a.csv"], ["alice/sales/a.csv", "alice/salesman.csv"]],
    ids=["another-tenant", "sibling-sharing-the-stem", "one-foreign-among-many"],
)
def test_a_manifest_naming_a_file_outside_the_location_is_refused(monkeypatch, files):
    """A foreign key is refused whoever wrote the object, and the detail never repeats the key."""
    monkeypatch.setattr(clients, "s3", lambda: _FakeS3(files))

    with pytest.raises(TerminalError) as exc:
        manifest.load(BUCKET, KEY, "alice/sales")

    assert exc.value.reason == messages.INVALID_REQUEST
    assert exc.value.detail == f"manifest {KEY} names a file outside the checked location"


@pytest.mark.parametrize(
    "body",
    [b"{}", b'{"files": null}', b'{"files": {"key": "alice/sales/a.csv"}}', b'["alice/sales/a.csv"]'],
    ids=["no-file-list", "null-file-list", "file-list-not-a-list", "not-an-object"],
)
def test_a_manifest_without_a_file_list_is_refused_rather_than_read_as_empty(monkeypatch, body):
    """Every caller falls back to an empty list, so a missing one would profile nothing and pass."""
    monkeypatch.setattr(clients, "s3", lambda: _FakeS3(body=body))

    with pytest.raises(TerminalError) as exc:
        manifest.load(BUCKET, KEY, "alice/sales")

    assert (exc.value.reason, exc.value.detail) == (messages.INVALID_REQUEST, f"manifest {KEY} carries no file list")


@pytest.mark.parametrize(
    ("location", "files"),
    [
        ("alice/sales", ["alice/sales/a.csv", "alice/sales/year=2025/b.csv"]),
        ("alice/sales/", ["alice/sales/a.csv"]),
        ("alice/report.csv", ["alice/report.csv"]),
    ],
    ids=["folder", "folder-with-slash", "single-file"],
)
def test_the_files_inspect_source_lists_are_read_back(monkeypatch, location, files):
    """The positive control: the folder listing and the single file's exact key both pass."""
    monkeypatch.setattr(clients, "s3", lambda: _FakeS3(files))

    loaded = manifest.load(BUCKET, KEY, location)

    assert [entry["key"] for entry in loaded["files"]] == files


@pytest.mark.parametrize("value", ["", "   ", 7, ["s3://b/k"]], ids=["empty", "blank", "number", "list"])
def test_a_carried_decision_that_is_neither_none_nor_a_path_is_refused(value):
    """Only an absent key has its own test beside the verbs; a malformed value is refused the same way."""
    with pytest.raises(TerminalError) as exc:
        sql.carried_path_filter({"pathFilter": value})

    assert (exc.value.reason, exc.value.detail) == (messages.INVALID_REQUEST, "malformed field 'pathFilter'")
