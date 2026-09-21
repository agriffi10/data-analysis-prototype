"""Bounded object reads for polars schema probes, without polars' cloud reader.

Every control plane that infers a schema wants the first few bytes of an object, never the
whole object. Pointing polars at an ``s3://`` URI and letting object_store fetch byte ranges
does not work in Lambda — it gives up on ranged access and tries to download the entire
object. So a bounded head is fetched with boto3 and handed to polars as an in-memory buffer.
Parquet keeps its schema in a footer that a head read cannot reach, so ``read_parquet_footer``
fetches the footer alone and hands polars that, framed as a file. Nothing in this codebase uses
object_store any more. Full reasoning and measurements: ``lambdas/info/shared-layer.md``.

Attributes:
  DEFAULT_PROBE_LINES: Enough lines for a JSON sample plus a header. This bounds cost, not
    correctness — the loop stops at a chunk boundary, so the head overshoots by up to a
    chunk, and no realistic object distinguishes a 1-line bound from this one.
  DEFAULT_PROBE_MAX_BYTES: Hard ceiling so one pathologically long line cannot grow the
    buffer without limit. This is the bound that constrains memory, and a Parquet footer is held
    to it too.
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

from . import clients, errors, parquet_trailer

DEFAULT_PROBE_LINES = 1001

DEFAULT_PROBE_MAX_BYTES = 32 * 1024 * 1024

_CHUNK_BYTES = 256 * 1024

DEFAULT_GZIP_MAX_COMPRESSED_BYTES = 8 * 1024 * 1024

DEFAULT_GZIP_MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024

_GZIP_WBITS = 16 + zlib.MAX_WBITS


def _ranged_get(bucket: str, key: str, span: str):
    """Issues one ranged GetObject, mapping a retryable fault to TransientError.

    Args:
      bucket: The object's bucket.
      key: The object key.
      span: The ``Range`` header's value.

    Returns:
      The GetObject response.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any other S3 fault propagates.
    """
    try:
        return clients.s3().get_object(Bucket=bucket, Key=key, Range=span)
    except Exception as err:
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise


def _read_exactly(response, want: int) -> bytes:
    """Reads a ranged response's body, refusing one that is not the span that was asked for.

    The declared length is checked BEFORE the body is read, and the read is capped at the span
    even so. Both matter because S3 answers a range it cannot parse by ignoring it and sending the
    whole object with a 200, and a reader that trusted the body would pull a large source whole
    into a function sized for a footer.

    Args:
      response: A GetObject response.
      want: The bytes the range asked for.

    Returns:
      Exactly ``want`` bytes.

    Raises:
      ParquetTrailerError: When the response declares, or yields, a different length.
    """
    body = response["Body"]
    try:
        declared = response.get("ContentLength")
        if declared != want:
            raise parquet_trailer.ParquetTrailerError(
                f"S3 answered a {want}-byte range with {declared} bytes"
            )
        data: bytes = body.read(want)
    finally:
        body.close()
    if len(data) != want:
        raise parquet_trailer.ParquetTrailerError(
            f"S3 sent {len(data)} bytes of a {want}-byte range"
        )
    return data


def _object_size(response) -> int:
    """Reads an object's full length from a ranged response.

    A ranged answer names the full length after the slash in ``ContentRange``. A response without
    one is S3 sending the whole object, whose length is then the body's own.

    Args:
      response: A GetObject response to a ranged request.

    Returns:
      The object's length in bytes.

    Raises:
      ValueError: When a ``ContentRange`` does not end in a numeric total, which both verbs
        refuse as an unreadable file.
    """
    content_range = response.get("ContentRange")
    if content_range:
        return int(content_range.rpartition("/")[2])
    return int(response.get("ContentLength") or 0)


def read_parquet_footer(bucket: str, key: str) -> io.BytesIO:
    """Returns a buffer holding only an object's Parquet footer, framed as a file polars can read.

    Two ranged GETs and no HEAD: the suffix range ``bytes=-8`` returns the trailer and, in its
    ``ContentRange``, the object's size; ``parquet_trailer.footer_span`` locates the footer; the
    second GET fetches exactly that. The buffer is ``PAR1``, the footer, the trailer — a file of
    one footer and no data, which ``polars.read_parquet_schema`` reads as the full file's schema on
    every polars this fleet has pinned. Handing polars a file object over S3 instead no longer
    bounds anything, because a newer polars reads such an object whole.

    An empty object has no suffix to return, and S3 refuses the range as ``InvalidRange``; that is
    refused here as the too-short object it is.

    Args:
      bucket: The object's bucket.
      key: The object key.

    Returns:
      The framed footer, positioned at byte zero.

    Raises:
      ParquetTrailerError: For an object too short to be Parquet, a trailer that does not locate a
        footer the object holds, a footer longer than ``DEFAULT_PROBE_MAX_BYTES``, or a response
        that is not the range asked for.
      TransientError: On a retryable S3 fault.
      ClientError: Any other S3 fault propagates.
    """
    trailer_span = f"bytes=-{parquet_trailer.TRAILER_BYTES}"
    try:
        tail = _ranged_get(bucket, key, trailer_span)
    except Exception as err:
        if errors.error_code(err) == "InvalidRange":
            raise parquet_trailer.ParquetTrailerError(
                "an object of 0 bytes is too short to be a Parquet file"
            ) from err
        raise
    size = _object_size(tail)
    trailer = _read_exactly(tail, min(size, parquet_trailer.TRAILER_BYTES))
    offset, length = parquet_trailer.footer_span(size, trailer)
    if length > DEFAULT_PROBE_MAX_BYTES:
        raise parquet_trailer.ParquetTrailerError(
            f"the object declares a {length}-byte footer, over the {DEFAULT_PROBE_MAX_BYTES}-byte "
            "probe bound"
        )
    footer = _read_exactly(
        _ranged_get(bucket, key, f"bytes={offset}-{offset + length - 1}"), length
    )
    return io.BytesIO(parquet_trailer.MAGIC + footer + trailer)


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
