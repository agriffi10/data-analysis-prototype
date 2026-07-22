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
"""

import os

from . import clients, errors

# Read enough lines for a JSON sample plus its header line. A CSV needs only line 1, but
# both formats share the bound deliberately: a quoted CSV header can itself contain a
# newline, and a one-line read would truncate it mid-column-name.
DEFAULT_PROBE_LINES = 1001

# Hard ceiling so one pathologically long line can't grow the buffer without limit.
DEFAULT_PROBE_MAX_BYTES = 32 * 1024 * 1024  # 32 MiB

_CHUNK_BYTES = 256 * 1024


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
    end = out.rfind(b"\n")
    return bytes(out[: end + 1]) if end != -1 else bytes(out)
