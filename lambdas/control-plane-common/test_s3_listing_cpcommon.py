"""Tests for cpcommon.s3_listing (SPEC-107 FR-003).

Pins the segment-level hidden-path rule, the user_settings/ exclusion, and the
absolute-by-default / relative-opt-in yield semantics that the two prior copies
disagreed on. ``object_size`` is here too: file-send and archive had it verbatim between
them, and the transient/terminal split is the half worth asserting once.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from cpcommon import clients, messages, s3_listing
from cpcommon.errors import TerminalError, TransientError

#: Reason codes the tests pass in as a caller would. Registered so TerminalError accepts them
#: without importing a domain layer — cpcommon owns the algorithm, not the wording.
#: `archive_source_missing` is deliberately NOT a production code: the point of the test that
#: uses it is that the reason travels from the caller, so it has to be one no plane registers.
messages.register(
    {
        "source_missing": "a selected file could not be read.",
        "archive_source_missing": "somebody else's sentence for the same fault.",
    },
    prefix="Test: ",
)


class _FakeS3:
    def __init__(self, objects):
        self._objects = objects  # list of (key, size)

    def get_paginator(self, _op):
        objects = self._objects

        class _Pager:
            def paginate(self, **_kwargs):
                yield {"Contents": [{"Key": k, "Size": s} for k, s in objects]}

        return _Pager()


def _install(objects):
    clients._s3 = _FakeS3(objects)


def test_hidden_segment_anywhere_in_path_is_excluded():
    # The pipeline's own reports live under a `_`-prefixed DIRECTORY, not a hidden
    # basename — tbcommon's basename-only rule missed this (FR-003).
    assert s3_listing.is_ignored("alice/_data-quality-reports/abc/report.json", 100, "alice/") is True


def test_ordinary_data_file_is_not_excluded():
    assert s3_listing.is_ignored("alice/data/part-0.csv", 100, "alice/") is False


def test_user_settings_subtree_is_excluded():
    # No leading underscore, so the segment rule alone would not catch it (FR-003).
    assert s3_listing.is_ignored("alice/user_settings/notifications.json", 100, "alice/") is True


def test_athenaresults_marker_and_zero_byte_are_excluded():
    assert s3_listing.is_ignored("alice/athenaresults/x.csv", 100, "alice/") is True
    assert s3_listing.is_ignored("alice/DO_NOT_DELETE.txt", 100, "alice/") is True
    assert s3_listing.is_ignored("alice/data/part-0.csv", 0, "alice/") is True  # zero-byte placeholder


def test_list_yields_absolute_keys_by_default():
    _install([
        ("alice/data/part-0.csv", 10),
        ("alice/_data-quality-reports/r/report.json", 20),  # excluded
        ("alice/user_settings/x.json", 30),  # excluded
        ("alice/data/part-1.csv", 40),
    ])
    got = list(s3_listing.list_data_objects("bkt", "alice/"))
    assert got == [("alice/data/part-0.csv", 10), ("alice/data/part-1.csv", 40)]


def test_list_yields_relative_keys_when_opted_in():
    _install([("alice/data/part-0.csv", 10), ("alice/data/part-1.csv", 40)])
    got = list(s3_listing.list_data_objects("bkt", "alice/", relative=True))
    assert got == [("data/part-0.csv", 10), ("data/part-1.csv", 40)]


# ── SPEC-165: the ignore rule is a parameter, the pagination is not ──────────


def test_a_caller_can_supply_its_own_ignore_rule():
    """WHY THIS SEAM EXISTS. Every rule in `is_ignored` is anchored at the LISTING PREFIX, which
    is right for a plane listing a table's own folder and wrong for file-send, whose prefix is
    whichever item the user picked. Forking the paginator to get a different rule would have
    duplicated the one part that genuinely is shared."""
    _install([
        ("alice/data/part-0.csv", 10),
        ("alice/data/DO_NOT_DELETE.txt", 20),
        ("alice/data/_drafts/notes.md", 30),
    ])

    got = list(
        s3_listing.list_data_objects(
            "bkt", "alice/", ignore=lambda key, size, prefix: key.endswith(".txt")
        )
    )

    assert got == [("alice/data/part-0.csv", 10), ("alice/data/_drafts/notes.md", 30)]


def test_the_default_rule_is_unchanged_for_every_existing_caller():
    """The other direction, and the one that would be a silent regression across three planes:
    table-builder, table-share and data-quality all call this with no predicate and must keep
    getting exactly the rule they had."""
    _install([("alice/data/part-0.csv", 10), ("alice/data/_hidden/x.csv", 20)])

    assert list(s3_listing.list_data_objects("bkt", "alice/")) == [("alice/data/part-0.csv", 10)]


def test_a_custom_rule_still_gets_the_shared_pagination():
    """The pagination IS the shared part. A caller passing its own predicate must not quietly
    opt out of paging past 1,000 keys — which is the boundary a fixture proves least."""
    pages = [
        [{"Key": f"alice/{i:05d}.csv", "Size": 1} for i in range(1000)],
        [{"Key": f"alice/{i:05d}.csv", "Size": 1} for i in range(1000, 1500)],
    ]

    class _P:
        def paginate(self, Bucket, Prefix):
            for page in pages:
                yield {"Contents": page}

    class _S3:
        def get_paginator(self, name):
            return _P()

    clients._s3 = _S3()

    got = list(s3_listing.list_data_objects("bkt", "alice/", ignore=lambda k, s, p: False))

    assert len(got) == 1500


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── object_size — the per-file HeadObject a copy plan costs ──────────────────


class _HeadS3:
    """An S3 whose HeadObject answers from a dict, or raises a code."""

    def __init__(self, sizes=None, error=None):
        self._sizes = sizes or {}
        self._error = error
        self.calls = []

    def head_object(self, Bucket, Key):
        self.calls.append((Bucket, Key))
        if self._error:
            raise self._error
        if Key not in self._sizes:
            raise _S3Error("404")
        return {"ContentLength": self._sizes[Key]}


class _S3Error(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


def test_the_size_comes_back_as_an_int():
    clients._s3 = _HeadS3({"alice/notes.txt": 512})

    assert s3_listing.object_size("user-bkt", "alice/notes.txt", missing_reason="source_missing") == 512


def test_a_missing_object_is_terminal_and_names_the_key():
    """The user picked it from their own browser moments ago, so the request no longer describes
    reality — and the message has to say WHICH file for that to be actionable."""
    clients._s3 = _HeadS3({"alice/other.txt": 1})

    with pytest.raises(TerminalError) as caught:
        s3_listing.object_size("user-bkt", "alice/gone.txt", missing_reason="source_missing")

    assert caught.value.reason == "source_missing"
    assert "alice/gone.txt" in caught.value.detail


def test_a_throttle_is_transient_rather_than_a_missing_file():
    """The direction that matters: classifying a throttle as a missing file tells the user their
    file is permanently gone over a fault a Retry fixes."""
    clients._s3 = _HeadS3(error=_S3Error("SlowDown"))

    with pytest.raises(TransientError):
        s3_listing.object_size("user-bkt", "alice/notes.txt", missing_reason="source_missing")


def test_the_reason_code_is_the_callers_and_never_this_layers():
    """cpcommon owns the algorithm, the domain layer owns the wording — which is why the reason
    is a required keyword here rather than a default this layer picked."""
    clients._s3 = _HeadS3({})

    with pytest.raises(TerminalError) as caught:
        s3_listing.object_size("user-bkt", "alice/gone.txt", missing_reason="archive_source_missing")

    assert caught.value.reason == "archive_source_missing"
