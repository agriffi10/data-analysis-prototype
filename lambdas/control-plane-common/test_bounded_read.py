"""Tests for cpcommon.bounded_read.

Stubs the S3 client, never polars: the point of this module is the BYTES handed to
polars and the fact that a big object is not drained to get them. The fake body counts
what was actually read, so "bounded" is asserted by observation rather than assumed.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon import bounded_read, clients
from cpcommon.errors import TransientError


class _FakeClientError(Exception):
    """A botocore-SHAPED error: carries ``.response["Error"]["Code"]``."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class _FakeBody:
    def __init__(self, data, chunk_size=None):
        self._data = data
        self._chunk_size = chunk_size
        self.bytes_read = 0
        self.closed = False

    def iter_chunks(self, size):
        step = self._chunk_size or size
        for start in range(0, len(self._data), step):
            piece = self._data[start: start + step]
            self.bytes_read += len(piece)
            yield piece

    def close(self):
        self.closed = True


class _FakeS3:
    def __init__(self, body=None, error=None):
        self.body = body
        self.error = error
        self.calls = []

    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"Body": self.body}


def _install(data, chunk_size=None):
    body = _FakeBody(data, chunk_size)
    clients._s3 = _FakeS3(body=body)
    return body


def test_partial_final_line_is_dropped():
    """A truncated last row would make polars invent a column or fail to parse."""
    body = _install(b"a,b,c\n1,2,3\n4,5", chunk_size=4)
    assert bounded_read.read_head("bkt", "k") == b"a,b,c\n1,2,3\n"
    assert body.closed


def test_object_with_no_newline_is_returned_whole():
    _install(b"a,b,c")
    assert bounded_read.read_head("bkt", "k") == b"a,b,c"


def test_stops_at_max_lines_without_draining_the_object():
    """The whole point: the 31 MiB CSV that broke table-builder must not be downloaded.

    Reading stops at the first chunk boundary at or past max_lines, so the result may
    overshoot by part of a chunk — it is a bound, not an exact line count. What matters
    is that it covers the requested lines and stops far short of the object.
    """
    data = b"".join(b"line%d\n" % n for n in range(10_000))
    body = _install(data, chunk_size=16)
    out = bounded_read.read_head("bkt", "k", max_lines=3)
    assert out.startswith(b"line0\nline1\nline2\n")
    assert out.endswith(b"\n"), "whole lines only"
    assert len(out) < len(data) / 100, "a bounded head, not most of the object"
    assert body.bytes_read < len(data), "read the whole object instead of a bounded head"
    assert body.closed, "the rest of the body must be abandoned, not left open"


def test_stops_at_the_byte_ceiling_on_one_giant_line():
    """A pathologically long single line can't grow the buffer without limit."""
    data = b"x" * 5000 + b"\n" + b"y" * 5000 + b"\n"
    body = _install(data, chunk_size=100)
    out = bounded_read.read_head("bkt", "k", max_lines=1000, max_bytes=1000)
    assert len(out) <= 1000
    assert body.bytes_read < len(data)


def test_reads_the_requested_object():
    _install(b"h\n")
    bounded_read.read_head("my-bucket", "alice/sales/part-0.csv")
    assert clients._s3.calls == [{"Bucket": "my-bucket", "Key": "alice/sales/part-0.csv"}]


def test_throttled_get_is_raised_as_TransientError():
    """Must reach the SFN as a name its Retry lists — a bare ClientError matches nothing
    there and would permanently fail a request a retry would have fixed."""
    clients._s3 = _FakeS3(error=_FakeClientError("SlowDown"))
    try:
        bounded_read.read_head("bkt", "k")
    except TransientError:
        return
    raise AssertionError("expected TransientError from a throttled GetObject")


def test_deterministic_get_error_propagates_unchanged():
    clients._s3 = _FakeS3(error=_FakeClientError("AccessDenied"))
    try:
        bounded_read.read_head("bkt", "k")
    except TransientError:
        raise AssertionError("a deterministic fault must NOT become TransientError")
    except _FakeClientError as err:
        assert err.response["Error"]["Code"] == "AccessDenied"
        return
    raise AssertionError("expected the original ClientError to propagate")


class _RangeS3:
    """Serves byte ranges out of an in-memory blob, recording each request."""

    def __init__(self, blob):
        self.blob = blob
        self.ranges = []
        self.head_calls = 0

    def head_object(self, **kwargs):
        self.head_calls += 1
        return {"ContentLength": len(self.blob)}

    def get_object(self, Bucket=None, Key=None, Range=None):  # boto3 casing
        self.ranges.append(Range)
        start, end = Range.split("=")[1].split("-")
        return {"Body": io.BytesIO(self.blob[int(start): int(end) + 1])}


def _ranged(blob):
    fake = _RangeS3(blob)
    clients._s3 = fake
    return fake


def test_range_reader_reads_a_slice_from_the_middle():
    fake = _ranged(b"0123456789")
    reader = bounded_read.S3RangeReader("bkt", "k")
    reader.seek(3)
    assert reader.read(4) == b"3456"
    assert fake.ranges == ["bytes=3-6"]


def test_range_reader_seeks_from_the_end():
    """SEEK_END is how a Parquet reader finds the footer, so it must resolve against size."""
    _ranged(b"0123456789")
    reader = bounded_read.S3RangeReader("bkt", "k")
    reader.seek(-4, io.SEEK_END)
    assert reader.tell() == 6
    assert reader.read(4) == b"6789"


def test_range_reader_seeks_relative_to_the_current_position():
    _ranged(b"0123456789")
    reader = bounded_read.S3RangeReader("bkt", "k")
    reader.seek(2)
    reader.seek(3, io.SEEK_CUR)
    assert reader.read(2) == b"56"


def test_range_reader_clamps_a_read_past_the_end():
    """An unclamped range would be an S3 InvalidRange error, not a short read."""
    fake = _ranged(b"0123456789")
    reader = bounded_read.S3RangeReader("bkt", "k")
    reader.seek(8)
    assert reader.read(100) == b"89"
    assert fake.ranges == ["bytes=8-9"]


def test_range_reader_at_eof_returns_empty_without_a_request():
    fake = _ranged(b"0123456789")
    reader = bounded_read.S3RangeReader("bkt", "k")
    reader.seek(0, io.SEEK_END)
    assert reader.read(10) == b""
    assert fake.ranges == [], "a read at EOF must not issue a GET"


def test_range_reader_fetches_the_size_once():
    """head_object is the only unranged call; repeating it per read would triple the
    request count on a footer probe."""
    fake = _ranged(b"0123456789")
    reader = bounded_read.S3RangeReader("bkt", "k")
    reader.seek(-2, io.SEEK_END)
    reader.read(1)
    reader.seek(-4, io.SEEK_END)
    reader.read(1)
    assert fake.head_calls == 1


def test_range_reader_is_seekable_and_readable():
    """polars checks these before it will seek rather than slurp."""
    _ranged(b"abc")
    reader = bounded_read.S3RangeReader("bkt", "k")
    assert reader.seekable() and reader.readable()


def test_range_reader_maps_a_throttled_get_to_TransientError():
    class _Throttled(_RangeS3):
        def get_object(self, **kwargs):
            raise _FakeClientError("SlowDown")

    clients._s3 = _Throttled(b"0123456789")
    reader = bounded_read.S3RangeReader("bkt", "k")
    try:
        reader.read(4)
    except TransientError:
        return
    raise AssertionError("expected TransientError from a throttled ranged GET")


def test_range_reader_maps_a_throttled_head_to_TransientError():
    class _Throttled(_RangeS3):
        def head_object(self, **kwargs):
            raise _FakeClientError("SlowDown")

    clients._s3 = _Throttled(b"0123456789")
    try:
        bounded_read.S3RangeReader("bkt", "k").seek(0, io.SEEK_END)
    except TransientError:
        return
    raise AssertionError("expected TransientError from a throttled size probe")


def test_range_reader_serves_a_parquet_smaller_than_the_footer_read_ahead():
    """A small Parquet must work too — the common case for a first upload.

    polars looks for the footer ~64 KiB back from the end, which on a small object is
    before byte 0. polars clamps that itself (measured: a 903-byte file is fetched as a
    single ``bytes=0-902``), so this does NOT exercise our own seek clamp — see
    test_range_reader_clamps_a_seek_before_the_start for that. What it does prove is that
    a whole-object-sized range round-trips and yields the right schema.
    """
    import polars as pl

    blob = io.BytesIO()
    pl.DataFrame({"id": pl.Series(range(50), dtype=pl.Int64), "note": pl.Series(["a"] * 50)}).write_parquet(blob)
    data = blob.getvalue()
    assert len(data) < 64 * 1024, "fixture must be smaller than the footer read-ahead"
    fake = _ranged(data)

    schema = pl.read_parquet_schema(bounded_read.S3RangeReader("bkt", "k"))

    assert [*schema] == ["id", "note"]
    assert all(int(r.split("=")[1].split("-")[0]) >= 0 for r in fake.ranges), "negative range offset"


def test_range_reader_clamps_a_seek_before_the_start():
    """Seeking further back than the object is long lands at 0, not at a negative offset.

    Defensive: polars clamps this itself today, so no polars-driven test reaches it. An
    unclamped position would render as "bytes=-44000-..." — a malformed range S3 rejects —
    so the contract is asserted directly rather than left to a caller's good behaviour.
    """
    fake = _ranged(b"0123456789")
    reader = bounded_read.S3RangeReader("bkt", "k")
    assert reader.seek(-100_000, io.SEEK_END) == 0
    assert reader.read(3) == b"012"
    assert fake.ranges == ["bytes=0-2"]


def test_range_reader_serves_a_real_parquet_footer_to_polars():
    """End to end, the property that matters: polars gets the right schema and the reader
    hands it only a small tail of the object.

    The object has to be comfortably larger than polars' footer read-ahead (~64 KiB) for
    this to assert anything — below that size the "footer read" IS the whole file, which
    is fine but proves nothing. An earlier version used a 58 KB fixture and failed for
    exactly that reason.
    """
    import polars as pl

    blob = io.BytesIO()
    pl.DataFrame({
        "id": pl.Series(range(400_000), dtype=pl.Int64),
        "amount": pl.Series([1.5] * 400_000, dtype=pl.Float64),
        "note": pl.Series(["abcdefghij"] * 400_000),
    }).write_parquet(blob, row_group_size=20_000)
    data = blob.getvalue()
    assert len(data) > 300_000, "fixture must dwarf the footer read-ahead"
    fake = _ranged(data)

    schema = pl.read_parquet_schema(bounded_read.S3RangeReader("bkt", "k"))

    assert [*schema] == ["id", "amount", "note"]
    served = sum(int(r.split("-")[1]) - int(r.split("=")[1].split("-")[0]) + 1 for r in fake.ranges)
    # Bounded by metadata size, not object size: a fixed ~64 KiB tail however big the file.
    assert served <= 256 * 1024, f"footer read grew to {served} bytes"
    assert served < len(data) / 4, f"read {served} of {len(data)} — not a footer read"
    starts = [int(r.split("=")[1].split("-")[0]) for r in fake.ranges]
    assert min(starts) > len(data) / 2, "the footer read must sit in the object's tail"
