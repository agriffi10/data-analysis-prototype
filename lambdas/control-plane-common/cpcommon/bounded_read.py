"""Bounded object reads for polars schema probes, without polars' cloud reader.

Every control plane that infers a schema wants the first few bytes of an object, never the
whole object. Pointing polars at an ``s3://`` URI and letting object_store fetch byte ranges
does not work in Lambda — it gives up on ranged access and tries to download the entire
object. So a bounded head is fetched with boto3 and handed to polars as an in-memory buffer.
Parquet keeps its schema in a footer that a head read cannot reach, so it gets
``S3RangeReader`` instead. Nothing in this codebase uses object_store any more. Full
reasoning and measurements: ``docs/lambda-rationale.md``.

Attributes:
  DEFAULT_PROBE_LINES: Enough lines for a JSON sample plus a header. This bounds cost, not
    correctness — the loop stops at a chunk boundary, so the head overshoots by up to a
    chunk, and no realistic object distinguishes a 1-line bound from this one.
  DEFAULT_PROBE_MAX_BYTES: Hard ceiling so one pathologically long line cannot grow the
    buffer without limit. This is the bound that constrains memory.
  DEFAULT_GZIP_MAX_COMPRESSED_BYTES: Compressed bytes pulled from S3 before a gzip stream
    is abandoned.
  DEFAULT_GZIP_MAX_DECOMPRESSED_BYTES: Decompressed bytes held in memory — the bound that
    actually protects the function.
  _CHUNK_BYTES: Bytes pulled from a stream at a time, and the granularity every bound above is
    actually enforced at — a read stops at the first chunk boundary past its limit.
  _GZIP_WBITS: zlib window bits for a gzip rather than raw-deflate stream.
"""

import io
import zlib

from . import clients, errors

DEFAULT_PROBE_LINES = 1001

DEFAULT_PROBE_MAX_BYTES = 32 * 1024 * 1024

_CHUNK_BYTES = 256 * 1024

DEFAULT_GZIP_MAX_COMPRESSED_BYTES = 8 * 1024 * 1024

DEFAULT_GZIP_MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024

_GZIP_WBITS = 16 + zlib.MAX_WBITS


class S3RangeReader(io.RawIOBase):
    """A seekable, read-only file object backed by boto3 ranged GETs.

    Exists for Parquet, whose schema is a footer at the end of the object: a head read
    cannot reach it, and object_store cannot fetch it here. Handed to
    ``polars.read_parquet_schema``, polars seeks to the tail and reads only the footer
    region — a handful of small GETs, independent of how large the object is.

    Use ``read_parquet_schema``, never ``scan_parquet``: given a Python file object,
    ``scan_parquet`` issues one read for the entire object, which would pull a 250 GB source
    into a 1 GB Lambda — the exact failure this module exists to avoid.

    Each read is one ranged GET. There is no read-ahead cache, because the footer read is a
    few calls and a cache would only add memory the probe does not need.
    """

    def __init__(self, bucket: str, key: str, size: int | None = None):
        """Positions a reader at byte zero of an object.

        Args:
          bucket: The object's bucket.
          key: The object key.
          size: Known content length, if the caller already has it; otherwise fetched
            lazily on first use.

        Returns:
          None.

        Raises:
          None.
        """
        self._bucket = bucket
        self._key = key
        self._size = size
        self._pos = 0

    @property
    def size(self) -> int:
        """Returns the object's length, fetching it once via HeadObject if not supplied.

        Needed to resolve SEEK_END and to clamp ranges.

        Args:
          None.

        Returns:
          The content length in bytes.

        Raises:
          TransientError: On a retryable S3 fault.
          ClientError: Any other S3 fault propagates.
        """
        if self._size is None:
            try:
                self._size = clients.s3().head_object(Bucket=self._bucket, Key=self._key)[
                    "ContentLength"
                ]
            except Exception as err:
                errors.raise_if_transient(err, f"head {self._bucket}/{self._key}")
                raise
        return self._size

    def readable(self) -> bool:
        """Reports that this stream supports reading.

        Args:
          None.

        Returns:
          True, always.

        Raises:
          None.
        """
        return True

    def seekable(self) -> bool:
        """Reports that this stream supports seeking.

        Args:
          None.

        Returns:
          True, always.

        Raises:
          None.
        """
        return True

    def tell(self) -> int:
        """Returns the current read position.

        Args:
          None.

        Returns:
          The zero-based byte offset.

        Raises:
          None.
        """
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        """Moves the read position, clamping at byte zero.

        Args:
          offset: Byte offset relative to ``whence``.
          whence: One of ``io.SEEK_SET``, ``io.SEEK_CUR`` or ``io.SEEK_END``.

        Returns:
          The new position.

        Raises:
          ValueError: On an unrecognised ``whence``.
          TransientError: On a retryable S3 fault while resolving the size for SEEK_END.
        """
        if whence == io.SEEK_SET:
            base = 0
        elif whence == io.SEEK_CUR:
            base = self._pos
        elif whence == io.SEEK_END:
            base = self.size
        else:
            raise ValueError(f"invalid whence {whence!r}")
        self._pos = max(0, base + offset)
        return self._pos

    def readinto(self, buffer) -> int:
        """Fills a buffer from one ranged GET and advances the position.

        The range is inclusive at both ends and clamped to the object, so a read past EOF
        returns the tail rather than an InvalidRange error.

        Args:
          buffer: A writable bytes-like object to fill.

        Returns:
          The number of bytes written, zero at EOF or for a zero-length buffer.

        Raises:
          TransientError: On a retryable S3 fault.
          ClientError: Any other S3 fault propagates.
        """
        want = len(buffer)
        if want == 0 or self._pos >= self.size:
            return 0
        end = min(self._pos + want, self.size) - 1
        try:
            body = clients.s3().get_object(
                Bucket=self._bucket, Key=self._key, Range=f"bytes={self._pos}-{end}"
            )["Body"]
        except Exception as err:
            errors.raise_if_transient(err, f"get {self._bucket}/{self._key}")
            raise
        try:
            data = body.read()
        finally:
            body.close()
        buffer[: len(data)] = data
        self._pos += len(data)
        return len(data)


def read_head(
    bucket: str,
    key: str,
    max_lines: int = DEFAULT_PROBE_LINES,
    max_bytes: int = DEFAULT_PROBE_MAX_BYTES,
) -> bytes:
    """Reads the head of a line-delimited object and trims it to whole lines.

    Reading stops at the first chunk boundary at or past either bound, so the result can
    overshoot by part of a chunk — these keep the read small rather than giving an exact line
    count. The tail after the last newline is dropped, because a truncated final row would
    produce a phantom column or a parse error. The rest of the body is abandoned rather than
    drained. An object with no newline at all is returned whole, already within the bounds.

    Args:
      bucket: The object's bucket.
      key: The object key.
      max_lines: Stop once this many newlines have been seen.
      max_bytes: Stop once this many bytes have been buffered.

    Returns:
      The bounded head, ending at a newline where the object has one.

    Raises:
      TransientError: On a retryable S3 fault. Callers must let it propagate so the Step
        Function's Retry re-runs the verb, rather than terminalizing it as an unreadable
        file.
      ClientError: Any other S3 fault propagates.
    """
    try:
        body = clients.s3().get_object(Bucket=bucket, Key=key)["Body"]
    except Exception as err:
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise
    out = bytearray()
    try:
        for chunk in body.iter_chunks(_CHUNK_BYTES):
            out += chunk
            if out.count(b"\n") >= max_lines or len(out) >= max_bytes:
                break
    finally:
        body.close()
    return _whole_lines(out)


def _whole_lines(out: bytearray) -> bytes:
    """Drops everything after the last newline in a buffer.

    Args:
      out: The buffer to trim.

    Returns:
      The buffer up to and including its last newline, or unchanged if it has none.

    Raises:
      None.
    """
    end = out.rfind(b"\n")
    return bytes(out[: end + 1]) if end != -1 else bytes(out)


def stream_gzip_head(
    bucket: str,
    key: str,
    max_lines: int = DEFAULT_PROBE_LINES,
    max_compressed_bytes: int = DEFAULT_GZIP_MAX_COMPRESSED_BYTES,
    max_decompressed_bytes: int = DEFAULT_GZIP_MAX_DECOMPRESSED_BYTES,
) -> bytearray:
    """Streams a gzip object from byte zero and returns the bounded decompressed head.

    A ranged read is impossible here — gzip is not seekable, so no byte range yields the
    header. The only way in is to stream from byte zero and decompress until the sample is
    in hand, then abandon the stream, which is what keeps this bounded on a 1 GiB archive.
    Each decompress call caps its own output, which is the guard that matters: checking the
    buffer length after an unbounded decompress is too late, because the allocation that
    kills the function already happened inside the call, and one 256 KiB chunk of deflate can
    expand to roughly 264 MB.

    The buffer is returned untrimmed so the thing that would exhaust memory is directly
    assertable. The trimmed result is not: it drops everything after the last newline, so on
    a compression bomb of one newline followed by gigabytes it is 15 bytes however large the
    buffer grew, and a test asserting on that passes whether or not any bound exists.

    Args:
      bucket: The object's bucket.
      key: The object key.
      max_lines: Stop once this many newlines have been decompressed.
      max_compressed_bytes: Stop once this much compressed input has been consumed.
      max_decompressed_bytes: Stop once this much output is held in memory.

    Returns:
      The untrimmed decompressed head.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any other S3 fault propagates.
      zlib.error: If the object is not a valid gzip stream.
    """
    try:
        body = clients.s3().get_object(Bucket=bucket, Key=key)["Body"]
    except Exception as err:
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise
    decompressor = zlib.decompressobj(_GZIP_WBITS)
    out = bytearray()
    consumed = 0
    try:
        for chunk in body.iter_chunks(_CHUNK_BYTES):
            consumed += len(chunk)
            headroom = max_decompressed_bytes - len(out)
            out += decompressor.decompress(chunk, headroom)
            if (
                out.count(b"\n") >= max_lines
                or consumed >= max_compressed_bytes
                or len(out) >= max_decompressed_bytes
            ):
                break
    finally:
        body.close()
    return out


def read_gzip_head(
    bucket: str,
    key: str,
    max_lines: int = DEFAULT_PROBE_LINES,
    max_compressed_bytes: int = DEFAULT_GZIP_MAX_COMPRESSED_BYTES,
    max_decompressed_bytes: int = DEFAULT_GZIP_MAX_DECOMPRESSED_BYTES,
) -> bytes:
    """Returns the bounded gzip head of an object, trimmed to whole lines.

    Args:
      bucket: The object's bucket.
      key: The object key.
      max_lines: Stop once this many newlines have been decompressed.
      max_compressed_bytes: Stop once this much compressed input has been consumed.
      max_decompressed_bytes: Stop once this much output is held in memory.

    Returns:
      The decompressed head, ending at a newline where there is one.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any other S3 fault propagates.
      zlib.error: If the object is not a valid gzip stream.
    """
    return _whole_lines(
        stream_gzip_head(bucket, key, max_lines, max_compressed_bytes, max_decompressed_bytes)
    )
