"""Bounded object reads for polars schema probes, without polars' cloud reader.

**Why this module exists.** Every control plane that infers a schema wants the same
thing: the first few bytes of an object, never the whole object (a source file can be
hundreds of GB and a Lambda has no disk for it). The obvious way — point polars at an
``s3://`` URI and let its ``object_store`` cloud reader fetch only the byte ranges the
scan needs — **does not work in Lambda**. It fails with ``failed to allocate {filesize}
bytes to download uri = s3://…``: object_store gives up on ranged access and tries to
download the entire object, even when the role's credentials are handed to it explicitly
via ``storage_options``. boto3 in the very same invocation authenticates and reads fine.

So the working pattern, proven live for data-quality (PR #242) and ported here after the
identical failure hit table-builder on a real user's 31 MiB CSV: fetch a **bounded head**
with boto3 and hand polars an in-memory buffer, which polars reads without touching
object_store. The no-full-download property the ``s3://`` scan was chosen for is kept —
we stop reading after ``max_lines`` newlines or ``max_bytes``, whichever comes first, and
abandon the rest of the body.

That covers the formats whose schema lives at the START of the file: a CSV header is line
1, and JSON type inference samples the first N lines. **Parquet keeps its schema in a
footer at the END**, which a head read cannot reach — so it gets ``S3RangeReader``, a
file-like object that serves ``read``/``seek`` from boto3 ranged GETs. Handed to
``polars.read_parquet_schema``, that fetches only the footer region: measured at 64 KiB
and 4 GETs for both a 0.3 MB and a 25 MB file, i.e. bounded by metadata size, not object
size. It must be ``read_parquet_schema`` — ``scan_parquet`` over a Python file object
slurps the WHOLE object in a single ``read()`` (measured on polars 1.12.0), so a lazy
reader would buy nothing there.

**Nothing in this codebase uses object_store any more**, which is the point: the one
reader that does not work here is no longer on any path, and no call site depends on
credentials being threaded into it.

``stream_gzip_head`` / ``read_gzip_head`` do the same job for a gzipped object, which
cannot be range-read at all, and carry the compression-bomb bound that a plain head read
does not need. The bounds are parameters: a caller with documented limits of its own
(data-quality's FR-005) passes them in rather than inheriting these defaults.
"""

import io
import zlib

from . import clients, errors

# Read enough lines for a JSON sample plus its header line. This bounds COST, not
# correctness: the loop stops at a CHUNK boundary, so the head overshoots by up to
# _CHUNK_BYTES — thousands of ordinary rows — and no realistic object distinguishes a
# 1-line bound from this one. max_bytes is the bound that constrains memory.
DEFAULT_PROBE_LINES = 1001

# Hard ceiling so one pathologically long line can't grow the buffer without limit.
DEFAULT_PROBE_MAX_BYTES = 32 * 1024 * 1024  # 32 MiB

_CHUNK_BYTES = 256 * 1024

# Compressed bytes pulled from S3 before a gzip stream is abandoned.
DEFAULT_GZIP_MAX_COMPRESSED_BYTES = 8 * 1024 * 1024  # 8 MiB

# Decompressed bytes held in memory — the bound that actually protects the function
# (see stream_gzip_head).
DEFAULT_GZIP_MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024  # 32 MiB

# zlib wbits for a gzip (not raw-deflate) stream.
_GZIP_WBITS = 16 + zlib.MAX_WBITS


class S3RangeReader(io.RawIOBase):
    """A seekable, read-only file object backed by boto3 ranged GETs.

    Exists for Parquet, whose schema is a footer at the END of the object: a head read
    cannot reach it, and object_store cannot fetch it here (module doc). Hand this to
    ``polars.read_parquet_schema`` and polars seeks to the tail and reads only the footer
    region — a handful of small GETs, independent of how large the object is.

    **Use ``read_parquet_schema``, not ``scan_parquet``.** Given a Python file object,
    ``scan_parquet`` issues ONE ``read()`` for the entire object (measured on polars
    1.12.0), which would pull a 250 GB source into a 1 GB Lambda — the exact failure this
    module exists to avoid. ``read_parquet_schema`` is the one that seeks.

    Each ``readinto`` is one ranged GET; there is no read-ahead cache, because the footer
    read is a few calls and a cache would only add memory the probe does not need.
    """

    def __init__(self, bucket: str, key: str, size: int | None = None):
        self._bucket = bucket
        self._key = key
        self._size = size
        self._pos = 0

    @property
    def size(self) -> int:
        """The object's length, fetched once (needed to resolve SEEK_END and clamp ranges)."""
        if self._size is None:
            try:
                self._size = clients.s3().head_object(Bucket=self._bucket, Key=self._key)[
                    "ContentLength"
                ]
            except Exception as err:  # retryable faults mapped; the rest propagate
                errors.raise_if_transient(err, f"head {self._bucket}/{self._key}")
                raise
        return self._size

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
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
        want = len(buffer)
        if want == 0 or self._pos >= self.size:
            return 0
        # Range is INCLUSIVE at both ends, and clamped to the object so a read past EOF
        # returns the tail rather than an InvalidRange error.
        end = min(self._pos + want, self.size) - 1
        try:
            body = clients.s3().get_object(
                Bucket=self._bucket, Key=self._key, Range=f"bytes={self._pos}-{end}"
            )["Body"]
        except Exception as err:  # retryable faults mapped; the rest propagate
            errors.raise_if_transient(err, f"get {self._bucket}/{self._key}")
            raise
        try:
            data = body.read()
        finally:
            body.close()
        buffer[: len(data)] = data
        self._pos += len(data)
        return len(data)

    def readall(self) -> bytes:
        """Read to EOF. Present for file-object completeness; the footer probe never calls it."""
        out = bytearray()
        while True:
            chunk = bytearray(_CHUNK_BYTES)
            count = self.readinto(chunk)
            if not count:
                return bytes(out)
            out += chunk[:count]


def read_head(
    bucket: str,
    key: str,
    max_lines: int = DEFAULT_PROBE_LINES,
    max_bytes: int = DEFAULT_PROBE_MAX_BYTES,
) -> bytes:
    """Return the head of a line-delimited object, trimmed to whole lines.

    Reading stops at the first chunk boundary at or past ``max_lines`` newlines or
    ``max_bytes``, so the result can overshoot by part of a chunk — these are bounds that
    keep the read small, not an exact line count. The tail after the last newline is then
    dropped: it is a partial record, and handing polars a truncated final row would
    produce a phantom column or a parse error. An object with no newline at all is
    returned whole (it is already within the bounds).

    A retryable S3 fault is raised as ``TransientError`` so the caller's Step Function
    Retry re-runs the verb; callers MUST let that propagate rather than terminalizing it
    as an unreadable file.
    """
    try:
        body = clients.s3().get_object(Bucket=bucket, Key=key)["Body"]
    except Exception as err:  # retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise
    out = bytearray()
    try:
        for chunk in body.iter_chunks(_CHUNK_BYTES):
            out += chunk
            if out.count(b"\n") >= max_lines or len(out) >= max_bytes:
                break
    finally:
        body.close()  # abandon the rest of the object; do not drain it
    return _whole_lines(out)


def _whole_lines(out: bytearray) -> bytes:
    """Drop everything after the last newline (see read_head)."""
    end = out.rfind(b"\n")
    return bytes(out[: end + 1]) if end != -1 else bytes(out)


def stream_gzip_head(
    bucket: str,
    key: str,
    max_lines: int = DEFAULT_PROBE_LINES,
    max_compressed_bytes: int = DEFAULT_GZIP_MAX_COMPRESSED_BYTES,
    max_decompressed_bytes: int = DEFAULT_GZIP_MAX_DECOMPRESSED_BYTES,
) -> bytearray:
    """Stream a gzip object from byte 0 and return the bounded, DECOMPRESSED head.

    A ranged read is impossible here: gzip is not seekable, so no byte range yields the
    header. The only way in is to stream from byte 0 and decompress until the
    header/sample is in hand — then ABANDON the stream, which is what keeps this bounded
    on a 1 GiB .gz. Stops at the first of: enough lines, enough COMPRESSED input consumed,
    or enough DECOMPRESSED output held.

    Returns the untrimmed buffer (``read_gzip_head`` trims it) so the buffer that would
    OOM the function is directly assertable. The trimmed result is not: it drops
    everything after the last newline, so on a compression bomb (one newline, then
    gigabytes) it is 15 bytes however large this buffer grew — a test asserting on that
    passes whether or not any bound exists.
    """
    try:
        body = clients.s3().get_object(Bucket=bucket, Key=key)["Body"]
    except Exception as err:  # retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise
    decompressor = zlib.decompressobj(_GZIP_WBITS)
    out = bytearray()
    consumed = 0
    try:
        for chunk in body.iter_chunks(_CHUNK_BYTES):
            consumed += len(chunk)
            # max_length caps THIS call's output, and is the guard that matters: checking
            # len(out) after an unbounded decompress() is too late, because the allocation
            # that kills the function already happened inside the call. One 256 KiB chunk
            # of deflate can expand to ~264 MB.
            headroom = max_decompressed_bytes - len(out)
            out += decompressor.decompress(chunk, headroom)
            if (
                out.count(b"\n") >= max_lines
                or consumed >= max_compressed_bytes
                or len(out) >= max_decompressed_bytes
            ):
                break
    finally:
        body.close()  # abandon the rest of the object; do not drain it
    return out


def read_gzip_head(
    bucket: str,
    key: str,
    max_lines: int = DEFAULT_PROBE_LINES,
    max_compressed_bytes: int = DEFAULT_GZIP_MAX_COMPRESSED_BYTES,
    max_decompressed_bytes: int = DEFAULT_GZIP_MAX_DECOMPRESSED_BYTES,
) -> bytes:
    """The bounded gzip head of ``key``, trimmed to whole lines."""
    return _whole_lines(
        stream_gzip_head(bucket, key, max_lines, max_compressed_bytes, max_decompressed_bytes)
    )
