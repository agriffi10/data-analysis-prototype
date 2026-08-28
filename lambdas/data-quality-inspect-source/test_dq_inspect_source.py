"""Unit tests for the data-quality inspect-source Lambda (SPEC-110).

Pure logic, AWS stubbed: s3_listing.list_data_objects and the S3 client are replaced on
the verb module, so no bucket is touched.
"""

import io
import json
import os
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import dq_inspect_source as v
import pytest
from cpcommon.errors import TerminalError, TransientError
from dqcommon import messages

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

    def head_object(self, Bucket, Key):  # boto3's kwarg casing
        self.head_calls.append(Key)
        if Key in self.keys:
            return {"ContentLength": 1}
        raise _FakeClientError("404")

    def put_object(self, Bucket, Key, Body, **kw):
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


# ── SPEC-151 FR-002: a single-file listing matches the object, not the prefix ────


def test_a_single_file_check_ignores_siblings_sharing_its_stem():
    """list_objects_v2 is a PREFIX match, so data.csv also returns data.csv.gz.

    Left unfiltered this was the worst defect in the plane: the extra keys made
    `keys == [prefix]` false in create-temp-tables, so the parent-folder promotion did not
    apply, the external table was built at s3://…/data.csv/ over nothing, and GROUPING SETS
    still emitted a total row — so the user got verdict "clean", rowCount 0, over data
    nothing had read.
    """
    listed, fake = _setup(
        [
            ("alice/sales/data.csv", 10),
            ("alice/sales/data.csv.gz", 20),
            ("alice/sales/data.csv2", 30),
        ],
        exact_keys=["alice/sales/data.csv"],
    )

    out = v.handler(_event(location="alice/sales/data.csv"), None)

    assert listed == [(BUCKET, "alice/sales/data.csv")]
    assert out["fileCount"] == 1
    assert [f["key"] for f in _manifest_of(fake)["files"]] == ["alice/sales/data.csv"]


def test_empty_location_is_terminal_no_data_files():
    _setup([])
    with pytest.raises(TerminalError) as err:
        v.handler(_event(), None)
    assert err.value.reason == messages.NO_DATA_FILES


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
    fake.head_object = lambda Bucket, Key: {"ContentLength": 0}
    v.clients.s3 = lambda: fake
    listed = []
    v.s3_listing.list_data_objects = lambda bucket, prefix: (
        listed.append((bucket, prefix)) or iter([("alice/sales/a.csv", 10)])
    )
    v._probe_columns = lambda bucket, key, fmt: list(_DEFAULT_COLUMNS)

    v.handler(_event(), None)

    assert listed == [(BUCKET, "alice/sales/")], "a zero-byte hit must not become a file"


def test_a_transient_head_error_is_retryable_not_a_folder():
    """Only a real 404 means "folder"; a 503 must not be mistaken for one — and must reach
    the SFN as a TransientError, the ONLY name in InspectSource's Retry list our own code
    can raise. A bare ClientError matches nothing there and would be recorded as a
    permanent failure carrying raw AWS text."""
    _setup([])
    fake = _FakeS3()

    def _boom(Bucket, Key):
        raise _FakeClientError("SlowDown")

    fake.head_object = _boom
    v.clients.s3 = lambda: fake
    with pytest.raises(TransientError):
        v.handler(_event(), None)


# ── FR-002: extension-based classification ───────────────────────────────────


# ── FR-003: single-format enforcement ────────────────────────────────────────


# ── FR-004: caps ─────────────────────────────────────────────────────────────


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
    ``_read_plain_head`` (a boto3 buffer — polars' cloud reader does not work in Lambda) so
    the stub feeds polars the file's bytes; Parquet reads through a ranged file object (its
    schema is a footer at the END, unreachable by a head read), so the stub hands
    ``_parquet_source`` a local file object, which polars seeks the same way.
    """
    monkeypatch.setattr(v, "_check_access", lambda bucket, key: None)
    if fmt == "parquet":
        # Seam handle: polars reads it after the lambda returns, so it must stay open.
        monkeypatch.setattr(
            v, "_parquet_source", lambda bucket, key: open(path, "rb")  # noqa: SIM115
        )
    else:
        with open(path, "rb") as fh:
            data = fh.read()
        monkeypatch.setattr(v, "_read_plain_head", lambda bucket, key: data)
    return v._probe_columns("bkt", "some/key", fmt)


# ── FR-005: the gzip probe's byte bound ──────────────────────────────────────


# The probe checks its bounds after each chunk, so it can overshoot by at most one chunk.
_CHUNK_SLACK = 256 * 1024


def _install_ranged_object(path):
    """Serve ``path`` over a fake S3 that honours Range, recording what was fetched.

    The Parquet footer read is only meaningful if the bytes are counted — this is what
    makes "reads the footer, not the object" an assertion rather than a claim.
    """
    served = {"bytes": 0, "ranges": []}
    size = os.path.getsize(path)

    class _S3:
        @staticmethod
        def head_object(Bucket, Key):  # boto3's kwarg casing
            return {"ContentLength": size}

        @staticmethod
        def get_object(Bucket, Key, Range=None):
            with open(path, "rb") as fh:
                if Range is None:
                    data = fh.read()
                else:
                    start, end = Range.split("=")[1].split("-")
                    fh.seek(int(start))
                    data = fh.read(int(end) - int(start) + 1)
            served["bytes"] += len(data)
            served["ranges"].append(Range)
            return {"Body": io.BytesIO(data)}

    v.clients.s3 = lambda: _S3()
    return served


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


# ── FR-005: partition detection ──────────────────────────────────────────────


def _partition_event(objects):
    """Run the verb and return (state_output, manifest).

    Partition NAMES ride in the state output; the observed VALUES live in the manifest
    (FR-006), so a partition assertion generally wants both.
    """
    _, fake = _setup(objects)
    out = v.handler(_event(), None)
    return out, _manifest_of(fake)


# ── FR-006: the manifest and the bounded state output ────────────────────────


def _manifest_of(fake):
    assert len(fake.puts) == 1, f"expected exactly one manifest write, got {len(fake.puts)}"
    return json.loads(fake.puts[0]["Body"])


# ── FR-006: the state payload bound ──────────────────────────────────────────


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# -- SPEC-132: the narrative ------------------------------------------------------------


def _probe_that_quotes_a_cell(secret):
    def _boom(bucket, key, fmt):
        try:
            raise ValueError(f"could not parse '{secret}' as dtype i64")
        except ValueError as exc:
            raise TerminalError(
                messages.UNREADABLE_HEADER,
                f"could not read the schema of {key}: {exc}",
                tokens={"object": key},
            ) from exc

    return _boom
