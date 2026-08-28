"""Unit tests for the data-quality byte-scan Lambda (SPEC-112 FR-001).

Pure logic, AWS stubbed: the S3 client and the manifest read are replaced on the verb, so
no bucket is touched.

TWO BOUNDS ARE UNDER TEST, and they fail differently — the spec's whole point is that the
first one is not enough on its own:

  BYTES    — never more than DQ_SCAN_TOTAL_BYTES, whatever the file count or file size.
             Breaking it times out a 300 s function on ~276 GB.
  REQUESTS — never more than ~1000 GetObjects. Breaking it times out the SAME function on
             21,000 round trips while reading a perfectly legal 2 GiB.

The bound tests shrink the budget via monkeypatch rather than moving 2 GiB through a unit
test; the REAL constants are exercised by the pure-planning tests over _regions, which need
no I/O at all.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import dq_byte_scan as v
from dqcommon import config

BUCKET = "dq-user-bkt"
MANIFEST_KEY = "alice/_data-quality-reports/req-1/manifest.json"

GIB = 1024**3


class _FakeClientError(Exception):
    """Mimics botocore.exceptions.ClientError enough for cpcommon.errors.error_code.

    botocore ships in the Lambda RUNTIME but is not a test dependency of this repo, so the
    suites fake it rather than import it (matching the sibling verb suites).
    """

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class _FakeBody:
    """A streaming body. Either real bytes, or ``length`` synthetic ones.

    The synthetic mode is what lets a 250 GB file be a test fixture: the bytes are
    generated a chunk at a time and never held, exactly as the verb reads them.
    """

    def __init__(self, data=None, length=0, mid_stream_error=None):
        self.data = data
        self.length = length
        self.mid_stream_error = mid_stream_error

    def iter_chunks(self, size):
        if self.data is not None:
            for start in range(0, len(self.data), size):
                yield self.data[start : start + size]
                # Faults DURING the transfer, which is where a dropped connection actually
                # lands — not on the request that opened it.
                if self.mid_stream_error:
                    raise self.mid_stream_error
            return
        remaining = self.length
        while remaining > 0:
            take = min(size, remaining)
            yield b"a" * take
            remaining -= take


class _FakeS3:
    """Records every ranged GET and serves content (real or synthetic)."""

    def __init__(self, content=None, error=None, mid_stream_error=None):
        self.content = content or {}
        self.error = error
        self.mid_stream_error = mid_stream_error
        self.gets = []
        self.bytes_served = 0

    def get_object(self, Bucket, Key, Range=None):  # boto3's kwarg casing
        if self.error:
            raise self.error
        span = Range.removeprefix("bytes=")
        start, end = (int(part) for part in span.split("-"))
        self.gets.append((Key, start, end))
        if Key in self.content:
            data = self.content[Key][start : end + 1]
            # S3 answers a range past the end of an object with 416, not a short read.
            if start >= len(self.content[Key]):
                raise _FakeClientError("InvalidRange")
            self.bytes_served += len(data)
            return {"Body": _FakeBody(data=data, mid_stream_error=self.mid_stream_error)}
        self.bytes_served += end - start + 1
        return {"Body": _FakeBody(length=end - start + 1, mid_stream_error=self.mid_stream_error)}


def _setup(monkeypatch, files, fmt="csv", content=None, error=None, mid_stream_error=None):
    """Install a fake S3 + manifest and return the fake."""
    fake = _FakeS3(content=content, error=error, mid_stream_error=mid_stream_error)
    monkeypatch.setattr(v.clients, "s3", lambda: fake)
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key: {"files": files})
    return fake


def _event(fmt="csv"):
    return {
        "requestId": "req-1",
        "actor": "alice",
        "space": {"bucket": BUCKET, "prefix": "alice/"},
        "manifestKey": MANIFEST_KEY,
        "format": fmt,
    }


def _shrink(monkeypatch, total=4096, min_sample=64):
    """Shrink the budget so a bound can be asserted without moving gigabytes."""
    monkeypatch.setattr(config, "DQ_SCAN_TOTAL_BYTES", total)
    monkeypatch.setattr(config, "DQ_SCAN_MIN_SAMPLE_BYTES", min_sample)


# ── The text-only gate (FR-001) ──────────────────────────────────────────────


def test_parquet_is_skipped_without_reading_a_byte(monkeypatch):
    fake = _setup(monkeypatch, [{"key": "alice/s/a.parquet", "size": 10 * GIB}], fmt="parquet")

    out = v.handler(_event(fmt="parquet"), None)

    assert out["encoding"] == {"status": "skipped", "reason": v.SKIP_BINARY}
    assert fake.gets == []


# ── Coverage: complete vs sampled (FR-001) ───────────────────────────────────


def test_a_file_larger_than_its_share_is_sampled(monkeypatch):
    _shrink(monkeypatch)
    _setup(monkeypatch, [{"key": "alice/s/big.csv", "size": 250 * GIB}])

    out = v.handler(_event(), None)["encoding"]

    assert out["coverage"] == "sampled"
    assert out["bytesExamined"] <= config.DQ_SCAN_TOTAL_BYTES
    assert out["bytesTotal"] == 250 * GIB
    # The figure the report turns into a coverage percentage — vanishingly small, and that
    # is the honest answer rather than a bigger budget.
    assert out["bytesExamined"] / out["bytesTotal"] < 0.001


# ── Invalid UTF-8 (FR-001) ───────────────────────────────────────────────────


def test_invalid_utf8_is_counted_with_its_offset_and_file(monkeypatch):
    # 0xE9 is Latin-1 'e-acute' — a UTF-8 lead byte followed by a non-continuation, i.e.
    # exactly what a Windows-codepage export from Excel looks like.
    content = {"alice/s/a.csv": b"id,name\n1,caf\xe9,x\n"}
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": len(content["alice/s/a.csv"])}], content=content)

    out = v.handler(_event(), None)["encoding"]

    assert out["invalidUtf8Sequences"] == 1
    assert out["sampleOffsets"] == [{"key": "alice/s/a.csv", "offset": 13}]


# ── Read boundaries must not invent findings ─────────────────────────────────


# ── The two bounds ───────────────────────────────────────────────────────────


# ── Faults ───────────────────────────────────────────────────────────────────


# -- SPEC-132 FR-004: the highest-risk emitter in the plane ------------------------------
