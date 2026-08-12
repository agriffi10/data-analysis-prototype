"""The restore lookup: rebuilding destinations from the keys, and tolerating a lost record.

The load-bearing claim in this file is the second section. SPEC-169 wrote ``_manifest.json`` as
a REPORT rather than a record, and the whole arc's design rests on a restore working without it
— so the tolerance is tested three ways (absent, unreadable, malformed) rather than asserted in
a docstring, and only a record that DISAGREES refuses.

Runnable under pytest or directly: python3 test_restore_arcommon.py.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from arcommon import restore
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError

ARCHIVE_ID = "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c"
ROOT = f"personal/alice/archive/{ARCHIVE_ID}/"


class _S3Error(Exception):
    def __init__(self, code, status=400):
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        super().__init__(code)


class _FakeS3:
    """Pages a listing and answers one GetObject, so pagination is genuinely exercised."""

    def __init__(self, pages=(), manifest=None, get_error=None, list_error=None):
        self._pages = list(pages)
        self._manifest = manifest
        self._get_error = get_error
        self._list_error = list_error
        self.gets = []

    def get_paginator(self, name):
        outer = self

        class _P:
            def paginate(self, Bucket, Prefix):
                if outer._list_error:
                    raise outer._list_error
                for page in outer._pages:
                    yield {"Contents": [{"Key": k, "Size": s} for k, s in page]}

        return _P()

    def get_object(self, Bucket, Key):
        self.gets.append(Key)
        if self._get_error:
            raise self._get_error
        if self._manifest is None:
            raise _S3Error("NoSuchKey", 404)
        return {"Body": _Body(self._manifest)}


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload if isinstance(self._payload, bytes) else json.dumps(self._payload).encode()


def _install(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


# ── The destinations come from the keys, not from the record ─────────────────


def test_every_destination_is_rebuilt_from_the_archived_key_alone():
    """The archived key encodes its own origin, so one listing yields both the objects and
    where they go — which is what makes a lost record unable to make a restore WRONG."""
    _install(pages=[[(f"{ROOT}reports/2026/q1.csv", 90_112), (f"{ROOT}notes.txt", 12)]])

    objects, total = restore.derive_destinations("archive-bkt", ROOT, "alice/")

    assert [o["destKey"] for o in objects] == ["alice/reports/2026/q1.csv", "alice/notes.txt"]
    assert [o["bytes"] for o in objects] == [90_112, 12]
    assert total == 90_124


def test_the_listing_pages_and_nothing_is_lost_at_the_boundary():
    """S3 returns at most 1,000 keys per page. Treating one page as the whole archive would
    restore a prefix of it and report success."""
    pages = [[(f"{ROOT}a/{i}.csv", 1) for i in range(3)], [(f"{ROOT}b/{i}.csv", 2) for i in range(2)]]
    _install(pages=pages)

    objects, total = restore.derive_destinations("archive-bkt", ROOT, "alice/")

    assert len(objects) == 5
    assert total == 7


def test_the_record_is_never_given_a_destination():
    """A restored `_manifest.json` would land in the user's space as a stray file they did not
    put there and cannot explain."""
    _install(pages=[[(f"{ROOT}_manifest.json", 240), (f"{ROOT}q1.csv", 10)]])

    objects, _ = restore.derive_destinations("archive-bkt", ROOT, "alice/")

    assert [o["destKey"] for o in objects] == ["alice/q1.csv"]


def test_a_users_own_file_of_the_same_name_deeper_down_still_comes_back():
    """THE EXCLUSION IS BY EXACT KEY AT THE ARCHIVE ROOT, NEVER BY BASENAME. A user's own
    `reports/_manifest.json` was archived like any other file, and a basename rule would drop it
    silently — the same class of mistake SPEC-165 records, where an exclusion anchored in the
    wrong place dropped a user's own folder out of a send that reported success."""
    _install(pages=[[(f"{ROOT}reports/_manifest.json", 55), (f"{ROOT}_manifest.json", 240)]])

    objects, _ = restore.derive_destinations("archive-bkt", ROOT, "alice/")

    assert [o["destKey"] for o in objects] == ["alice/reports/_manifest.json"]


def test_an_empty_folder_placeholder_comes_back_too():
    """SPEC-169's archive predicate deliberately KEEPS what every other plane's listing drops —
    zero-byte placeholders, hidden segments — so an archived empty folder is restorable. A
    restore filtering them out would return less than was taken."""
    _install(pages=[[(f"{ROOT}empty/", 0), (f"{ROOT}_drafts/x.txt", 3)]])

    objects, _ = restore.derive_destinations("archive-bkt", ROOT, "alice/")

    assert [o["destKey"] for o in objects] == ["alice/empty/", "alice/_drafts/x.txt"]


def test_a_key_that_does_not_sit_under_the_prefix_is_refused_not_re_rooted():
    _install(pages=[[("personal/bob/archive/x/q1.csv", 10)]])

    with pytest.raises(TerminalError) as caught:
        restore.derive_destinations("archive-bkt", ROOT, "alice/")

    assert caught.value.reason == "forbidden"


def test_a_retryable_listing_fault_stays_transient():
    _install(list_error=_S3Error("SlowDown", 503))

    with pytest.raises(TransientError):
        restore.derive_destinations("archive-bkt", ROOT, "alice/")


def test_an_empty_archive_is_not_found_and_says_nothing_about_why():
    """The space comes from the REQUEST, so an id belonging to another space resolves to an
    empty prefix here — which must read identically to an id that was never used. Anything else
    is an existence oracle over other people's archives."""
    with pytest.raises(TerminalError) as caught:
        restore.assert_found([], ARCHIVE_ID, "alice")

    assert caught.value.reason == "archive_not_found"
    assert "belongs" not in str(caught.value).lower()


# ── The record is a cross-check and NEVER a dependency ───────────────────────


def test_an_absent_record_lets_the_restore_proceed():
    """FR-003 AC5, and the property SPEC-169 shaped its manifest around. A restore that refused
    for want of a convenience record would be exactly the failure mode the self-describing key
    layout exists to prevent."""
    _install(manifest=None)

    assert restore.read_recorded_count("archive-bkt", ROOT) is None
    restore.assert_complete(3, None, ARCHIVE_ID)


def test_an_unreadable_record_lets_the_restore_proceed():
    """Same reasoning: the cross-check can only ADD confidence, so its own fault must not
    subtract any."""
    _install(get_error=_S3Error("AccessDenied", 403))

    assert restore.read_recorded_count("archive-bkt", ROOT) is None


@pytest.mark.parametrize("payload", [b"{not json", {"objectCount": "three"}, {}, {"objectCount": True}])
def test_a_malformed_record_lets_the_restore_proceed(payload):
    _install(manifest=payload)

    assert restore.read_recorded_count("archive-bkt", ROOT) is None


def test_a_throttled_record_read_is_retried_rather_than_read_as_absent():
    """The one place the tolerance could cost something: silently skipping the integrity check
    because S3 was busy."""
    _install(get_error=_S3Error("SlowDown", 503))

    with pytest.raises(TransientError):
        restore.read_recorded_count("archive-bkt", ROOT)


def test_a_record_that_agrees_with_the_listing_passes():
    restore.assert_complete(1204, 1204, ARCHIVE_ID)


def test_a_record_that_disagrees_refuses_and_names_both_numbers():
    """It can only fire when something is already wrong, which is the point of an integrity
    check rather than an argument against having one."""
    with pytest.raises(TerminalError) as caught:
        restore.assert_complete(1200, 1204, ARCHIVE_ID)

    assert caught.value.reason == "restore_archive_incomplete"
    assert caught.value.tokens == {"expected": "1204", "found": "1200"}


def test_the_disagreement_does_not_reuse_the_copy_shortfalls_reason_code():
    """`archive_incomplete` was registered by SPEC-169 for a copy that fell short, and its body
    promises "nothing was deleted and your files are exactly where they were" — a sentence that
    is meaningless about a restore. One code cannot carry both."""
    with pytest.raises(TerminalError) as caught:
        restore.assert_complete(1, 2, ARCHIVE_ID)

    assert caught.value.reason != "archive_incomplete"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
