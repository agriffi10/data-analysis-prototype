"""Unit tests for the data-quality inspect-source Lambda (SPEC-110).

Pure logic, AWS stubbed: s3_listing.list_data_objects and the S3 client are replaced on
the verb module, so no bucket is touched.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import pytest  # noqa: E402
from cpcommon.errors import TerminalError  # noqa: E402
from dqcommon import config, messages  # noqa: E402

import dq_inspect_source as v  # noqa: E402

BUCKET = "dq-user-bkt"
LOCATION = "alice/sales"


class _FakeClientError(Exception):
    """Mimics botocore.exceptions.ClientError enough for dq_inspect_source._error_code.

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

    def head_object(self, Bucket, Key):  # noqa: N803 - boto3's kwarg casing
        self.head_calls.append(Key)
        if Key in self.keys:
            return {"ContentLength": 1}
        raise _FakeClientError("404")


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
        raise _FakeClientError("503")

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
    """Run the probe against a local file by stubbing the s3:// URI + access probe."""
    monkeypatch.setattr(v, "_check_access", lambda bucket, key: None)
    monkeypatch.setattr(v, "_object_uri", lambda bucket, key: path)
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


def test_the_probe_reads_s3_directly_never_downloading():
    """polars' object_store fetches only the ranges the scan needs; no /tmp, no download."""
    assert v._object_uri("bkt", "alice/sales/a.parquet") == "s3://bkt/alice/sales/a.parquet"


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
    _setup([("alice/sales/a.csv", 10), ("alice/sales/b.csv", 10), ("alice/sales/c.csv", 10)])
    real_probe = v._probe_columns
    v._probe_columns = lambda bucket, key, fmt: probed.append(key) or real_probe(bucket, key, fmt)
    out = v.handler(_event(), None)
    assert probed == ["alice/sales/a.csv", "alice/sales/b.csv", "alice/sales/c.csv"]
    assert len(out["files"]) == 3


def test_files_disagreeing_on_columns_is_recorded_not_rejected():
    """The input SPEC-112 must report on — inspect-source records it and moves on."""
    _setup(
        [("alice/sales/a.csv", 10), ("alice/sales/b.csv", 10)],
        columns={
            "alice/sales/a.csv": [{"name": "id", "type": "string"}, {"name": "note", "type": "string"}],
            "alice/sales/b.csv": [{"name": "id", "type": "string"}],
        },
    )
    out = v.handler(_event(), None)
    assert [len(f["columns"]) for f in out["files"]] == [2, 1]
    assert [f["key"] for f in out["files"]] == ["alice/sales/a.csv", "alice/sales/b.csv"]


# ── FR-005: the gzip probe's byte bound ──────────────────────────────────────


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


def test_gzip_probe_reads_far_less_than_the_object(monkeypatch):
    """gzip is not seekable, so "bounded range" is false — the probe streams and ABANDONS.

    Pins the FR-005 byte bound: what is read stays under GZIP_PROBE_MAX_BYTES and is a
    small fraction of the object, so a 1 GiB .gz costs a few MB to probe, not 1 GiB.
    """
    blob, uncompressed_len = _gzip_source()
    counter = {"read": 0}
    body = _CountingBody(blob, counter)
    v.clients.s3 = lambda: type("S3", (), {"get_object": staticmethod(lambda **kw: {"Body": body})})()

    head = v._read_gzip_head("bkt", "alice/sales/big.csv.gz")

    assert counter["read"] <= v.GZIP_PROBE_MAX_BYTES
    assert counter["read"] < len(blob), "the probe drained the whole compressed object"
    assert len(head) < uncompressed_len, "the probe decompressed the whole object"
    assert body.closed, "the stream must be abandoned, not left open"
    assert head.startswith(b"id,amount,note\n")
    assert head.endswith(b"\n"), "a partial trailing line would break the parse"


def test_gzip_probe_yields_the_same_columns_as_the_plain_file(monkeypatch):
    blob, _ = _gzip_source(rows=5)
    body = _CountingBody(blob, {"read": 0})
    v.clients.s3 = lambda: type("S3", (), {"get_object": staticmethod(lambda **kw: {"Body": body})})()
    monkeypatch.setattr(v, "_check_access", lambda bucket, key: None)
    columns = v._probe_columns("bkt", "alice/sales/big.csv.gz", "csv")
    assert [c["name"] for c in columns] == ["id", "amount", "note"]
    assert {c["type"] for c in columns} == {"string"}


# ── FR-005: partition detection ──────────────────────────────────────────────


def _partition_event(objects):
    _setup(objects)
    return v.handler(_event(), None)


def test_a_flat_folder_has_no_partition_keys():
    out = _partition_event([("alice/sales/a.csv", 10), ("alice/sales/b.csv", 10)])
    assert out["partitionKeys"] == []


def test_plain_nested_folders_are_flat_not_a_mismatch():
    """No key=value anywhere, so this is simply an unpartitioned folder — Athena reads
    every file under LOCATION recursively and omits nothing."""
    out = _partition_event(
        [("alice/sales/a.csv", 10), ("alice/sales/2024/b.csv", 10), ("alice/sales/2024/q1/c.csv", 10)]
    )
    assert out["partitionKeys"] == []


def test_a_partitioned_folder_records_keys_and_values():
    out = _partition_event([("alice/sales/region=us/a.csv", 10), ("alice/sales/region=eu/b.csv", 10)])
    assert out["partitionKeys"] == [{"name": "region", "values": ["eu", "us"]}]


def test_multiple_keys_keep_their_path_order():
    """Order is the granularity order SPEC-111's projection declares."""
    out = _partition_event(
        [("alice/sales/region=us/dt=2024-01/a.csv", 10), ("alice/sales/region=eu/dt=2024-02/b.csv", 10)]
    )
    assert [k["name"] for k in out["partitionKeys"]] == ["region", "dt"]


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
    out = _partition_event(objects)
    assert len(out["partitionKeys"][0]["values"]) == 3


def test_partition_values_are_deduped_and_sorted():
    """Deterministic: a retry must produce a byte-identical manifest, and listing order
    is not guaranteed stable."""
    out = _partition_event(
        [
            ("alice/sales/region=us/a.csv", 10),
            ("alice/sales/region=us/b.csv", 10),
            ("alice/sales/region=eu/c.csv", 10),
        ]
    )
    assert out["partitionKeys"] == [{"name": "region", "values": ["eu", "us"]}]


def test_a_single_file_location_under_partitions_is_not_a_mismatch():
    """One file listed as its own exact key has no relative dirs, so it is flat."""
    _setup([("alice/sales/region=us/a.csv", 10)], exact_keys=["alice/sales/region=us/a.csv"])
    out = v.handler(_event(location="alice/sales/region=us/a.csv"), None)
    assert out["partitionKeys"] == []
    assert out["fileCount"] == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
