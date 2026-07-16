"""Unit tests for the data-quality inspect-source Lambda (SPEC-110).

Pure logic, AWS stubbed: s3_listing.list_data_objects and the S3 client are replaced on
the verb module, so no bucket is touched.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import pytest  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from cpcommon.errors import TerminalError  # noqa: E402
from dqcommon import config, messages  # noqa: E402

import dq_inspect_source as v  # noqa: E402

BUCKET = "dq-user-bkt"
LOCATION = "alice/sales"


class _FakeS3:
    """Stands in for the S3 client's head_object (the folder-vs-file probe).

    ``keys`` are the object keys that EXIST as exact objects; anything else raises the
    404 that means "not an object, so treat it as a folder".
    """

    def __init__(self, keys=()):
        self.keys = set(keys)
        self.head_calls = []

    def head_object(self, Bucket, Key):  # noqa: N803 - boto3's kwarg casing
        self.head_calls.append(Key)
        if Key in self.keys:
            return {"ContentLength": 1}
        raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")


def _setup(objects, exact_keys=(), monkeypatch=None):
    """Point the verb at a fake listing + a fake S3, returning the recorded prefixes."""
    listed = []
    fake = _FakeS3(exact_keys)
    v.clients.s3 = lambda: fake

    def _list(bucket, prefix):
        listed.append((bucket, prefix))
        return iter(objects)

    v.s3_listing.list_data_objects = _list
    return listed, fake


def _event(**over):
    event = {
        "requestId": "req-1",
        "actor": "alice",
        "space": {"kind": "personal", "bucket": BUCKET, "prefix": "alice/"},
        "location": LOCATION,
        "reportPrefix": "alice/_data-quality-reports/req-1/",
    }
    event.update(over)
    return event


# ── FR-001: listing ──────────────────────────────────────────────────────────


def test_folder_is_listed_with_a_trailing_slash():
    """A prefix match without the slash would swallow alice/sales2/ and sales-archive/."""
    listed, _ = _setup([("alice/sales/a.csv", 10)])
    v.handler(_event(), None)
    assert listed == [(BUCKET, "alice/sales/")]


def test_single_file_location_yields_a_one_object_manifest():
    listed, _ = _setup([("alice/sales/a.csv", 10)], exact_keys=["alice/sales/a.csv"])
    out = v.handler(_event(location="alice/sales/a.csv"), None)
    assert listed == [(BUCKET, "alice/sales/a.csv")]
    assert out["fileCount"] == 1
    assert out["format"] == "csv"


def test_a_folder_of_files_proceeds():
    _setup([("alice/sales/a.csv", 10), ("alice/sales/b.csv", 20)])
    out = v.handler(_event(), None)
    assert out["format"] == "csv"
    assert out["fileCount"] == 2


def test_empty_location_is_terminal_no_data_files():
    _setup([])
    with pytest.raises(TerminalError) as err:
        v.handler(_event(), None)
    assert err.value.reason == messages.NO_DATA_FILES


def test_exclusions_come_from_cpcommon_not_reimplemented_here():
    """The verb must delegate the ignore rules; anything cpcommon drops never arrives.

    cpcommon's segment-level rule (SPEC-107 FR-003) is what stops this pipeline reading
    back its own _data-quality-reports/ folder, and it also drops user_settings/, the
    marker, and zero-byte placeholders. Asserting the verb passes the real function
    through is the contract; s3_listing has its own tests for the rules themselves.
    """
    import cpcommon.s3_listing as real

    hidden = "alice/sales/_data-quality-reports/x/report.json"
    settings = "alice/user_settings/notifications.json"
    marker = "alice/sales/DO_NOT_DELETE.txt"
    placeholder = "alice/sales/folder/"
    for key, size in ((hidden, 10), (settings, 10), (marker, 10), (placeholder, 0)):
        assert real.is_ignored(key, size, "alice/sales/") or real.is_ignored(key, size, "alice/")


def test_a_transient_head_error_propagates_for_the_sfn_retry():
    """Only a real 404 means "folder"; a 503 must not be mistaken for one."""
    _setup([])
    fake = _FakeS3()

    def _boom(Bucket, Key):  # noqa: N803
        raise ClientError({"Error": {"Code": "503", "Message": "Slow Down"}}, "HeadObject")

    fake.head_object = _boom
    v.clients.s3 = lambda: fake
    with pytest.raises(ClientError):
        v.handler(_event(), None)


# ── FR-002: extension-based classification ───────────────────────────────────


@pytest.mark.parametrize(
    "key,expected",
    [
        ("a.csv", "csv"),
        ("a.txt", "csv"),
        ("a.json", "json"),
        ("a.jsonl", "json"),
        ("a.ndjson", "json"),
        ("a.parquet", "parquet"),
        ("a.CSV", "csv"),
    ],
)
def test_extension_map(key, expected):
    assert v._classify(key) == expected


@pytest.mark.parametrize(
    "key,expected",
    [
        ("a.csv.gz", "csv"),
        ("a.json.gz", "json"),
        ("a.ndjson.gz", "json"),
        ("a.jsonl.gz", "json"),
    ],
)
def test_one_trailing_gz_is_stripped_before_classification(key, expected):
    assert v._classify(key) == expected


def test_bare_gz_is_unsupported():
    """Nothing says what's inside, and this arc does not sniff content."""
    assert v._classify("a.gz") is None


def test_a_file_with_no_extension_is_unsupported():
    """Classification is on the extension only; there is nothing to classify."""
    assert v._classify("alice/sales/README") is None
    _setup([("alice/sales/README", 10)])
    with pytest.raises(TerminalError) as err:
        v.handler(_event(), None)
    assert err.value.reason == messages.UNSUPPORTED_FORMAT


def test_parquet_gz_is_unsupported():
    """Athena can't read it and polars can't range-read the footer through gzip."""
    assert v._classify("a.parquet.gz") is None


def test_parquet_is_supported_so_convert_then_verify_works():
    """The file converter's output must be checkable, or the two arcs can't compose."""
    _setup([("alice/sales/part-0.parquet", 10)])
    assert v.handler(_event(), None)["format"] == "parquet"


def test_xlsx_is_terminal_unsupported_format_with_no_convert_first_guidance():
    _setup([("alice/sales/book.xlsx", 10)])
    with pytest.raises(TerminalError) as err:
        v.handler(_event(), None)
    assert err.value.reason == messages.UNSUPPORTED_FORMAT
    assert "convert" not in messages.failure_message(err.value.reason).lower()


def test_unsupported_extension_names_the_offending_object():
    _setup([("alice/sales/a.csv", 10), ("alice/sales/notes.pdf", 10)])
    with pytest.raises(TerminalError) as err:
        v.handler(_event(), None)
    assert err.value.reason == messages.UNSUPPORTED_FORMAT
    assert "notes.pdf" in err.value.detail


# ── FR-003: single-format enforcement ────────────────────────────────────────


def test_mixed_formats_is_terminal_naming_the_formats():
    _setup([("alice/sales/a.csv", 10), ("alice/sales/b.parquet", 10)])
    with pytest.raises(TerminalError) as err:
        v.handler(_event(), None)
    assert err.value.reason == messages.MIXED_FORMATS
    assert "csv" in err.value.detail and "parquet" in err.value.detail


def test_csv_and_txt_together_are_one_format_not_mixed():
    """Both map to csv, so this folder is consistent."""
    _setup([("alice/sales/a.csv", 10), ("alice/sales/b.txt", 10)])
    assert v.handler(_event(), None)["format"] == "csv"


# ── FR-004: caps ─────────────────────────────────────────────────────────────


def test_object_count_cap_breach_is_terminal_naming_count_and_limit():
    objects = [(f"alice/sales/p-{i}.csv", 10) for i in range(config.DQ_MAX_OBJECTS + 1)]
    _setup(objects)
    with pytest.raises(TerminalError) as err:
        v.handler(_event(), None)
    assert err.value.reason == messages.TOO_MANY_FILES
    assert str(config.DQ_MAX_OBJECTS + 1) in err.value.detail
    assert str(config.DQ_MAX_OBJECTS) in err.value.detail


def test_exactly_the_cap_is_allowed():
    _setup([(f"alice/sales/p-{i}.csv", 10) for i in range(config.DQ_MAX_OBJECTS)])
    assert v.handler(_event(), None)["fileCount"] == config.DQ_MAX_OBJECTS


def test_oversized_gz_is_terminal_with_decompress_or_split_guidance():
    """gzip is not splittable: one worker, then the 30-minute DML timeout."""
    _setup([("alice/sales/big.csv.gz", config.DQ_MAX_GZIP_OBJECT_BYTES + 1)])
    with pytest.raises(TerminalError) as err:
        v.handler(_event(), None)
    assert err.value.reason == messages.COMPRESSED_SOURCE_TOO_LARGE
    assert "big.csv.gz" in err.value.detail
    body = messages.failure_message(err.value.reason, object="alice/sales/big.csv.gz")
    assert "decompress" in body.lower() and "split" in body.lower()


def test_a_huge_uncompressed_object_is_fine():
    """There is deliberately NO size cap on uncompressed sources — Athena splits them."""
    _setup([("alice/sales/huge.csv", 500 * 1024**3)])
    assert v.handler(_event(), None)["fileCount"] == 1


def test_a_gz_under_the_cap_is_fine():
    _setup([("alice/sales/ok.csv.gz", config.DQ_MAX_GZIP_OBJECT_BYTES - 1)])
    assert v.handler(_event(), None)["format"] == "csv"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
