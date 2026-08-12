"""The receipt: the one artifact of an archive the user can actually read.

Two things are worth testing about a text file. The FIELDS, because SPEC-171 rewrites this
document rather than appending to it — so a field that only appeared after a restore would make
the format conditional on its own history. And the SIZE RENDERING, because the same number is
shown by the file browser and the two must not disagree (SPEC-155 FR-007).

Runnable under pytest or directly: python3 test_receipt_arcommon.py.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from arcommon import receipt
from cpcommon import clients
from cpcommon.errors import TransientError


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, error=None):
        self.puts = []
        self._error = error

    def put_object(self, Bucket, Key, Body, ContentType):
        if self._error:
            raise self._error
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})
        return {}


def _install(error=None):
    fake = _FakeS3(error)
    clients._s3 = fake
    return fake


_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"


def _record(**overrides):
    record = {
        "requestId": _REQUEST_ID,
        "startedAt": "2026-08-10T14:02:11.123Z",
        "source": {"bucket": "dat-prod-user-space", "root": "alice/"},
        "archive": {"bucket": "dat-prod-archive", "root": f"personal/alice/archive/{_REQUEST_ID}/"},
        "objectCount": 1204,
        "totalBytes": 8_412_339_201,
    }
    record.update(overrides)
    return record


def _labels(text: str) -> list:
    return [line.split(":", 1)[0] for line in text.strip().splitlines()]


# ── FR-006 AC4/AC5: the eight lines, and the two that look premature ─────────


def test_the_receipt_carries_one_labelled_line_for_each_specified_field():
    text = receipt.render(_record())

    assert _labels(text) == [
        "Requested",
        "Request ID",
        "Original path",
        "Archived path",
        "Total size",
        "Files archived",
        "Restore requested",
        "Restored to",
    ]


def test_the_two_restore_fields_are_present_from_the_first_write():
    """FR-006 AC5. SPEC-171 rewrites the whole file; a field that only appeared after a restore
    would make the format conditional on the document's own history, so every reader would have
    to handle two shapes of one document."""
    text = receipt.render(_record())

    assert "Restore requested:" in text
    assert "No" in text.split("Restore requested:")[1].splitlines()[0]
    assert text.strip().endswith(receipt._ABSENT)


def test_the_size_is_both_human_readable_and_exact():
    """The rounded number is what a person reads; the exact one is the only version anybody can
    reconcile against a bill."""
    text = receipt.render(_record())

    assert "7.8 GB (8412339201 bytes)" in text


def test_the_paths_are_the_space_root_and_the_archive_root():
    """A DELIBERATE reading of FR-006, whose sample shows a selected folder. Every archived
    object keeps its path relative to the SPACE root, so naming the selected folder would pair it
    with an archive prefix that does not correspond to it — and a selection of 200 items has no
    single original path at all. Rooted this way the two lines are exact inverses for every
    object, for every selection."""
    text = receipt.render(_record())

    assert "s3://dat-prod-user-space/alice/" in text
    assert f"s3://dat-prod-archive/personal/alice/archive/{_REQUEST_ID}/" in text


def test_the_time_comes_from_the_execution_and_renders_as_utc():
    """From the CONTEXT OBJECT rather than a clock read in the verb: the record is written before
    the deletion and this file after it, so two now() calls would disagree by however long the
    deletion took, and a re-run would disagree with itself."""
    assert "2026-08-10 14:02:11 UTC" in receipt.render(_record())


@pytest.mark.parametrize("started", [None, "", "not-a-time", 7])
def test_an_unparseable_time_renders_a_placeholder_rather_than_failing(started):
    """By the time this runs the data is archived and the source is gone. A raise over a
    timestamp would turn a completed archive into a failed run."""
    text = receipt.render(_record(startedAt=started))

    assert "Requested:" in text
    assert receipt._ABSENT in text.splitlines()[0]


def test_a_missing_count_renders_zero_rather_than_raising():
    text = receipt.render({"totalBytes": 0})

    assert "Files archived:" in text
    assert "0 B (0 bytes)" in text


# ── The size ladder, shared with the browser (SPEC-155 FR-007) ───────────────


@pytest.mark.parametrize(
    "size,expected",
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024**2, "1.0 MB"),
        (1024**3, "1.0 GB"),
        (1024**4, "1.0 TB"),
        (3 * 1024**4, "3.0 TB"),
        (3072 * 1024**3, "3.0 TB"),
    ],
)
def test_the_size_ladder_matches_the_file_browsers(size, expected):
    """`formatSize`'s rule, mirrored: binary units, one decimal above bytes, and a TB CEILING —
    3 TB must not read as `3072.0 GB` here and `3.0 TB` on the other screen, which is the
    disagreement SPEC-155 FR-007 closed between the two browser formatters."""
    assert receipt.human_bytes(size) == expected


def test_the_ceiling_keeps_growing_in_tb_rather_than_inventing_a_unit():
    assert receipt.human_bytes(2048 * 1024**4).endswith(" TB")


# ── The write ────────────────────────────────────────────────────────────────


def test_the_receipt_is_written_as_plain_utf8_text_at_the_specified_key():
    """Deliberately not rendered in the browser — the project has no in-browser preview and this
    does not introduce one. The user downloads it and reads it."""
    fake = _install()

    key = receipt.write("user-bkt", "alice", _REQUEST_ID, _record())

    assert key == f"alice/archive/{_REQUEST_ID}/receipt.txt"
    assert fake.puts[0]["ContentType"] == "text/plain; charset=utf-8"
    assert fake.puts[0]["Body"].decode("utf-8").startswith("Requested:")


def test_a_retryable_write_fault_stays_transient():
    """The state's Retry re-runs the verb, which is safe because the key is a pure function of
    the request and the write is a whole-object PUT."""
    _install(error=_S3Error("SlowDown"))

    with pytest.raises(TransientError):
        receipt.write("user-bkt", "alice", _REQUEST_ID, _record())


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
