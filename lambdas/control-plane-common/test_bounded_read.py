"""Tests for cpcommon.bounded_read.

Stubs the S3 client, never polars: the point of this module is the BYTES handed to
polars and the fact that a big object is not drained to get them. The fake body counts
what was actually read, so "bounded" is asserted by observation rather than assumed.
"""

import datetime
import decimal
import io
import os
import pathlib
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon import bounded_read, clients
from cpcommon.errors import TransientError
from cpcommon.parquet_trailer import ParquetTrailerError


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


class _CountingBody:
    """A response body that counts what is actually READ from it, not what it holds."""

    def __init__(self, data):
        self._data = data
        self.bytes_read = 0
        self.closed = False

    def read(self, amt=None):
        piece = self._data[self.bytes_read:] if amt is None else self._data[self.bytes_read: self.bytes_read + amt]
        self.bytes_read += len(piece)
        return piece

    def close(self):
        self.closed = True


class RangedS3:
    """Serves one object's byte ranges the way S3 does, recording every range and every byte read.

    The three answers that matter are S3's own, not a convenient approximation: a suffix range
    longer than the object returns the whole object; an empty object refuses any range as
    ``InvalidRange``; and a range S3 cannot parse — an inverted one — is IGNORED, the whole object
    coming back with no ``ContentRange``. ``ignore_ranges_from`` makes every request from that
    one-based position on answer as if its range had been ignored, and ``body_skew`` makes every
    body that many bytes longer (or, negative, shorter) than the length its response declares.
    ``served`` is bytes read out of bodies, so a reader that refuses a response unread is charged
    nothing for it.

    The verb suites import this rather than keep copies, because a fake that answers ranges
    differently in three files is three claims about S3.
    """

    def __init__(self, blob, ignore_ranges_from=None, body_skew=0):
        self.blob = blob
        self.ranges = []
        self.bodies = []
        self.head_calls = 0
        self.ignore_ranges_from = ignore_ranges_from
        self.body_skew = body_skew

    @property
    def served(self):
        return sum(body.bytes_read for body in self.bodies)

    def head_object(self, **kwargs):
        self.head_calls += 1
        return {"ContentLength": len(self.blob)}

    def _answer(self, start, end, ranged):
        data = self.blob[start: end + 1]
        data = data[: len(data) + self.body_skew] if self.body_skew < 0 else data + bytes(self.body_skew)
        body = _CountingBody(data)
        self.bodies.append(body)
        response = {"Body": body, "ContentLength": end - start + 1}
        if ranged:
            response["ContentRange"] = f"bytes {start}-{end}/{len(self.blob)}"
        return response

    def get_object(self, Bucket=None, Key=None, Range=None):  # boto3 casing
        self.ranges.append(Range)
        size = len(self.blob)
        ignored = self.ignore_ranges_from is not None and len(self.ranges) >= self.ignore_ranges_from
        first, last = Range.split("=", 1)[1].split("-")
        if ignored or (first and last and int(first) > int(last)):
            return self._answer(0, size - 1, ranged=False)
        if size == 0:
            raise _FakeClientError("InvalidRange")
        if not first:
            return self._answer(max(0, size - int(last)), size - 1, ranged=True)
        return self._answer(int(first), min(int(last), size - 1), ranged=True)


#: A Parquet file whose footer polars 1.44 PANICS on — a pyo3 ``PanicException``, which is a
#: ``BaseException`` and escapes ``except Exception`` — found by fuzzing footers. Kept as bytes
#: because it is one random mutation of a polars-written file and nothing smaller reproduces it.
PANICKING_PARQUET = pathlib.Path(__file__).with_name("test_panicking_footer.parquet")


def _served_by(blob, **kwargs):
    fake = RangedS3(blob, **kwargs)
    clients._s3 = fake
    return fake


def _declared_footer(blob):
    return struct.unpack("<I", blob[-8:-4])[0]


def _parquet_of_every_shape():
    """A Parquet file over 2 MB, in many row groups, holding the dtypes a probe must carry whole."""
    import polars as pl

    rows = 400_000
    frame = pl.DataFrame({
        "id": pl.Series(range(rows), dtype=pl.Int64),
        "label": pl.Series([f"row-{i}" for i in range(rows)]),
        "at": pl.Series([datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC) + datetime.timedelta(seconds=i) for i in range(rows)]),
        "amount": pl.Series([decimal.Decimal(i % 10_000) / 100 for i in range(rows)], dtype=pl.Decimal(10, 2)),
        "tags": pl.Series([[i, i + 1] for i in range(rows)], dtype=pl.List(pl.Int64)),
        "where": pl.Series([{"x": i, "y": f"y{i}"} for i in range(rows)]),
    })
    blob = io.BytesIO()
    frame.write_parquet(blob, row_group_size=20_000)
    return blob.getvalue()


def test_a_parquet_probe_reads_the_footer_alone_and_polars_gets_the_whole_schema():
    """The property the probe exists for, on whichever polars is installed: the schema is the
    file's, and what was read is the trailer and the footer, however large the object is."""
    import polars as pl

    blob = _parquet_of_every_shape()
    assert len(blob) >= 2_000_000, "the fixture must dwarf its own footer"
    fake = _served_by(blob)

    schema = pl.read_parquet_schema(bounded_read.read_parquet_footer("bkt", "k"))

    assert schema == pl.read_parquet_schema(io.BytesIO(blob))
    assert fake.served <= _declared_footer(blob) + 8, f"read {fake.served} of {len(blob)} bytes"
    assert fake.head_calls == 0 and len(fake.ranges) == 2


def test_a_throttled_ranged_get_is_transient():
    class _Throttled(RangedS3):
        def get_object(self, **kwargs):
            raise _FakeClientError("SlowDown")

    clients._s3 = _Throttled(b"PAR1" * 8)
    with pytest.raises(TransientError):
        bounded_read.read_parquet_footer("bkt", "k")


def test_a_footer_over_the_probe_bound_is_refused_before_it_is_fetched():
    declared = bounded_read.DEFAULT_PROBE_MAX_BYTES + 1
    blob = b"PAR1" + bytes(declared) + struct.pack("<I", declared) + b"PAR1"
    fake = _served_by(blob)

    with pytest.raises(ParquetTrailerError, match=r"over the .*probe bound"):
        bounded_read.read_parquet_footer("bkt", "k")

    assert (len(fake.ranges), fake.served) == (1, 8), "only the trailer may be fetched"


@pytest.mark.parametrize("blob", [b"", b"PAR1!"], ids=["empty", "five-bytes"])
def test_an_object_too_short_to_be_parquet_is_refused_as_too_short(blob):
    fake = _served_by(blob)

    with pytest.raises(ParquetTrailerError, match="too short"):
        bounded_read.read_parquet_footer("bkt", "k")

    assert fake.served <= len(blob)


def test_a_zero_length_footer_is_refused_without_a_second_request():
    """Its range would be inverted, and S3 answers an inverted range with the whole object."""
    fake = _served_by(b"PAR1" + bytes(64) + struct.pack("<I", 0) + b"PAR1")

    with pytest.raises(ParquetTrailerError, match="zero bytes"):
        bounded_read.read_parquet_footer("bkt", "k")

    assert len(fake.ranges) == 1


@pytest.mark.parametrize(("ignored_from", "trailer_read"), [(1, 0), (2, 8)], ids=["trailer", "footer"])
def test_a_response_that_ignored_its_range_is_refused_unread(ignored_from, trailer_read):
    """The one guard whose failure is silent: trust the body of a whole-object answer and a large
    source is pulled whole into a function sized for a footer, with every schema still right."""
    blob = _parquet_of_every_shape()
    fake = _served_by(blob, ignore_ranges_from=ignored_from)

    with pytest.raises(ParquetTrailerError, match="answered a"):
        bounded_read.read_parquet_footer("bkt", "k")

    assert fake.served == trailer_read, f"read {fake.served} bytes of a whole-object answer"


def test_a_footer_exactly_at_the_probe_bound_is_read():
    """The other side of the bound: a footer that fills it is the largest the probe serves, and
    what is read is still the footer and the trailer alone."""
    declared = bounded_read.DEFAULT_PROBE_MAX_BYTES
    fake = _served_by(b"PAR1" + bytes(declared) + struct.pack("<I", declared) + b"PAR1")

    framed = bounded_read.read_parquet_footer("bkt", "k")

    assert len(framed.getvalue()) == declared + 12
    assert fake.served == declared + 8


@pytest.mark.parametrize(("skew", "outcome"), [(-1, "refused"), (1_000_000, "read")], ids=["short", "long"])
def test_a_body_that_is_not_its_declared_length_is_never_read_past_it(skew, outcome):
    """A body short of what its response declared is refused rather than framed as a footer, and
    one longer is read only as far as the declared span — the read is capped, not trusted."""
    import polars as pl

    blob = _parquet_of_every_shape()
    fake = _served_by(blob, body_skew=skew)

    if outcome == "refused":
        with pytest.raises(ParquetTrailerError, match="S3 sent"):
            bounded_read.read_parquet_footer("bkt", "k")
    else:
        schema = pl.read_parquet_schema(bounded_read.read_parquet_footer("bkt", "k"))
        assert schema == pl.read_parquet_schema(io.BytesIO(blob))

    assert fake.served <= _declared_footer(blob) + 8
