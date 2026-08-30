"""Unit tests for the archive delete-archived Lambda (SPEC-171 FR-005).

The batching discipline is ``arcommon.delete``'s and has its own suite; what only this verb can
get wrong is the ASYMMETRY with delete-source — a partial sweep here is a FLAG on a successful
run, where a partial source deletion is a terminal failure — and the listing carrying the objects
a default predicate would drop. Runnable under pytest or directly:
python3 test_archive_delete_archived.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ARCHIVE_BUCKET", "archive-bkt")

import archive_delete_archived as m
import pytest
from arcommon import notify
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ID = "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c"
_ARCHIVE_ROOT = f"personal/alice/archive/{_ARCHIVE_ID}/"


class _FakeS3:
    def __init__(self, contents, errors=()):
        self._contents = contents
        self._errors = list(errors)
        self.deleted = []
        self.honour_prefix = True

    def get_paginator(self, name):
        return self

    def paginate(self, **kwargs):
        # `honour_prefix=False` models the shape the pre-issue check exists for: a listing that
        # returns a key outside the prefix it was asked for. S3 does not do that, which is the
        # point — the check is defence in depth, and it cannot be exercised through a fake that
        # enforces the very guarantee being defended against.
        prefix = kwargs["Prefix"] if self.honour_prefix else ""
        yield {
            "Contents": [
                {"Key": key, "Size": size}
                for key, size in self._contents
                if key.startswith(prefix)
            ]
        }

    def delete_objects(self, Bucket, Delete):
        self.deleted.extend(obj["Key"] for obj in Delete["Objects"])
        return {"Errors": self._errors}


def _install(contents=None, errors=()):
    contents = contents if contents is not None else [
        (f"{_ARCHIVE_ROOT}reports/q1.csv", 9),
        (f"{_ARCHIVE_ROOT}empty/", 0),
        (f"{_ARCHIVE_ROOT}_manifest.json", 120),
    ]
    fake = _FakeS3(contents, errors)
    clients._s3 = fake
    return fake


def _request(**overrides):
    base = {
        "requestId": _REQUEST_ID,
        "mode": "restore",
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "kind": "personal", "name": "alice"},
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT, "archiveId": _ARCHIVE_ID},
        "objectCount": 3,
        "totalBytes": 129,
        "transferOutcome": {"copied": 3, "failed": 0, "expected": 3, "complete": True},
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _sink(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(m.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def test_the_whole_archive_prefix_goes_including_its_own_record():
    """FR-005 AC1. `_manifest.json` is this plane's integrity record and is hidden by the shared
    paginator's default predicate — a sweep that inherited it would leave the one object nobody
    would think to look for."""
    fake = _install()

    out = m.handler(_request(), None)

    assert set(fake.deleted) == {
        f"{_ARCHIVE_ROOT}reports/q1.csv",
        f"{_ARCHIVE_ROOT}empty/",
        f"{_ARCHIVE_ROOT}_manifest.json",
    }
    assert out["cleanup"] == {"deleted": 3, "residue": 0, "cleanupIncomplete": False}


def test_a_key_outside_the_prefix_refuses_before_anything_is_issued():
    """`assert_deletable` checks the whole list up front, so a listing that somehow returned a
    foreign key fails the verb rather than stopping a deletion half way through."""
    fake = _install(contents=[("personal/bob/archive/x/theirs.csv", 9)])
    fake.honour_prefix = False

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(), None)

    assert caught.value.reason == "forbidden"
    assert fake.deleted == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
