"""Unit tests for the archive rollback Lambda (SPEC-169 FR-004).

The verb on the branch of the commit gate that does not lead to a deletion. Two things are worth
testing about it: that it removes the partial copy by LISTING the archive prefix (so it catches
objects a batch copied before it died and never reported), and that it ALWAYS raises — with a
message that says nothing was deleted, and a different one when the cleanup itself left residue.

Runnable under pytest or directly: python3 test_archive_rollback.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ARCHIVE_BUCKET", "archive-bkt")

import archive_rollback as m
import pytest
from arcommon import notify
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ROOT = f"personal/alice/archive/{_REQUEST_ID}/"


class _FakeS3:
    def __init__(self, objects, errors_on=()):
        self._objects = objects
        self._errors_on = set(errors_on)
        self.deletes = []

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

    def delete_objects(self, Bucket, Delete):
        self.deletes.append({"Bucket": Bucket, "Keys": [o["Key"] for o in Delete["Objects"]]})
        return {
            "Errors": [
                {"Key": o["Key"]} for o in Delete["Objects"] if o["Key"] in self._errors_on
            ]
        }


def _install(objects, errors_on=()):
    fake = _FakeS3(objects, errors_on)
    clients._s3 = fake
    return fake


def _event(copied=6, failed=2, expected=8):
    return {
        "requestId": _REQUEST_ID,
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "kind": "personal", "name": "alice"},
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT},
        "objectCount": expected,
        "transferOutcome": {
            "copied": copied,
            "failed": failed,
            "expected": expected,
            "complete": False,
        },
    }


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def test_it_deletes_what_the_listing_finds_under_this_requests_prefix():
    """Listed rather than taken from the collector, and the listing is the strictly better
    answer: the prefix is this request's alone, so everything under it was put there by this
    archive — including anything a batch copied before it died and never reported."""
    _install({f"{_ARCHIVE_ROOT}reports/a.csv": 5, f"{_ARCHIVE_ROOT}reports/b.csv": 5})
    fake = clients._s3

    with pytest.raises(TerminalError):
        m.handler(_event(), None)

    assert fake.deletes == [
        {
            "Bucket": "archive-bkt",
            "Keys": [f"{_ARCHIVE_ROOT}reports/a.csv", f"{_ARCHIVE_ROOT}reports/b.csv"],
        }
    ]


def test_it_deletes_placeholders_and_hidden_objects_the_default_predicate_would_skip():
    """The shared paginator's default drops zero-byte objects and hidden segments, and both are
    things this plane deliberately archives. A rollback that inherited the default would leave
    exactly those behind, billed at the GLACIER 90-day minimum."""
    _install({f"{_ARCHIVE_ROOT}reports/empty/": 0, f"{_ARCHIVE_ROOT}_drafts/x.csv": 3})
    fake = clients._s3

    with pytest.raises(TerminalError):
        m.handler(_event(), None)

    assert set(fake.deletes[0]["Keys"]) == {
        f"{_ARCHIVE_ROOT}reports/empty/",
        f"{_ARCHIVE_ROOT}_drafts/x.csv",
    }


def test_it_never_reaches_outside_its_own_archive_prefix():
    """The prefix carries the request id, so one rollback can only ever touch one archive."""
    _install({
        f"{_ARCHIVE_ROOT}a.csv": 1,
        "personal/alice/archive/some-other-request/b.csv": 1,
        "personal/bob/archive/x/c.csv": 1,
    })
    fake = clients._s3

    with pytest.raises(TerminalError):
        m.handler(_event(), None)

    assert fake.deletes[0]["Keys"] == [f"{_ARCHIVE_ROOT}a.csv"]


def test_a_clean_rollback_still_fails_the_run_and_names_the_counts(_no_real_notifications):
    """FR-004 AC5. It ALWAYS raises: the gate has already decided this archive did not happen,
    and the only question left was whether the vault was left clean. The message names how many
    copied, how many did not, and says plainly that nothing was deleted."""
    _install({f"{_ARCHIVE_ROOT}a.csv": 1})

    with pytest.raises(TerminalError) as err:
        m.handler(_event(copied=6, failed=2, expected=8), None)

    assert err.value.reason == "archive_incomplete"
    assert err.value.tokens == {"copied": "6", "total": "8"}

    message = _no_real_notifications[0][1]
    assert "6 of 8" in message
    assert "nothing was deleted" in message


def test_residue_changes_the_message_and_not_the_outcome(_no_real_notifications):
    """FR-004 AC4. The property that matters is that the source is intact, and it is — so a
    rollback that itself failed partially reports the residue and carries on. The residue is
    unreachable by the user and is swept by the bucket's own expiry."""
    _install({f"{_ARCHIVE_ROOT}a.csv": 1, f"{_ARCHIVE_ROOT}b.csv": 1}, errors_on={f"{_ARCHIVE_ROOT}b.csv"})

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "archive_rollback_incomplete"
    assert err.value.tokens["residue"] == "1"

    message = _no_real_notifications[0][1]
    assert "nothing was deleted" in message
    assert "expire on their own" in message


def test_an_empty_vault_is_not_an_error_and_still_fails_the_run():
    """The Map may have failed before copying anything at all. There is nothing to roll back and
    the archive still did not happen."""
    fake = _install({})

    with pytest.raises(TerminalError) as err:
        m.handler(_event(copied=0, failed=8), None)

    assert err.value.reason == "archive_incomplete"
    assert fake.deletes == []


def test_the_actor_is_notified_once_by_the_decorator(_no_real_notifications):
    """The machine's own NotifyFailure then suppresses the duplicate on the TerminalError name,
    which is why this verb raises a terminal error rather than a bare exception."""
    _install({f"{_ARCHIVE_ROOT}a.csv": 1})

    with pytest.raises(TerminalError):
        m.handler(_event(), None)

    assert [user for user, _ in _no_real_notifications] == ["alice"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
