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

This works for the formats whose schema lives at the START of the file: a CSV header is
line 1, and JSON type inference samples the first N lines. **Parquet is the exception** —
its schema lives in a footer at the END — so it still goes through object_store over the
URI, with ``storage_options()`` credentials. That path is not yet proven live; if it
fails the same way, the fix is a boto3 footer read (last-N-bytes), not more credentials.

``stream_gzip_head`` / ``read_gzip_head`` do the same job for a gzipped object, which
cannot be range-read at all, and carry the compression-bomb bound that a plain head read
does not need. The bounds are parameters: a caller with documented limits of its own
(data-quality's FR-005) passes them in rather than inheriting these defaults.
"""

import os
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


def object_uri(bucket: str, key: str) -> str:
    """The ``s3://`` URI for polars' cloud reader (Parquet footers only — see module doc)."""
    return f"s3://{bucket}/{key}"


def storage_options() -> dict:
    """Credentials for polars' object_store cloud reader, from the Lambda role's env.

    polars does NOT reuse the ambient AWS credential chain the way boto3 does: its
    object_store S3 reader needs the role's creds handed in EXPLICITLY, even inside a
    Lambda where boto3 finds them automatically. The runtime injects AWS_ACCESS_KEY_ID /
    AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN (temporary role creds — the session token is
    mandatory or the request is rejected) and AWS_REGION; object_store's config keys are
    the ``aws_*`` forms.
    """
    opts: dict[str, str] = {}
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if region:
        opts["aws_region"] = region
    for env_name, os_key in (
        ("AWS_ACCESS_KEY_ID", "aws_access_key_id"),
        ("AWS_SECRET_ACCESS_KEY", "aws_secret_access_key"),
        ("AWS_SESSION_TOKEN", "aws_session_token"),
    ):
        value = os.environ.get(env_name)
        if value:
            opts[os_key] = value
    return opts


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
    except Exception as err:  # noqa: BLE001 - retryable faults mapped; the rest propagate
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
    except Exception as err:  # noqa: BLE001 - retryable faults mapped; the rest propagate
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
