"""Tests for cpcommon.bounded_read.

Stubs the S3 client, never polars: the point of this module is the BYTES handed to
polars and the fact that a big object is not drained to get them. The fake body counts
what was actually read, so "bounded" is asserted by observation rather than assumed.

Runnable under pytest or directly: python3 test_bounded_read.py.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon import bounded_read, clients  # noqa: E402
from cpcommon.errors import TransientError  # noqa: E402


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


def test_storage_options_carries_region_and_temporary_credentials():
    """object_store rejects role creds without the session token, so all four must be there."""
    saved = {k: os.environ.get(k) for k in
             ("AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")}
    os.environ.update({
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "AKIA_T",
        "AWS_SECRET_ACCESS_KEY": "secret_t",
        "AWS_SESSION_TOKEN": "token_t",
    })
    try:
        assert bounded_read.storage_options() == {
            "aws_region": "us-east-1",
            "aws_access_key_id": "AKIA_T",
            "aws_secret_access_key": "secret_t",
            "aws_session_token": "token_t",
        }
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_storage_options_omits_vars_that_are_absent():
    saved = {k: os.environ.get(k) for k in
             ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_ACCESS_KEY_ID",
              "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")}
    for key in saved:
        os.environ.pop(key, None)
    try:
        assert bounded_read.storage_options() == {}
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value


def test_object_uri():
    assert bounded_read.object_uri("bkt", "a/b/c.csv") == "s3://bkt/a/b/c.csv"


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
