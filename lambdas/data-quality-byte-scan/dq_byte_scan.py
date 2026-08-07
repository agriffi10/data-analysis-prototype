"""data-quality byte-scan — the one check a SQL engine cannot do.

By the time Athena hands you a row the raw bytes are gone: the SerDe has already decoded and
parsed them. So invalid text encoding — a file exported from a spreadsheet in a Windows codepage,
one of the most common real-world corruptions — is invisible to every other check in this arc.
This verb reads a bounded sample of raw bytes and reports what it finds.

It cannot be exact, and a bigger budget is not the answer: the sources this arc targets are
enormous, the function's ceiling is finite, and Athena cannot see raw bytes at any size. The
honest response is a labelled sample — the figure ships with its coverage percentage and the
report says sampled — because a number that silently means "of the first fraction of a percent"
is worse than no number at all. The budget is per request, never per file, and is divided across
the manifest's files; the arithmetic is in ``docs/lambda-rationale.md``.

Text only. Binary formats and compressed objects are skipped with their reason: a binary format
defines its encoding in the file itself, and a compressed file's raw bytes are compressor output,
so scanning them would measure the compressor rather than the user's text.

The invalid-sequence counting uses a registered decode error handler, because the obvious
implementations are both wrong here. Replacing on decode loses the offsets entirely, and catching
in a loop re-decodes the remaining suffix after every error, which degrades to quadratic on a file
where a large fraction of bytes are invalid — the case this check exists to find — and burns the
timeout on the file it was supposed to diagnose. A registered handler is called once per bad
sequence during a single linear decode, receives the exact byte range, and returns where to
resume. It records into module state because the codecs machinery identifies handlers by name; a
Lambda invocation is single-threaded, and each file's scan resets that state before it starts.

The count is an integer and the offset list is capped, which is not tidiness — retaining an offset
per bad sequence costs tens of bytes each, and a large mis-encoded export holds tens of millions
of them. Avoiding the quadratic CPU path only to exhaust memory on the same file would be the same
bug wearing a different hat.

The service name is the control plane, not the function: one data-quality run is nine
invocations, and they are only one queryable set if they share it. The per-verb identity rides as
the ``verb`` field.

Attributes:
  TEXT_FORMATS: Formats whose bytes are user-authored text. Anything else is skipped.
  SKIP_BINARY: The skip reason for a binary format, worded for the report.
  SKIP_COMPRESSED: The skip reason for a compressed source, worded for the report.
  _MAX_UTF8_LEN: Longest encoded sequence, hence the most trailing bytes that can be a truncated
    character.
  _HANDLER_NAME: The registered decode error handler's name.
  _found: Offsets of the invalid sequences seen in the current file, capped.
  _invalid: How many invalid sequences the current file has produced.
  _base: The absolute offset the current decode buffer starts at.
  _INVALID_RANGE: The error code for a range that no longer exists because the object shrank.
"""

import codecs
import logging

from cpcommon import clients, errors, events, observability
from dqcommon import config, messages, notify
from dqcommon import manifest as manifest_store

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="data-quality")

TEXT_FORMATS = frozenset({"csv", "json"})

SKIP_BINARY = "binary format — encoding is defined by the file format"
SKIP_COMPRESSED = "compressed source — raw bytes are DEFLATE output"

_MAX_UTF8_LEN = 4

_HANDLER_NAME = "dq_byte_scan.count_invalid"
_found: list[int] = []
_invalid = 0
_base = 0


def _record_invalid(err: UnicodeDecodeError):
    """Records one invalid sequence and tells the decoder to carry on past it.

    Args:
      err: The decode error, carrying the offending byte range.

    Returns:
      The replacement character and the offset to resume at.

    Raises:
      None.
    """
    global _invalid
    _invalid += 1
    if len(_found) < config.DQ_OFFSET_SAMPLE:
        _found.append(_base + err.start)
    return ("�", err.end)


codecs.register_error(_HANDLER_NAME, _record_invalid)


def _split_trailing_partial(buf: bytes) -> tuple[bytes, bytes]:
    """Splits a buffer into a decodable part and a held-back truncated final character.

    A read boundary lands mid-character routinely on non-ASCII text. Those bytes are not
    corruption — they are the chunk size showing through — and counting them would put
    invalid-encoding findings in front of a user whose file is perfectly fine, in rough
    proportion to how big the file is. They are held back and prepended to the next chunk.

    Args:
      buf: The bytes read so far in this chunk, plus any carry.

    Returns:
      A ``(decodable, carry)`` tuple.

    Raises:
      None.
    """
    for back in range(1, min(_MAX_UTF8_LEN, len(buf)) + 1):
        byte = buf[-back]
        if byte < 0x80:
            break
        if byte >= 0xC0:
            needed = 2 if byte < 0xE0 else 3 if byte < 0xF0 else 4
            return (buf[:-back], buf[-back:]) if back < needed else (buf, b"")
    return buf, b""


def _decode(buf: bytes, base: int) -> None:
    """Decodes a buffer, recording the absolute offset of every invalid sequence found.

    Args:
      buf: The bytes to decode.
      base: The absolute file offset the buffer starts at.

    Returns:
      None.

    Raises:
      None.
    """
    global _base
    _base = base
    buf.decode("utf-8", errors=_HANDLER_NAME)


_INVALID_RANGE = "InvalidRange"


def _scan_region(bucket: str, key: str, start: int, length: int, at_eof: bool) -> int:
    """Scans one contiguous byte range and returns the bytes actually examined.

    The whole transfer is guarded, not just the request. The bytes move during the chunked read,
    and a mid-stream fault carries no error code and arrives at Step Functions as its own Python
    class name, which the Retry list does not name. One dropped connection across the many
    sequential reads a full budget can span would then fail the request permanently, after all
    three Athena queries have already been paid for. Guarding only the request would map the rarer
    fault and miss the likelier one.

    Bytes left over at the end of the region are a truncated character. At end of file that is
    real corruption — a file cut off mid-character — and is counted; anywhere else it is this
    region's edge, and the rest of the character sits in a part of the file the budget did not
    buy, so counting it would invent a finding.

    Args:
      bucket: The source bucket.
      key: The object key.
      start: The first byte of the range.
      length: How many bytes to read.
      at_eof: Whether this range reaches the end of the object.

    Returns:
      The bytes examined. Invalid-sequence offsets land in the module state; the caller owns
      resetting it.

    Raises:
      TransientError: On a retryable S3 fault. A one-off throttle must not fail a check this far
        in, and the verb is a pure read, so a retry re-runs it safely over the same deterministic
        ranges.
      ClientError: Any other deterministic fault propagates. A range that no longer exists is the
        exception: the object shrank or was replaced since it was listed, and losing the whole
        check over one file that changed would be worse than scanning less of it — the figure is
        already labelled sampled, and the caller marks the file incomplete.
    """
    end = start + length - 1
    pending = b""
    base = start
    examined = 0

    try:
        body = clients.s3().get_object(Bucket=bucket, Key=key, Range=f"bytes={start}-{end}")["Body"]
        for chunk in body.iter_chunks(config.DQ_SCAN_READ_CHUNK_BYTES):
            examined += len(chunk)
            decodable, pending = _split_trailing_partial(pending + chunk)
            _decode(decodable, base)
            base += len(decodable)
    except Exception as err:
        if errors.error_code(err) == _INVALID_RANGE:
            logger.warning("range %s-%s of %s no longer exists — object changed", start, end, key)
            return examined
        errors.raise_if_transient(err, f"get {bucket}/{key} bytes={start}-{end}")
        raise

    if pending and at_eof:
        _decode(pending, base)

    return examined


def _regions(size: int, share: int) -> list[tuple[int, int]]:
    """Plans the ranges to read from one file, spending at most its share.

    A file that fits its share is read as one range, and the caller reports it complete.
    Otherwise a head window comes first, because corruption clusters at the start of a
    badly-exported file — a byte-order mark, a codepage-encoded header, an accented name in the
    first records — then evenly-spread ranged reads over the remainder, so a corruption confined
    to the middle or tail of a large file is still reachable.

    The sample count is an upper bound floored by the minimum sample size, because the request
    count, not just the byte count, is a way to blow the timeout.

    The final sample is not clipped to the end of file, and that is not an oversight: reaching
    that branch means the share is smaller than the file, so each sample is strictly smaller than
    each stride and the last window ends before the end by construction. A clamp here would be
    unreachable code that reads like a guard, and a test pins the invariant instead.

    Args:
      size: The file's size.
      share: The bytes this file may spend.

    Returns:
      A list of ``(start, length)`` ranges.

    Raises:
      None.
    """
    if _fits(size, share):
        return [(0, size)] if size else []

    head = int(share * config.DQ_SCAN_HEAD_FRACTION)
    remainder = share - head
    count = min(config.DQ_SCAN_SAMPLE_COUNT, remainder // config.DQ_SCAN_MIN_SAMPLE_BYTES)
    if not count:
        return [(0, head)] if head else []

    sample = remainder // count
    stride = (size - head) // count
    regions = [(0, head)]
    for index in range(count):
        regions.append((head + index * stride, sample))
    return regions


def _fits(size: int, share: int) -> bool:
    """Reports whether a whole file fits inside its share, so it is read in full.

    One predicate, used by both the planner and the coverage verdict. Duplicating it let a
    single-sided edit report complete coverage over a file the planner had in fact sampled — a
    coverage figure that lies in the safe-sounding direction.

    Args:
      size: The file's size.
      share: The bytes this file may spend.

    Returns:
      True when the file fits.

    Raises:
      None.
    """
    return size <= share


def _scan_file(bucket: str, entry: dict, share: int) -> tuple[int, bool, int, list[int]]:
    """Scans one file within its share.

    A short read, meaning the object changed mid-check, also means the file was not read in full,
    whatever the manifest's size said.

    Args:
      bucket: The source bucket.
      entry: The manifest's entry for this file.
      share: The bytes this file may spend.

    Returns:
      A ``(bytes examined, read in full, invalid count, offsets)`` tuple. The offsets are already
      ascending, because regions are planned and scanned in file order.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any other deterministic fault propagates.
      KeyError: If the entry has no key.
    """
    global _invalid
    key = entry["key"]
    size = entry.get("size") or 0
    examined = 0
    _found.clear()
    _invalid = 0
    for start, length in _regions(size, share):
        examined += _scan_region(bucket, key, start, length, at_eof=start + length >= size)
    return examined, _fits(size, share) and examined >= size, _invalid, list(_found)


@observability.step("scan")
def _scan_all(bucket: str, scannable: list[dict], share: int):
    """Scans every scannable file, as one step.

    The span covers the whole scan and never a file or a region. This verb iterates per file and
    per region within a file, so a step one level down would mint thousands of child spans for one
    invocation — each an SQS message and a line in a day object the sweep rewrites in full.

    Each retained example carries its key. A bare offset is unreadable across a large folder —
    byte four thousand of which file? — and the whole point of keeping examples is that an
    operator can go and look at one.

    Args:
      bucket: The source bucket.
      scannable: The manifest entries that are not compressed.
      share: The bytes each file may spend.

    Returns:
      A ``(bytes examined, invalid count, all read in full, offsets)`` tuple.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any other deterministic fault propagates.
    """
    examined = 0
    invalid = 0
    complete = True
    offsets: list[dict] = []
    for entry in scannable:
        file_examined, in_full, file_invalid, file_offsets = _scan_file(bucket, entry, share)
        examined += file_examined
        invalid += file_invalid
        complete = complete and in_full
        offsets.extend(
            {"key": entry["key"], "offset": offset}
            for offset in file_offsets[: config.DQ_OFFSET_SAMPLE - len(offsets)]
        )
    return examined, invalid, complete, offsets


def _scan(event: dict) -> dict:
    """Divides the budget across the scannable files, scans them, and shapes the figure.

    Compression is per file, because inspect-source enforces one format rather than one codec, so
    a folder can mix plain and compressed objects. The scannable subset is scanned and the rest
    counted as skipped, rather than losing the whole figure to one compressed sibling.

    The division is the whole point: the budget is a total, so a thousand files get a small share
    each and two files get a large one, and the bytes read never exceed the total whatever the
    file count or the file sizes are.

    A skipped file makes the whole figure sampled. Without that clause, one tiny plain file beside
    many large compressed ones reports complete coverage over a folder where most of the data was
    never looked at — the figure reading cleanest exactly where it has seen least.

    Per-file figures are accounted for but not returned. Each file gets its own share and its own
    complete-or-sampled verdict, but a per-file array on the state would exceed the payload limit
    at the object cap, and breaching it raises outside every Catch: the execution would die
    without reaching the notify state and the user would be told nothing at all, on exactly the
    biggest folders. The report's encoding block is aggregate anyway.

    Offsets are positions; the bytes at them are file contents. This is the single highest-risk
    emitter in the plane — the verb's whole purpose is holding a user's raw bytes, and the natural
    debugging instinct is to log the sequence that failed to decode. That sequence is the file. An
    offset and a key are enough to go and look, and they are all that is recorded.

    The module state is not cleared on the way out: each file's scan resets it before starting,
    what survives the last one is at most a capped handful of integers, and clearing it here would
    also erase the only externally observable evidence that the cap does anything — the test
    asserting it would pass against an unbounded list.

    Args:
      event: The task input, carrying the space, manifest key and format.

    Returns:
      The event with the encoding figure attached.

    Raises:
      TerminalError: ``invalid_request`` when a required field is missing.
      TransientError: On a retryable S3 fault.
    """
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    manifest_key = events.require(event, "manifestKey", reason=messages.INVALID_REQUEST)
    fmt = events.require(event, "format", reason=messages.INVALID_REQUEST)

    out = dict(event)

    if fmt not in TEXT_FORMATS:
        out["encoding"] = {"status": "skipped", "reason": SKIP_BINARY}
        logger.info("byte-scan skipped: format=%s", fmt)
        observability.info("scan skipped", reason=SKIP_BINARY, format=fmt, files=0, invalid=0)
        return out

    files = manifest_store.load(bucket, manifest_key).get("files") or []
    scannable = [f for f in files if not config.is_compressed(f["key"])]
    skipped = len(files) - len(scannable)

    if not scannable:
        out["encoding"] = {"status": "skipped", "reason": SKIP_COMPRESSED}
        logger.info("byte-scan skipped: all %d files compressed", skipped)
        observability.info(
            "scan skipped", reason=SKIP_COMPRESSED, format=fmt, files=0, skipped=skipped, invalid=0
        )
        return out

    share = max(config.DQ_SCAN_TOTAL_BYTES // len(scannable), 1)

    examined, invalid, complete, offsets = _scan_all(bucket, scannable, share)

    out["encoding"] = {
        "invalidUtf8Sequences": invalid,
        "sampleOffsets": offsets,
        "bytesExamined": examined,
        "bytesTotal": sum(f.get("size") or 0 for f in scannable),
        "coverage": "complete" if complete and not skipped else "sampled",
        "filesScanned": len(scannable),
        "filesSkipped": skipped,
    }
    logger.info(
        "byte-scan: %d files, %d of %d bytes examined, %d invalid sequences, %d skipped",
        len(scannable),
        examined,
        out["encoding"]["bytesTotal"],
        invalid,
        skipped,
    )
    observability.info(
        "scanned bytes",
        files=len(scannable),
        skipped=skipped,
        bytes=examined,
        bytes_total=out["encoding"]["bytesTotal"],
        invalid=invalid,
        offsets=[o["offset"] for o in offsets],
        offset_keys=sorted({o["key"] for o in offsets}),
        coverage=out["encoding"]["coverage"],
    )
    return out


@observability.traced("byte-scan")
@notify.notifies_on_failure("byte-scan")
def handler(event, context) -> dict:
    """Scans a bounded sample of the source's raw bytes and threads the figure onward.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The task input.
      context: The Lambda context, unused.

    Returns:
      The event with the encoding figure attached.

    Raises:
      TerminalError: ``invalid_request`` when a required field is missing.
      TransientError: On a retryable S3 fault.
    """
    return _scan(event)
