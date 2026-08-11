"""Tests for cpcommon.s3_listing (SPEC-107 FR-003).

Pins the segment-level hidden-path rule, the user_settings/ exclusion, and the
absolute-by-default / relative-opt-in yield semantics that the two prior copies
disagreed on.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon import clients, s3_listing


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
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
