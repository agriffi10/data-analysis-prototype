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
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_check_target_absent as m
import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError


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


def test_a_space_recipient_resolves_in_the_shared_bucket():
    _install()

    record = m.handler(_event({"kind": "space", "name": "finance"}), None)

    assert record["recipient"]["destBucket"] == "shared-bkt"
    assert record["recipient"]["destRoot"] == "finance/"


def test_an_unresolved_recipient_short_circuits_without_any_s3_call():
    """FR-001 AC3. A send to five recipients where two do not exist must not list two inboxes
    that do not exist either — and the annotated reason is carried, not re-derived."""
    fake = _install()

    record = m.handler(_event({"kind": "user", "name": "ghost", "invalid": "unknown_user"}), None)

    assert record["status"] == "failed"
    assert record["reason"] == "unknown_user"
    assert fake.listings == []


def test_a_taken_item_name_is_a_conflict_that_names_the_item():
    """FR-001 AC5. The colliding name is a FIELD, not prose inside an error: SPEC-167 tells the
    sender which file was already there, and a detail parsed back out of a Step Functions Cause
    would be both fragile and a rule break (raw operator text never reaches a user)."""
    _install(["bob/shared_files/alice/notes.txt"])

    record = m.handler(_event({"kind": "user", "name": "bob"}), None)

    assert record["status"] == "failed"
    assert record["reason"] == "conflict"
    assert record["detail"] == "notes.txt"


def test_the_conflict_is_per_item_name_not_per_send():
    """FR-001 AC2. A first send of ``reports/`` to a recipient who already holds ``budget.csv``
    from this sender is not a conflict — only a name this send would actually create is."""
    _install(["bob/shared_files/alice/budget.csv"])

    record = m.handler(_event({"kind": "user", "name": "bob"}), None)

    assert record["status"] == "ok"


def test_another_senders_item_of_the_same_name_is_not_a_conflict():
    """The inbox is namespaced by sender, so two senders may both send ``notes.txt``."""
    _install(["bob/shared_files/carol/notes.txt"])

    record = m.handler(_event({"kind": "user", "name": "bob"}), None)

    assert record["status"] == "ok"


def test_the_recipients_own_file_of_the_same_name_is_not_a_conflict():
    """Only the inbox is consulted. A recipient with their own ``notes.txt`` in their space root
    still receives one — it lands under ``shared_files/{sender}/`` and cannot collide."""
    _install(["bob/notes.txt", "bob/reports/notes.txt"])

    record = m.handler(_event({"kind": "user", "name": "bob"}), None)

    assert record["status"] == "ok"


def test_the_first_colliding_item_reported_is_the_first_one_selected():
    """Deterministic, and in the order the sender chose rather than S3's — the reported name is
    the one they will go looking for."""
    _install(["bob/shared_files/alice/notes.txt", "bob/shared_files/alice/reports/x.csv"])

    record = m.handler(_event({"kind": "user", "name": "bob"}), None)

    assert record["detail"] == "reports"


def test_a_listing_fault_fails_the_item_rather_than_reading_as_clear():
    """The refusal direction that matters: a guard that cannot see the destination must not fall
    through to "nothing is there", which is the one answer that ends in an overwrite."""
    _install(error=RuntimeError("boom"))

    with pytest.raises(TransientError):
        m.handler(_event({"kind": "user", "name": "bob"}), None)


def test_an_unknown_recipient_kind_fails_the_item_rather_than_guessing_a_bucket():
    """Unreachable through validate-authorize, which shape-checks the kind. Guessing wrong here
    writes one person's files into another's space."""
    _install()

    with pytest.raises(TerminalError):
        m.handler(_event({"kind": "team", "name": "bob"}), None)


def test_every_record_carries_every_field_whatever_the_outcome():
    """The Map's records are read by ASL Pass states, and a Pass referencing an absent path
    raises an uncatchable States.Runtime — so a sparse record would kill the execution on
    exactly the refusal it was recording."""
    _install(["bob/shared_files/alice/notes.txt"])
    records = [
        m.handler(_event({"kind": "user", "name": "bob"}), None),
        m.handler(_event({"kind": "user", "name": "carol"}), None),
        m.handler(_event({"kind": "user", "name": "ghost", "invalid": "unknown_user"}), None),
    ]

    for record in records:
        assert set(record) == {"status", "recipient", "reason", "detail"}
        assert isinstance(record["recipient"], dict)


def test_the_verb_reaches_no_notifier_at_all():
    """Every per-recipient outcome is told to the sender ONCE, from the terminal summary
    (SPEC-167), so a decorator emit here would be the second message about one conflict.

    Asserted as the ABSENCE OF THE IMPORT rather than by counting emits: a test that counted
    them would pass just as happily against a decorator whose emit had silently become a no-op,
    and the thing being fixed is that this verb must not be a notification channel."""
    assert "notify" not in m.__dict__, "check-target-absent imported a notifier"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
