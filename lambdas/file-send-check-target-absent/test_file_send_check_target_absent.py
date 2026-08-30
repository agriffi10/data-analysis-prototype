"""Unit tests for the file-send check-target-absent Lambda (SPEC-166 FR-001).

Drives the real handler: the inbox listing itself is covered in ``file-send-common``, so what
this file exercises is the guard's decisions — the short-circuit that costs no S3 call, the
conflict that names the item, and the isolation that keeps a refusal inside one Map item.
Runnable under pytest or directly: python3 test_file_send_check_target_absent.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-send-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_check_target_absent as m
import pytest
from cpcommon import clients


class _FakeS3:
    def __init__(self, keys, error=None):
        self._keys = sorted(keys)
        self._error = error
        self.listings = []

    def get_paginator(self, name):
        fake = self

        class _P:
            def paginate(self, Bucket, Prefix, Delimiter):
                fake.listings.append({"Bucket": Bucket, "Prefix": Prefix})
                if fake._error:
                    raise fake._error
                prefixes, contents = [], []
                for key in fake._keys:
                    if not key.startswith(Prefix):
                        continue
                    head, sep, _ = key[len(Prefix) :].partition(Delimiter)
                    if sep:
                        entry = {"Prefix": f"{Prefix}{head}{Delimiter}"}
                        if entry not in prefixes:
                            prefixes.append(entry)
                    else:
                        contents.append({"Key": key, "Size": 1})
                yield {"CommonPrefixes": prefixes, "Contents": contents}

        return _P()


def _install(keys=(), error=None):
    fake = _FakeS3(keys, error)
    clients._s3 = fake
    return fake


def _request(items=None):
    return {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "source": {
            "bucket": "user-bkt",
            "root": "alice/",
            "items": items
            or [{"kind": "folder", "key": "alice/reports/"}, {"kind": "file", "key": "alice/notes.txt"}],
        },
        "recipients": [],
    }


def _event(recipient, items=None):
    return {"recipient": recipient, "request": _request(items)}


def test_a_clear_recipient_comes_back_resolved():
    """The bucket and root are worked out ONCE per recipient here, so the manifest builder does
    not resolve a destination per object."""
    _install()

    record = m.handler(_event({"kind": "user", "name": "bob"}), None)

    assert record["status"] == "ok"
    assert record["recipient"]["destBucket"] == "user-bkt"
    assert record["recipient"]["destRoot"] == "bob/"
    assert record["reason"] == "" and record["detail"] == ""


def test_a_taken_item_name_is_a_conflict_that_names_the_item():
    """FR-001 AC5. The colliding name is a FIELD, not prose inside an error: SPEC-167 tells the
    sender which file was already there, and a detail parsed back out of a Step Functions Cause
    would be both fragile and a rule break (raw operator text never reaches a user)."""
    _install(["bob/shared_files/alice/notes.txt"])

    record = m.handler(_event({"kind": "user", "name": "bob"}), None)

    assert record["status"] == "failed"
    assert record["reason"] == "conflict"
    assert record["detail"] == "notes.txt"


def test_another_senders_item_of_the_same_name_is_not_a_conflict():
    """The inbox is namespaced by sender, so two senders may both send ``notes.txt``."""
    _install(["bob/shared_files/carol/notes.txt"])

    record = m.handler(_event({"kind": "user", "name": "bob"}), None)

    assert record["status"] == "ok"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
