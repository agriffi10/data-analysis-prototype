"""Unit tests for the data-quality inspect-source Lambda (SPEC-110).

Pure logic, AWS stubbed: s3_listing.list_data_objects and the S3 client are replaced on
the verb module, so no bucket is touched.
"""

import json
import os
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import pytest  # noqa: E402
from cpcommon.errors import TerminalError, TransientError  # noqa: E402
from dqcommon import config, messages  # noqa: E402

import dq_inspect_source as v  # noqa: E402

BUCKET = "dq-user-bkt"
LOCATION = "alice/sales"


class _FakeClientError(Exception):
    """Mimics botocore.exceptions.ClientError enough for cpcommon.errors.error_code.

    botocore ships in the Lambda RUNTIME but is NOT a test dependency of this repo, so
    the suites fake it rather than import it (see table-builder-execute-ddl's
    _FakeClientError and shared-space-common's fakes.FakeClientError). Importing the real
    one passes locally, where botocore is usually present transitively, and fails in CI.
    """

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class _FakeS3:
    """Stands in for the S3 client's head_object (the folder-vs-file probe).

    ``keys`` are the object keys that EXIST as exact objects; anything else raises the
    404 that means "not an object, so treat it as a folder".
    """

    def __init__(self, keys=()):
        self.keys = set(keys)
        self.head_calls = []
        self.puts = []

    def head_object(self, Bucket, Key):  # noqa: N803 - boto3's kwarg casing
        self.head_calls.append(Key)
        if Key in self.keys:
            return {"ContentLength": 1}
        raise _FakeClientError("404")

    def put_object(self, Bucket, Key, Body, **kw):  # noqa: N803
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, **kw})
        return {}


@pytest.fixture(autouse=True)
def _restore_verb_module():
    """Snapshot/restore the verb module's namespace around every test.

    conftest.py does this for the cpcommon modules, but not for the verb — and _setup
    below stubs the verb's own _probe_columns. Without this, that stub would leak into
    the probe tests further down and they would silently assert against the stub instead
    of the real polars read.
    """
    saved = dict(vars(v))
    yield
    v.__dict__.clear()
    v.__dict__.update(saved)


_DEFAULT_COLUMNS = [{"name": "id", "type": "string"}]


def _setup(objects, exact_keys=(), columns=None):
    """Point the verb at a fake listing + a fake S3, returning the recorded prefixes.

    The per-file probe is stubbed by default — the tests below that exercise the REAL
    probe call _probe_columns directly rather than going through the handler.
    ``columns`` may be a dict keyed by object key to give files differing column lists.
    """
    listed = []
    fake = _FakeS3(exact_keys)
    v.clients.s3 = lambda: fake

    def _list(bucket, prefix):
        listed.append((bucket, prefix))
        return iter(objects)

    def _probe(bucket, key, fmt):
        if isinstance(columns, dict):
            return columns[key]
        return list(columns or _DEFAULT_COLUMNS)

    v.s3_listing.list_data_objects = _list
    v._probe_columns = _probe
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
    """The verb must delegate the ignore rules — driven through the REAL s3_listing.

    Only the S3 paginator is faked, so cpcommon's rules actually run: the segment-level
    hidden-path rule (SPEC-107 FR-003) is what stops this pipeline reading back its own
    _data-quality-reports/ folder as source data, and it also drops user_settings/, the
    marker and zero-byte placeholders. An earlier version asserted on
    s3_listing.is_ignored directly, which is s3_listing's own test territory and would
    have passed even if this verb had bypassed it entirely.
    """
    page = {
        "Contents": [
            {"Key": "alice/sales/real.csv", "Size": 10},
            {"Key": "alice/sales/_data-quality-reports/req-1/report.json", "Size": 10},
            {"Key": "alice/sales/.hidden/tmp.csv", "Size": 10},
            {"Key": "alice/sales/DO_NOT_DELETE.txt", "Size": 10},
            {"Key": "alice/sales/placeholder/", "Size": 0},
            {"Key": "alice/sales/empty.csv", "Size": 0},
        ]
    }
    fake = _FakeS3()
    fake.get_paginator = lambda op: type("P", (), {"paginate": staticmethod(lambda **kw: [page])})()
    v.clients.s3 = lambda: fake
    v._probe_columns = lambda bucket, key, fmt: list(_DEFAULT_COLUMNS)

    v.handler(_event(), None)

    assert [f["key"] for f in _manifest_of(fake)["files"]] == ["alice/sales/real.csv"]


def test_user_settings_is_excluded_at_a_space_root_scan():
    """A check pointed at the space root must not treat the notification inbox as data."""
    page = {
        "Contents": [
            {"Key": "alice/data.csv", "Size": 10},
            {"Key": "alice/user_settings/notifications.json", "Size": 10},
            {"Key": "alice/athenaresults/q.csv", "Size": 10},
        ]
    }
    fake = _FakeS3()
    fake.get_paginator = lambda op: type("P", (), {"paginate": staticmethod(lambda **kw: [page])})()
    v.clients.s3 = lambda: fake
    v._probe_columns = lambda bucket, key, fmt: list(_DEFAULT_COLUMNS)

    v.handler(_event(location="alice"), None)

    assert [f["key"] for f in _manifest_of(fake)["files"]] == ["alice/data.csv"]


def test_a_zero_byte_object_at_the_location_is_a_folder_not_a_file():
    """S3 has no directories — a folder IS a zero-byte placeholder object (SPEC-016).

    With a placeholder at 'alice/sales', head_object SUCCEEDS, so a size-blind probe would
    read the location as a file and list the slash-less prefix 'alice/sales' — silently
    pulling in 'alice/sales-archive/' and 'alice/sales2/'. The placeholder itself is then
    dropped by s3_listing (size 0), so nothing fails and the user gets a report over files
    they never selected.
    """
    fake = _FakeS3()
    fake.head_object = lambda Bucket, Key: {"ContentLength": 0}  # noqa: N803
    v.clients.s3 = lambda: fake
    listed = []
    v.s3_listing.list_data_objects = lambda bucket, prefix: (
        listed.append((bucket, prefix)) or iter([("alice/sales/a.csv", 10)])
    )
    v._probe_columns = lambda bucket, key, fmt: list(_DEFAULT_COLUMNS)

    v.handler(_event(), None)

    assert listed == [(BUCKET, "alice/sales/")], "a zero-byte hit must not become a file"


def test_a_real_file_at_the_location_is_still_a_file():
    listed, _ = _setup([("alice/sales/a.csv", 10)], exact_keys=["alice/sales/a.csv"])
    v.handler(_event(location="alice/sales/a.csv"), None)
    assert listed == [(BUCKET, "alice/sales/a.csv")]


def test_a_transient_head_error_is_retryable_not_a_folder():
    """Only a real 404 means "folder"; a 503 must not be mistaken for one — and must reach
    the SFN as a TransientError, the ONLY name in InspectSource's Retry list our own code
    can raise. A bare ClientError matches nothing there and would be recorded as a
    permanent failure carrying raw AWS text."""
    _setup([])
    fake = _FakeS3()

    def _boom(Bucket, Key):  # noqa: N803
        raise _FakeClientError("SlowDown")

    fake.head_object = _boom
    v.clients.s3 = lambda: fake
    with pytest.raises(TransientError):
        v.handler(_event(), None)


def test_a_non_transient_head_error_is_not_disguised_as_retryable():
    """AccessDenied is deterministic — retrying it just burns the SFN's attempts."""
    _setup([])
    fake = _FakeS3()

    def _boom(Bucket, Key):  # noqa: N803
        raise _FakeClientError("AccessDenied")

    fake.head_object = _boom
    v.clients.s3 = lambda: fake
    with pytest.raises(_FakeClientError):
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


# ── FR-005: the per-file header probe ────────────────────────────────────────
#
# These drive REAL polars against real files (local paths for the s3:// path, a real
# gzip stream for the compressed path). Mocking the probe would assert nothing about the
# thing SPEC-111's DDL depends on.


def _write(tmp_path, name, content, binary=False):
    p = tmp_path / name
    p.write_bytes(content) if binary else p.write_text(content)
    return str(p)


def _probe_local(monkeypatch, path, fmt):
    """Run the probe against a local file.

    Mirrors the two read paths the verb uses (SPEC-111): CSV/JSON are read via
    ``_read_plain_head`` (a boto3 buffer — polars' object_store cloud read does not work in
    Lambda) so the stub feeds polars the file's bytes; Parquet still reads via the s3:// URI
    (its schema is a footer at the END of the file, unreachable by a head read), so the stub
    points ``_object_uri`` at the local path.
    """
    monkeypatch.setattr(v, "_check_access", lambda bucket, key: None)
    if fmt == "parquet":
        monkeypatch.setattr(v, "_object_uri", lambda bucket, key: path)
    else:
        with open(path, "rb") as fh:
            data = fh.read()
        monkeypatch.setattr(v, "_read_plain_head", lambda bucket, key: data)
    return v._probe_columns("bkt", "some/key", fmt)


def test_csv_probe_yields_all_string_columns(tmp_path, monkeypatch):
    """CSV is not type-inferred: "string" IS the type (SPEC-111's OpenCSVSerde)."""
    path = _write(tmp_path, "a.csv", "id,amount,note\n1,2.5,hi\n")
    assert _probe_local(monkeypatch, path, "csv") == [
        {"name": "id", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "note", "type": "string"},
    ]


def test_csv_probe_handles_a_quoted_header_containing_a_comma(tmp_path, monkeypatch):
    """A hand-rolled split(",") would invent a column here; polars does not."""
    path = _write(tmp_path, "q.csv", 'id,"last, first"\n1,"Doe, Jane"\n')
    assert [c["name"] for c in _probe_local(monkeypatch, path, "csv")] == ["id", "last, first"]


def test_parquet_probe_yields_the_dtypes_spec_111_needs(tmp_path, monkeypatch):
    """Athena does not auto-detect a Parquet schema, so these types ARE the DDL."""
    import polars as pl

    path = str(tmp_path / "a.parquet")
    pl.DataFrame(
        {"id": pl.Series([1], dtype=pl.Int64), "amt": pl.Series([2.5], dtype=pl.Float64), "ok": [True]}
    ).write_parquet(path)
    assert _probe_local(monkeypatch, path, "parquet") == [
        {"name": "id", "type": "bigint"},
        {"name": "amt", "type": "double"},
        {"name": "ok", "type": "boolean"},
    ]


def test_json_probe_infers_types(tmp_path, monkeypatch):
    path = _write(tmp_path, "a.ndjson", '{"id":1,"name":"a"}\n{"id":2,"name":"b"}\n')
    assert _probe_local(monkeypatch, path, "json") == [
        {"name": "id", "type": "bigint"},
        {"name": "name", "type": "string"},
    ]


def test_the_probe_hands_polars_an_s3_uri_rather_than_a_local_path():
    """Named for what it actually proves. The no-download guarantee on this path is
    polars/object_store's (it range-fetches the footer), which a unit test can't observe —
    only that we never route the read through /tmp. The gz path's bound IS asserted, below."""
    assert v._object_uri("bkt", "alice/sales/a.parquet") == "s3://bkt/alice/sales/a.parquet"


def test_csv_probe_reads_via_boto3_not_object_store(tmp_path, monkeypatch):
    """The SPEC-111 fix: a plain CSV must be read through _read_plain_head (boto3 buffer),
    NOT polars' object_store s3:// scan — which fails in Lambda even with credentials
    ('failed to allocate N bytes to download'). Fail _object_uri so any accidental route
    back to the cloud reader is caught here rather than in production."""
    path = _write(tmp_path, "a.csv", "id,amount\n1,2\n")
    monkeypatch.setattr(v, "_check_access", lambda bucket, key: None)

    def _boom(bucket, key):
        raise AssertionError("CSV must not use the object_store s3:// path")

    monkeypatch.setattr(v, "_object_uri", _boom)
    with open(path, "rb") as fh:
        data = fh.read()
    monkeypatch.setattr(v, "_read_plain_head", lambda bucket, key: data)
    assert [c["name"] for c in v._probe_columns("bkt", "some/a.csv", "csv")] == ["id", "amount"]


def test_storage_options_carries_the_roles_creds_and_region(monkeypatch):
    """polars' object_store needs the creds handed in explicitly (SPEC-111). Assert the
    aws_* keys are built from the Lambda role's env — the token is mandatory."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA_TEST")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret_test")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "token_test")
    opts = v._storage_options()
    assert opts == {
        "aws_region": "us-east-1",
        "aws_access_key_id": "AKIA_TEST",
        "aws_secret_access_key": "secret_test",
        "aws_session_token": "token_test",
    }


def test_read_plain_head_drops_a_partial_trailing_line():
    """A CSV header is line 1; the read trims to whole lines and drops a partial trailing
    line (handing polars a truncated final row would invent a column or fail to parse)."""
    body, _ = _install_body(b"id,amount\n1,2\n3,4\npartial_no_newline")
    out = v._read_plain_head("bkt", "some/a.csv")
    assert out == b"id,amount\n1,2\n3,4\n"  # partial tail dropped
    assert body.closed  # the body stream is abandoned, not drained


def test_read_plain_head_does_not_drain_a_large_object():
    """The guarantee that matters: it abandons the object once the bound is met, so a huge
    CSV is never fully pulled into the Lambda. (Bounding is at chunk granularity, like the
    gzip head — a chunk may carry many lines — so this asserts bytes-not-drained + whole
    lines, not an exact line count.)"""
    rows = b"h\n" + b"row\n" * 262_144  # ~1 MiB, many 256 KiB chunks
    body, counter = _install_body(rows)
    out = v._read_plain_head("bkt", "some/big.csv")
    assert counter["read"] < len(rows)  # stopped early — did not drain the object
    assert out.endswith(b"\n")  # whole lines only
    assert body.closed


def test_check_access_head_objects_the_key():
    _, fake = _setup([], exact_keys=["alice/sales/a.csv"])
    v._check_access("bkt", "alice/sales/a.csv")
    assert fake.head_calls == ["alice/sales/a.csv"]


def test_an_unmappable_dtype_is_a_terminal_not_a_crash(tmp_path, monkeypatch):
    """A dtype with no Hive equivalent has no place in SPEC-111's column list."""
    import polars as pl

    path = str(tmp_path / "b.parquet")
    pl.DataFrame({"blob": pl.Series([b"\x00"], dtype=pl.Binary)}).write_parquet(path)
    monkeypatch.setattr(v, "_check_access", lambda bucket, key: None)
    monkeypatch.setattr(v, "_object_uri", lambda bucket, key: path)
    with pytest.raises(TerminalError) as err:
        v._probe_columns("bkt", "alice/sales/b.parquet", "parquet")
    assert err.value.reason == messages.UNREADABLE_HEADER
    assert "blob" in err.value.detail


def test_an_unknown_format_is_a_terminal():
    """Defensive: _resolve_format only ever emits csv/json/parquet."""
    with pytest.raises(TerminalError) as err:
        v._columns_from("s3://bkt/a.avro", "avro")
    assert err.value.reason == messages.UNREADABLE_HEADER


def test_an_unreadable_header_fails_the_whole_request(tmp_path, monkeypatch):
    """Not a silent skip: a report that omits the file we couldn't parse would hide the
    worst file in the folder."""
    path = _write(tmp_path, "broken.parquet", b"this is not parquet", binary=True)
    monkeypatch.setattr(v, "_check_access", lambda bucket, key: None)
    monkeypatch.setattr(v, "_object_uri", lambda bucket, key: path)
    with pytest.raises(TerminalError) as err:
        v._probe_columns("bkt", "alice/sales/broken.parquet", "parquet")
    assert err.value.reason == messages.UNREADABLE_HEADER
    assert "broken.parquet" in err.value.detail


def test_the_access_probe_runs_before_the_read(tmp_path, monkeypatch):
    """A transient S3 error must surface as a retryable boto error, NOT unreadable_header
    — the user would otherwise be told a permanent-sounding verdict on a blip."""
    calls = []
    monkeypatch.setattr(v, "_object_uri", lambda bucket, key: str(tmp_path / "nope.csv"))

    def _denied(bucket, key):
        calls.append(key)
        raise _FakeClientError("503")

    monkeypatch.setattr(v, "_check_access", _denied)
    with pytest.raises(_FakeClientError):
        v._probe_columns("bkt", "alice/sales/a.csv", "csv")
    assert calls == ["alice/sales/a.csv"]


def test_every_file_is_probed_not_just_a_sample():
    """SPEC-112's cross-file check compares per-file column lists; one sample shows nothing."""
    probed = []
    _, fake = _setup([("alice/sales/a.csv", 10), ("alice/sales/b.csv", 10), ("alice/sales/c.csv", 10)])
    real_probe = v._probe_columns
    v._probe_columns = lambda bucket, key, fmt: probed.append(key) or real_probe(bucket, key, fmt)
    v.handler(_event(), None)
    assert probed == ["alice/sales/a.csv", "alice/sales/b.csv", "alice/sales/c.csv"]
    assert len(_manifest_of(fake)["files"]) == 3


def test_files_disagreeing_on_columns_is_recorded_not_rejected():
    """The input SPEC-112 must report on — inspect-source records it and moves on."""
    _, fake = _setup(
        [("alice/sales/a.csv", 10), ("alice/sales/b.csv", 10)],
        columns={
            "alice/sales/a.csv": [{"name": "id", "type": "string"}, {"name": "note", "type": "string"}],
            "alice/sales/b.csv": [{"name": "id", "type": "string"}],
        },
    )
    v.handler(_event(), None)
    files = _manifest_of(fake)["files"]
    assert [len(f["columns"]) for f in files] == [2, 1]
    assert [f["key"] for f in files] == ["alice/sales/a.csv", "alice/sales/b.csv"]


# ── FR-005: the gzip probe's byte bound ──────────────────────────────────────


# The probe checks its bounds after each chunk, so it can overshoot by at most one chunk.
_CHUNK_SLACK = 256 * 1024


class _CountingBody:
    """A GetObject body that records how many COMPRESSED bytes were actually pulled."""

    def __init__(self, data, counter):
        self._data = data
        self._counter = counter
        self.closed = False

    def iter_chunks(self, size):
        for i in range(0, len(self._data), size):
            chunk = self._data[i : i + size]
            self._counter["read"] += len(chunk)
            yield chunk

    def close(self):
        self.closed = True


def _gzip_source(rows=400_000):
    """A .gz whose decompressed body is far larger than the probe should ever read."""
    import gzip

    raw = "id,amount,note\n" + "".join(f"{i},{i}.5,row-{i}\n" for i in range(rows))
    return gzip.compress(raw.encode()), len(raw)


def _install_body(blob):
    counter = {"read": 0}
    body = _CountingBody(blob, counter)
    v.clients.s3 = lambda: type("S3", (), {"get_object": staticmethod(lambda **kw: {"Body": body})})()
    return body, counter


def _streaming_gzip(blocks, block_bytes, *, newline_free=False, seed=0):
    """Build a gzip stream incrementally, never materialising the raw body.

    Compressing ``blocks * block_bytes`` up front would put hundreds of MB in the test
    process — the very thing under test. compressobj lets each block be fed and dropped.
    ``newline_free`` yields near-incompressible blocks with no newlines, so the LINE stop
    can't fire and the byte bounds are what the probe actually hits.
    """
    import random

    rnd = random.Random(seed)
    compressor = zlib.compressobj(1, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    parts = [compressor.compress(b"id,amount,note\n")]
    for _ in range(blocks):
        block = rnd.randbytes(block_bytes).replace(b"\n", b"x") if newline_free else b"x" * block_bytes
        parts.append(compressor.compress(block))
    parts.append(compressor.flush())
    return b"".join(parts)


def test_gzip_probe_stops_at_the_line_count_on_an_ordinary_file():
    """gzip is not seekable, so "bounded range" is false — the probe streams and ABANDONS."""
    blob, uncompressed_len = _gzip_source()
    body, counter = _install_body(blob)

    head = v._read_gzip_head("bkt", "alice/sales/big.csv.gz")

    assert counter["read"] < len(blob), "the probe drained the whole compressed object"
    assert len(head) < uncompressed_len, "the probe decompressed the whole object"
    assert body.closed, "the stream must be abandoned, not left open"
    assert head.startswith(b"id,amount,note\n")
    assert head.endswith(b"\n"), "a partial trailing line would break the parse"


def test_gzip_probe_stops_at_the_compressed_byte_bound(monkeypatch):
    """FR-005's stated bound, pinned on an object that can ONLY stop via that bound.

    The earlier version of this test used a 2.8 MB fixture with a newline every few bytes,
    so the probe always stopped on the line count and the byte bound was never reached —
    deleting the bound entirely left every test green. This fixture has ONE newline and is
    incompressible, so the line stop cannot fire: if the `consumed >= GZIP_PROBE_MAX_BYTES`
    check is removed, the probe reads the whole object and this fails.
    """
    monkeypatch.setattr(v, "GZIP_PROBE_MAX_BYTES", 512 * 1024)
    blob = _streaming_gzip(4, 1024 * 1024, newline_free=True)
    assert len(blob) > 2 * v.GZIP_PROBE_MAX_BYTES, "fixture must be able to exceed the bound"
    body, counter = _install_body(blob)

    v._read_gzip_head("bkt", "alice/sales/opaque.csv.gz")

    assert counter["read"] <= v.GZIP_PROBE_MAX_BYTES + _CHUNK_SLACK
    assert counter["read"] < len(blob), "the probe drained the whole compressed object"
    assert body.closed


def test_gzip_probe_stops_at_the_decompressed_byte_bound(monkeypatch):
    """A compression bomb must not OOM the function — bounding the COMPRESSED side is not enough.

    deflate reaches ~1032:1, so the 8 MiB compressed bound alone permits ~8 GB in memory
    against a 1024 MB function. An OOM is not a TerminalError: the actor would get no
    notification and no reason at all. Here ~64 MiB of 'x' with a single newline compresses
    to a few KB — far under DQ_MAX_GZIP_OBJECT_BYTES and under the compressed bound, so the
    DECOMPRESSED bound is the only thing that can stop it.

    Asserts on _stream_gzip_head's BUFFER, never on _read_gzip_head's truncated result: the
    truncation drops everything after the last newline, so on this exact fixture the result
    is 15 bytes no matter how many gigabytes the buffer reached. An earlier version of this
    test made that mistake and passed with every bound deleted.
    """
    monkeypatch.setattr(v, "GZIP_PROBE_MAX_DECOMPRESSED_BYTES", 1024 * 1024)
    blob = _streaming_gzip(64, 1024 * 1024)  # ~64 MiB of 'x', one newline, tiny compressed
    assert len(blob) < v.GZIP_PROBE_MAX_BYTES, "fixture must not trip the compressed bound"
    body, _ = _install_body(blob)

    out = v._stream_gzip_head("bkt", "alice/sales/bomb.csv.gz")

    assert len(out) <= v.GZIP_PROBE_MAX_DECOMPRESSED_BYTES, "the probe held an unbounded buffer"
    assert body.closed


def test_one_chunk_cannot_blow_past_the_decompressed_bound(monkeypatch):
    """The per-call max_length is the real guard, not the post-hoc length check.

    ~8 MiB of 'x' compresses to ~8 KB — a SINGLE 256 KiB chunk. Checking len(out) only
    after an unbounded decompress() would already have allocated all of it, so this pins
    that the cap is applied inside the call.
    """
    monkeypatch.setattr(v, "GZIP_PROBE_MAX_DECOMPRESSED_BYTES", 64 * 1024)
    blob = _streaming_gzip(8, 1024 * 1024)
    assert len(blob) < 256 * 1024, "fixture must fit in one chunk for this to prove anything"
    _install_body(blob)

    out = v._stream_gzip_head("bkt", "alice/sales/bomb.csv.gz")

    assert len(out) <= v.GZIP_PROBE_MAX_DECOMPRESSED_BYTES


def test_a_compression_bomb_fails_loudly_rather_than_ooming(monkeypatch):
    """The bound truncates mid-line, so polars gets a header and no complete record —
    the honest outcome is a reason the user can act on, not a killed container."""
    monkeypatch.setattr(v, "GZIP_PROBE_MAX_DECOMPRESSED_BYTES", 64 * 1024)
    monkeypatch.setattr(v, "_check_access", lambda bucket, key: None)
    _install_body(_streaming_gzip(8, 1024 * 1024))
    with pytest.raises(TerminalError) as err:
        v._probe_columns("bkt", "alice/sales/bomb.json.gz", "json")
    assert err.value.reason == messages.UNREADABLE_HEADER


def test_the_shipped_decompressed_bound_fits_the_function_memory():
    """1024 MB (locals.tf). The bound is what keeps the probe's peak allocation nowhere
    near it, so a bump to either number should be a deliberate, paired change."""
    assert v.GZIP_PROBE_MAX_DECOMPRESSED_BYTES <= 64 * 1024**2


def test_gzip_probe_yields_the_same_columns_as_the_plain_file(monkeypatch):
    blob, _ = _gzip_source(rows=5)
    _install_body(blob)
    monkeypatch.setattr(v, "_check_access", lambda bucket, key: None)
    columns = v._probe_columns("bkt", "alice/sales/big.csv.gz", "csv")
    assert [c["name"] for c in columns] == ["id", "amount", "note"]
    assert {c["type"] for c in columns} == {"string"}


def test_a_gzipped_ndjson_probe_infers_types(monkeypatch):
    """The .json.gz path: decompressed head -> BytesIO -> scan_ndjson."""
    import gzip

    raw = b'{"id":1,"name":"a"}\n{"id":2,"name":"b"}\n'
    _install_body(gzip.compress(raw))
    monkeypatch.setattr(v, "_check_access", lambda bucket, key: None)
    assert v._probe_columns("bkt", "alice/sales/a.ndjson.gz", "json") == [
        {"name": "id", "type": "bigint"},
        {"name": "name", "type": "string"},
    ]


def test_a_gz_whose_last_line_is_incomplete_drops_the_partial_record(monkeypatch):
    """A truncated final row would give polars a phantom column or a parse error."""
    import gzip

    _install_body(gzip.compress(b"id,amount\n1,2\n3,4"))  # no trailing newline
    monkeypatch.setattr(v, "_check_access", lambda bucket, key: None)
    assert v._read_gzip_head("bkt", "alice/sales/a.csv.gz") == b"id,amount\n1,2\n"


def test_a_gz_object_that_is_not_actually_gzip_is_a_terminal(monkeypatch):
    """The extension is a claim, not a guarantee — this arc never sniffs content."""
    _install_body(b"id,amount\n1,2\n")  # plain bytes behind a .gz name
    monkeypatch.setattr(v, "_check_access", lambda bucket, key: None)
    with pytest.raises(TerminalError) as err:
        v._probe_columns("bkt", "alice/sales/liar.csv.gz", "csv")
    assert err.value.reason == messages.UNREADABLE_HEADER


# ── FR-005: partition detection ──────────────────────────────────────────────


def _partition_event(objects):
    """Run the verb and return (state_output, manifest).

    Partition NAMES ride in the state output; the observed VALUES live in the manifest
    (FR-006), so a partition assertion generally wants both.
    """
    _, fake = _setup(objects)
    out = v.handler(_event(), None)
    return out, _manifest_of(fake)


def test_a_flat_folder_has_no_partition_keys():
    out, manifest = _partition_event([("alice/sales/a.csv", 10), ("alice/sales/b.csv", 10)])
    assert out["partitionKeys"] == []
    assert manifest["partitionKeys"] == []


def test_plain_nested_folders_are_flat_not_a_mismatch():
    """No key=value anywhere, so this is simply an unpartitioned folder — Athena reads
    every file under LOCATION recursively and omits nothing."""
    out, _ = _partition_event(
        [("alice/sales/a.csv", 10), ("alice/sales/2024/b.csv", 10), ("alice/sales/2024/q1/c.csv", 10)]
    )
    assert out["partitionKeys"] == []


def test_a_partitioned_folder_records_keys_and_values():
    out, manifest = _partition_event(
        [("alice/sales/region=us/a.csv", 10), ("alice/sales/region=eu/b.csv", 10)]
    )
    assert out["partitionKeys"] == ["region"]
    assert manifest["partitionKeys"] == [{"name": "region", "values": ["eu", "us"]}]


def test_multiple_keys_keep_their_path_order():
    """Order is the granularity order SPEC-111's projection declares."""
    out, manifest = _partition_event(
        [("alice/sales/region=us/dt=2024-01/a.csv", 10), ("alice/sales/region=eu/dt=2024-02/b.csv", 10)]
    )
    assert out["partitionKeys"] == ["region", "dt"]
    assert [k["name"] for k in manifest["partitionKeys"]] == ["region", "dt"]


def test_a_stray_root_file_beside_partitions_is_a_mismatch():
    """The file belongs to no partition, so Athena would never scan it and the report
    would silently omit it."""
    with pytest.raises(TerminalError) as err:
        _partition_event([("alice/sales/region=us/a.csv", 10), ("alice/sales/stray.csv", 10)])
    assert err.value.reason == messages.PARTITION_LAYOUT_MISMATCH
    assert "stray.csv" in err.value.detail


def test_differing_partition_depth_is_a_mismatch():
    with pytest.raises(TerminalError) as err:
        _partition_event(
            [("alice/sales/region=us/a.csv", 10), ("alice/sales/region=eu/dt=2024-01/b.csv", 10)]
        )
    assert err.value.reason == messages.PARTITION_LAYOUT_MISMATCH


def test_a_plain_segment_inside_a_partitioned_source_is_a_mismatch():
    with pytest.raises(TerminalError) as err:
        _partition_event([("alice/sales/region=us/a.csv", 10), ("alice/sales/region=eu/extra/b.csv", 10)])
    assert err.value.reason == messages.PARTITION_LAYOUT_MISMATCH
    assert "extra" in err.value.detail


def test_a_plain_segment_shared_by_EVERY_object_is_still_a_mismatch():
    """The case the plain-segment guard exists for, and the only one that needs it.

    When the objects DISAGREE the consistency check already catches them ('extra' reads as
    a phantom key name). When they all share the segment, the signatures match and nothing
    upstream fires — so without the guard this reaches `seg.split("=", 1)` unpacking a
    one-element list and dies with a ValueError, which is not a TerminalError and so
    reaches the user as an unexplained failure rather than a reason.
    """
    with pytest.raises(TerminalError) as err:
        _partition_event(
            [("alice/sales/region=us/extra/a.csv", 10), ("alice/sales/region=eu/extra/b.csv", 10)]
        )
    assert err.value.reason == messages.PARTITION_LAYOUT_MISMATCH
    assert "extra" in err.value.detail


@pytest.mark.parametrize(
    "stray", ["alice/sales/region=/a.csv", "alice/sales/=us/a.csv"]
)
def test_an_empty_partition_key_or_value_is_a_mismatch(stray):
    """Hive spells an absent value __HIVE_DEFAULT_PARTITION__, so SPEC-111 would emit a
    projection enum containing "" — a partition resolving to nothing, whose files are then
    silently missing from the report. Same harm as a layout mismatch, so same terminal."""
    with pytest.raises(TerminalError) as err:
        _partition_event([("alice/sales/region=us/a.csv", 10), (stray, 10)])
    assert err.value.reason == messages.PARTITION_LAYOUT_MISMATCH


def test_too_many_partition_values_is_terminal_naming_key_count_and_limit(monkeypatch):
    """The cap is unreachable through the handler at the shipped defaults, so the cap
    itself is exercised directly.

    N distinct values require >= N objects (a value only exists because an object sits
    under it), so with DQ_MAX_PARTITION_VALUES == DQ_MAX_OBJECTS == 1000, breaching the
    value cap means first breaching the object cap and getting too_many_files. The value
    cap is a live guard only if it is LOWER than the object cap — see the note in
    dqcommon/config.py. Lowering it here is what makes the guard's own behaviour testable
    without asserting on a code path the defaults forbid.
    """
    monkeypatch.setattr(config, "DQ_MAX_PARTITION_VALUES", 2)
    objects = [(f"alice/sales/dt=2024-{i:02d}/a.csv", 10) for i in range(3)]
    with pytest.raises(TerminalError) as err:
        _partition_event(objects)
    assert err.value.reason == messages.TOO_MANY_PARTITION_VALUES
    assert "dt" in err.value.detail
    assert "3" in err.value.detail and "2" in err.value.detail


def test_the_object_cap_dominates_the_partition_value_cap_at_the_defaults():
    """Pins the relationship above: at the shipped defaults a source with more partition
    values than the cap ALWAYS trips too_many_files first. If someone raises
    DQ_MAX_OBJECTS without revisiting DQ_MAX_PARTITION_VALUES, this test tells them the
    value cap just went live."""
    assert config.DQ_MAX_PARTITION_VALUES >= config.DQ_MAX_OBJECTS
    objects = [(f"alice/sales/dt=2024-{i:05d}/a.csv", 10) for i in range(config.DQ_MAX_OBJECTS + 1)]
    with pytest.raises(TerminalError) as err:
        _partition_event(objects)
    assert err.value.reason == messages.TOO_MANY_FILES


def test_exactly_the_partition_value_cap_is_allowed(monkeypatch):
    monkeypatch.setattr(config, "DQ_MAX_PARTITION_VALUES", 3)
    objects = [(f"alice/sales/dt=2024-{i:02d}/a.csv", 10) for i in range(3)]
    _, manifest = _partition_event(objects)
    assert len(manifest["partitionKeys"][0]["values"]) == 3


def test_partition_values_are_deduped_and_sorted():
    """Deterministic: a retry must produce a byte-identical manifest, and listing order
    is not guaranteed stable."""
    _, manifest = _partition_event(
        [
            ("alice/sales/region=us/a.csv", 10),
            ("alice/sales/region=us/b.csv", 10),
            ("alice/sales/region=eu/c.csv", 10),
        ]
    )
    assert manifest["partitionKeys"] == [{"name": "region", "values": ["eu", "us"]}]


def test_a_single_file_location_under_partitions_is_not_a_mismatch():
    """One file listed as its own exact key has no relative dirs, so it is flat."""
    _setup([("alice/sales/region=us/a.csv", 10)], exact_keys=["alice/sales/region=us/a.csv"])
    out = v.handler(_event(location="alice/sales/region=us/a.csv"), None)
    assert out["partitionKeys"] == []
    assert out["fileCount"] == 1


# ── FR-006: the manifest and the bounded state output ────────────────────────


def _manifest_of(fake):
    assert len(fake.puts) == 1, f"expected exactly one manifest write, got {len(fake.puts)}"
    return json.loads(fake.puts[0]["Body"])


def test_the_manifest_is_written_to_the_report_prefix():
    _, fake = _setup([("alice/sales/a.csv", 4096)])
    out = v.handler(_event(), None)
    assert fake.puts[0]["Bucket"] == BUCKET
    assert fake.puts[0]["Key"] == "alice/_data-quality-reports/req-1/manifest.json"
    assert out["manifestKey"] == "alice/_data-quality-reports/req-1/manifest.json"


def test_the_manifest_carries_the_spec_shape():
    _, fake = _setup(
        [("alice/sales/region=us/a.csv", 4096), ("alice/sales/region=eu/b.csv", 8192)],
        columns={
            "alice/sales/region=us/a.csv": [
                {"name": "id", "type": "string"},
                {"name": "note", "type": "string"},
            ],
            "alice/sales/region=eu/b.csv": [{"name": "id", "type": "string"}],
        },
    )
    v.handler(_event(), None)
    assert _manifest_of(fake) == {
        "requestId": "req-1",
        "format": "csv",
        "fileCount": 2,
        "partitionKeys": [{"name": "region", "values": ["eu", "us"]}],
        "files": [
            {
                "key": "alice/sales/region=us/a.csv",
                "size": 4096,
                "columns": [{"name": "id", "type": "string"}, {"name": "note", "type": "string"}],
            },
            {
                "key": "alice/sales/region=eu/b.csv",
                "size": 8192,
                "columns": [{"name": "id", "type": "string"}],
            },
        ],
    }


def test_a_throttled_manifest_write_is_retryable_not_terminal():
    """The bug this pins: an unmapped put_object fault reaches the SFN as `ClientError`,
    which InspectSource's Retry list does NOT name — so a one-off SlowDown becomes a
    permanent failure whose user-facing reason is raw AWS text, after every file has
    already been probed. The verb is replay-safe, so a Retry simply rewrites the manifest.
    """
    _, fake = _setup([("alice/sales/a.csv", 10)])

    def _boom(Bucket, Key, Body, **kw):  # noqa: N803
        raise _FakeClientError("SlowDown")

    fake.put_object = _boom
    with pytest.raises(TransientError):
        v.handler(_event(), None)


def test_a_non_transient_manifest_write_error_is_not_disguised_as_retryable():
    _, fake = _setup([("alice/sales/a.csv", 10)])

    def _boom(Bucket, Key, Body, **kw):  # noqa: N803
        raise _FakeClientError("AccessDenied")

    fake.put_object = _boom
    with pytest.raises(_FakeClientError):
        v.handler(_event(), None)


def test_a_throttled_listing_is_retryable():
    """A throttled page mid-pagination is retryable; s3_listing lets it propagate raw, so
    the verb is what has to map it."""
    _setup([])

    def _boom(bucket, prefix):
        raise _FakeClientError("SlowDown")

    v.s3_listing.list_data_objects = _boom
    with pytest.raises(TransientError):
        v.handler(_event(), None)


def test_a_throttled_access_probe_is_retryable():
    """The real _check_access, not a stub — a throttle here must not become a permanent
    'the columns couldn't be read'."""
    _, fake = _setup([("alice/sales/a.csv", 10)])
    calls = []

    def _boom(Bucket, Key):  # noqa: N803
        calls.append(Key)
        raise _FakeClientError("Throttling")

    fake.head_object = _boom
    with pytest.raises(TransientError):
        v._check_access(BUCKET, "alice/sales/a.csv")
    assert calls == ["alice/sales/a.csv"]


def test_a_throttled_gzip_get_is_retryable_not_unreadable_header():
    """_read_gzip_head runs INSIDE _probe_columns' try, so without an explicit
    TransientError re-raise the catch-all would swallow it and report the file as
    permanently unreadable."""
    fake = _FakeS3()
    fake.get_object = lambda **kw: (_ for _ in ()).throw(_FakeClientError("SlowDown"))
    fake.head_object = lambda Bucket, Key: {"ContentLength": 10}  # noqa: N803
    v.clients.s3 = lambda: fake
    with pytest.raises(TransientError):
        v._probe_columns(BUCKET, "alice/sales/a.csv.gz", "csv")


def test_non_transient_faults_propagate_unchanged_from_every_read_path():
    """The other half of the mapping: only the retryable codes become TransientError.

    Disguising AccessDenied as retryable would burn the SFN's attempts on a fault that
    cannot resolve, and delay the real reason by the full backoff.
    """
    denied = _FakeClientError("AccessDenied")

    # listing
    _setup([])
    v.s3_listing.list_data_objects = lambda b, p: (_ for _ in ()).throw(denied)
    with pytest.raises(_FakeClientError):
        v.handler(_event(), None)

    # access probe
    _, fake = _setup([("alice/sales/a.csv", 10)])
    fake.head_object = lambda Bucket, Key: (_ for _ in ()).throw(denied)  # noqa: N803
    with pytest.raises(_FakeClientError):
        v._check_access(BUCKET, "alice/sales/a.csv")

    # gzip body read
    fake2 = _FakeS3()
    fake2.get_object = lambda **kw: (_ for _ in ()).throw(denied)
    v.clients.s3 = lambda: fake2
    with pytest.raises(_FakeClientError):
        v._read_gzip_head(BUCKET, "alice/sales/a.csv.gz")


def test_the_manifest_key_is_a_pure_function_of_the_request_and_a_replay_is_byte_identical():
    """The only idempotency this pipeline has: no verb does request-id bookkeeping, so a
    Retry must overwrite the SAME KEY with the SAME BYTES rather than leave a second
    artefact behind.

    Asserts the KEY as well as the body — an earlier version compared bodies only, and so
    passed even with a uuid4() in the key, i.e. it did not test the first half of its own
    name.
    """
    writes = []
    for _ in range(2):
        _, fake = _setup([("alice/sales/b.csv", 2), ("alice/sales/a.csv", 1)])
        v.handler(_event(), None)
        writes.append((fake.puts[0]["Key"], fake.puts[0]["Body"]))
    assert writes[0] == writes[1], "a replay must rewrite the same key with the same bytes"


# ── FR-006: the state payload bound ──────────────────────────────────────────


def test_the_state_payload_stays_tiny_at_the_object_cap_with_maximal_keys():
    """DQ_MAX_OBJECTS files with 1024-character keys — the worst case the caps allow.

    The disaster this prevents: a state payload over Step Functions' 256 KB raises
    States.DataLimitExceeded, which is thrown OUTSIDE every Catch — the execution dies
    without reaching NotifyFailure, so the user is told NOTHING, and it happens on exactly
    the biggest folders. Passing the manifest by POINTER is what keeps the payload flat.
    """
    long_dir = "d" * 990
    objects = [(f"alice/sales/{long_dir}/part-{i:04d}.csv", 1024) for i in range(config.DQ_MAX_OBJECTS)]
    assert len(objects[0][0]) > 1000, "fixture must use maximal-length keys"
    _setup(objects, columns=[{"name": f"col_{i}", "type": "string"} for i in range(50)])

    out = v.handler(_event(), None)

    payload = json.dumps(out).encode()
    assert len(payload) < 8 * 1024, f"state payload is {len(payload)} bytes"
    assert out["fileCount"] == config.DQ_MAX_OBJECTS


def test_the_payload_stays_bounded_when_partition_key_NAMES_are_the_worst_case():
    """The file list rides as a pointer, so partition-key NAMES are the only thing left in
    the payload that grows with the input — and the test above uses a flat folder, which
    exercises none of them. Bounded transitively by S3's 1024-byte key limit (a key can
    hold ~250 `a=1/` segments), but bounded-by-luck is worth pinning.
    """
    segments = "/".join(f"k{i:03d}=v" for i in range(120))
    objects = [(f"alice/sales/{segments}/part-{i}.csv", 10) for i in range(5)]
    assert len(objects[0][0]) < 1024, "fixture must stay inside S3's key limit"
    _setup(objects)

    out = v.handler(_event(), None)

    assert len(out["partitionKeys"]) == 120
    assert len(json.dumps(out).encode()) < 8 * 1024


def test_long_partition_VALUES_do_not_reach_the_payload():
    """Values live in the manifest; only names ride in the state."""
    long_value = "v" * 900
    _setup([(f"alice/sales/region={long_value}/a.csv", 10), ("alice/sales/region=eu/b.csv", 10)])
    out = v.handler(_event(), None)
    payload = json.dumps(out)
    assert long_value not in payload
    assert len(payload.encode()) < 8 * 1024


def test_the_state_output_never_inlines_the_file_list_or_columns():
    _, fake = _setup([("alice/sales/a.csv", 10), ("alice/sales/b.csv", 10)])
    out = v.handler(_event(), None)
    assert "files" not in out
    assert "columns" not in out
    # The data is in the manifest, not the payload.
    assert len(_manifest_of(fake)["files"]) == 2


def test_the_state_output_carries_partition_key_NAMES_not_values():
    """Values are capped at DQ_MAX_PARTITION_VALUES per key — far too many to ride in the
    payload. SPEC-111 reads them from the manifest when it builds the projection enum."""
    _, fake = _setup([("alice/sales/region=us/a.csv", 10), ("alice/sales/region=eu/b.csv", 10)])
    out = v.handler(_event(), None)
    assert out["partitionKeys"] == ["region"]
    assert _manifest_of(fake)["partitionKeys"] == [{"name": "region", "values": ["eu", "us"]}]


def test_the_state_output_threads_the_identity_contract():
    """SPEC-109's contract, and it is uncatchable if broken: RecordSuccess/RecordFailure
    read $.requestId/$.actor, and a Pass state's JSONPath hard-fails on an ABSENT key with
    States.Runtime — skipping NotifyFailure and leaving the user with no notification at
    all. This is why FR-006's "only" means "add only", not "keep only"."""
    _setup([("alice/sales/a.csv", 10)])
    out = v.handler(_event(), None)
    assert out["requestId"] == "req-1"
    assert out["actor"] == "alice"


def test_the_state_output_threads_what_spec_111_needs():
    _setup([("alice/sales/a.csv", 10)])
    out = v.handler(_event(), None)
    assert out["space"]["bucket"] == BUCKET
    assert out["location"] == LOCATION
    assert out["reportPrefix"] == "alice/_data-quality-reports/req-1/"


def test_a_missing_report_prefix_is_invalid_request():
    """Rather than a bare KeyError the SFN records as an opaque failure."""
    _setup([("alice/sales/a.csv", 10)])
    event = _event()
    del event["reportPrefix"]
    with pytest.raises(TerminalError) as err:
        v.handler(event, None)
    assert err.value.reason == messages.INVALID_REQUEST


def test_no_manifest_is_written_when_the_request_fails():
    """A terminal before the write must not leave a half-truth in the report prefix."""
    _, fake = _setup([("alice/sales/a.csv", 10), ("alice/sales/b.parquet", 10)])
    with pytest.raises(TerminalError):
        v.handler(_event(), None)
    assert fake.puts == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
