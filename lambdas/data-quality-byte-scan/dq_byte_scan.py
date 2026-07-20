"""data-quality byte-scan — the one check a SQL engine cannot do (SPEC-112 FR-001).

By the time Athena hands you a row the raw bytes are GONE: the serde has already decoded
and parsed them. So invalid UTF-8 — a file exported from Excel in a Windows codepage, one
of the most common real-world corruptions — is INVISIBLE to every other check in this arc.
This verb reads a bounded sample of raw bytes and reports what it finds.

WHY THIS CANNOT BE EXACT, and why a bigger budget is not the answer: the sources this arc
targets run to 250 GB, against a 300-second function, and Athena cannot see raw bytes at
any size. There is no budget that makes this exact. The honest response is a LABELLED
sample — the figure ships with its coverage percentage and the report says "sampled" —
because a number that silently means "of the first 0.8%" is worse than no number at all.

THE BUDGET IS PER REQUEST, NEVER PER FILE. See config.DQ_SCAN_TOTAL_BYTES for the
arithmetic; the short version is that a per-file window of 256 MiB across the 1000 files
DQ_MAX_OBJECTS permits is ~276 GB through one 1024 MB Lambda in 300 s (~920 MB/s, against
a real ~60-100 MB/s). It passes on a three-file fixture and times out on every real folder.
The total is divided across the manifest's files; it must never be re-expressed per file.

TEXT ONLY. Parquet and .gz are skipped with their reason (FR-001): Parquet defines its
encoding in the file format, and a .gz file's raw bytes are DEFLATE output, so scanning
them would measure the compressor rather than the user's text.
"""

import codecs
import logging

from cpcommon import clients, errors, events
from dqcommon import config, manifest as manifest_store, messages

logger = logging.getLogger()
logger.setLevel(logging.INFO)

#: Formats whose bytes are user-authored text. Anything else is skipped (FR-001).
TEXT_FORMATS = frozenset({"csv", "json"})

#: The skip reasons, worded for the report (SPEC-113 renders them verbatim).
SKIP_BINARY = "binary format — encoding is defined by the file format"
SKIP_COMPRESSED = "compressed source — raw bytes are DEFLATE output"

#: Longest UTF-8 sequence, hence the most trailing bytes that can be a truncated character.
_MAX_UTF8_LEN = 4

# ── Counting invalid sequences in ONE decode pass ────────────────────────────
#
# The obvious implementations are both wrong here:
#
#   decode(errors="replace")  loses the offsets entirely, and
#   try/except UnicodeDecodeError in a loop  re-decodes the remaining suffix after every
#   error, which is O(errors x bytes) — a Latin-1 file where a large fraction of bytes are
#   invalid (i.e. THE CASE THIS CHECK EXISTS TO FIND) degrades to quadratic and burns the
#   timeout on the file it was supposed to diagnose.
#
# A registered error handler is called ONCE PER BAD SEQUENCE during a single linear decode,
# receives the exact byte range, and returns where to resume. One pass, offsets kept, no
# quadratic path. The handler records into module state because codecs identifies handlers
# by NAME — a Lambda invocation is single-threaded, and each file's scan resets the state
# before it starts.
#
# THE COUNT IS AN INT AND THE OFFSET LIST IS CAPPED, which is not tidiness — retaining an
# offset per bad sequence is ~42 bytes each, and a 250 MB CP1252 export holds tens of
# millions of them: over a gigabyte in a 1024 MB function. Avoiding the quadratic CPU path
# above only to OOM on the same file would be the same bug wearing a different hat.
_HANDLER_NAME = "dq_byte_scan.count_invalid"
_found: list[int] = []
_invalid = 0
_base = 0


def _record_invalid(err: UnicodeDecodeError):
    """Record one invalid sequence and tell the decoder to carry on past it."""
    global _invalid
    _invalid += 1
    if len(_found) < config.DQ_OFFSET_SAMPLE:
        _found.append(_base + err.start)
    return ("�", err.end)


codecs.register_error(_HANDLER_NAME, _record_invalid)


def _split_trailing_partial(buf: bytes) -> tuple[bytes, bytes]:
    """Split ``buf`` into (decodable, carry), holding back a truncated final character.

    A read boundary lands mid-character routinely on non-ASCII text. Those bytes are NOT
    corruption — they are the chunk size showing through — and counting them would put
    invalid-UTF-8 findings in front of a user whose file is perfectly fine, in rough
    proportion to how big the file is. Held back here and prepended to the next chunk.
    """
    for back in range(1, min(_MAX_UTF8_LEN, len(buf)) + 1):
        byte = buf[-back]
        if byte < 0x80:  # ASCII: complete on its own, nothing outstanding
            break
        if byte >= 0xC0:  # a lead byte — is its sequence complete within buf?
            needed = 2 if byte < 0xE0 else 3 if byte < 0xF0 else 4
            return (buf[:-back], buf[-back:]) if back < needed else (buf, b"")
    return buf, b""


def _decode(buf: bytes, base: int) -> None:
    """Decode ``buf``, appending the absolute offset of every invalid sequence found."""
    global _base
    _base = base
    buf.decode("utf-8", errors=_HANDLER_NAME)


#: A range that no longer exists because the object shrank between states (see _scan_region).
_INVALID_RANGE = "InvalidRange"


def _scan_region(bucket: str, key: str, start: int, length: int, at_eof: bool) -> int:
    """Scan one contiguous byte range, returning the bytes actually examined.

    Invalid-sequence offsets land in the module-level ``_found``; the caller owns resetting
    it.

    THE WHOLE TRANSFER IS INSIDE THE TRY, not just the request. The bytes move during
    ``iter_chunks``, and a mid-stream fault (ReadTimeoutError, IncompleteReadError, a reset
    connection) carries no error code and arrives at Step Functions as its own Python class
    name — which the ByteScan Retry list does not name. One dropped connection across the
    ~1000 sequential reads a 2 GiB budget can span would then fail the request PERMANENTLY,
    after all three Athena queries have already been paid for. Wrapping only the
    ``get_object`` call would map the rarer fault and miss the likelier one.
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
    except Exception as err:  # noqa: BLE001 - retryable faults mapped; the rest propagate
        if errors.error_code(err) == _INVALID_RANGE:
            # The object shrank or was replaced between inspect-source's listing and now,
            # so this range is past its end. Losing the whole check over one file that
            # changed under us would be worse than scanning less of it: the figure is
            # already labelled sampled, and the caller marks the file incomplete.
            logger.warning("range %s-%s of %s no longer exists — object changed", start, end, key)
            return examined
        # A one-off SlowDown must not fail a check this far in. The verb is a pure read, so
        # a Step Functions Retry re-runs it safely over the same deterministic ranges.
        errors.raise_if_transient(err, f"get {bucket}/{key} bytes={start}-{end}")
        raise

    if pending and at_eof:
        # Bytes left over at the end of the region are a truncated character. At EOF that
        # is REAL corruption (a file cut off mid-character) and is counted; anywhere else
        # it is this region's edge, and the rest of the character sits in a part of the
        # file the budget did not buy — counting it would invent a finding.
        _decode(pending, base)

    return examined


def _regions(size: int, share: int) -> list[tuple[int, int]]:
    """Plan the ranges to read from one file, spending at most ``share`` bytes.

    A file that fits its share is read as ONE range (the caller reports it ``complete``).
    Otherwise: a head window first, because corruption clusters at the start of a
    badly-exported file — a BOM, a codepage-encoded header, an accented name in the first
    records — then evenly-spread ranged reads over the remainder, so a corruption confined
    to the middle or tail of a large file is still reachable.

    The sample COUNT is "up to" DQ_SCAN_SAMPLE_COUNT, floored by DQ_SCAN_MIN_SAMPLE_BYTES:
    see that constant for why the REQUEST count, not just the byte count, is a way to blow
    the timeout.
    """
    if _fits(size, share):
        return [(0, size)] if size else []

    head = int(share * config.DQ_SCAN_HEAD_FRACTION)
    remainder = share - head
    count = min(config.DQ_SCAN_SAMPLE_COUNT, remainder // config.DQ_SCAN_MIN_SAMPLE_BYTES)
    if not count:
        return [(0, head)] if head else []

    # No clipping of the final sample to EOF, and that is not an oversight: reaching here
    # means share < size, so sample (= remainder / count) is strictly less than stride
    # (= the un-headed remainder of the FILE / count) and the last window ends before EOF
    # by construction. A min() here would be unreachable code that reads like a guard —
    # test_planned_regions_never_read_past_the_end_of_the_file pins the invariant instead.
    sample = remainder // count
    stride = (size - head) // count
    regions = [(0, head)]
    for index in range(count):
        regions.append((head + index * stride, sample))
    return regions


def _fits(size: int, share: int) -> bool:
    """True when the whole file fits inside its share, so it is read in full.

    ONE predicate, used by both the planner and the coverage verdict. Duplicating it let a
    single-sided edit report ``coverage: "complete"`` over a file the planner had in fact
    sampled — a coverage figure that lies in the safe-sounding direction.
    """
    return size <= share


def _scan_file(bucket: str, entry: dict, share: int) -> tuple[int, bool, int, list[int]]:
    """Scan one file within its share.

    Returns ``(bytesExamined, read_in_full, invalid_count, first_offsets)``. The offsets are
    already ascending — regions are planned in file order and scanned in order.
    """
    global _invalid
    key = entry["key"]
    size = entry.get("size") or 0
    examined = 0
    _found.clear()
    _invalid = 0
    for start, length in _regions(size, share):
        examined += _scan_region(bucket, key, start, length, at_eof=start + length >= size)
    # A short read (the object changed mid-check) also means this file was not read in full,
    # whatever the manifest's size said.
    return examined, _fits(size, share) and examined >= size, _invalid, list(_found)


def _scan(event: dict) -> dict:
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    manifest_key = events.require(event, "manifestKey", reason=messages.INVALID_REQUEST)
    fmt = events.require(event, "format", reason=messages.INVALID_REQUEST)

    out = dict(event)

    if fmt not in TEXT_FORMATS:
        # Zero bytes read. The report renders the skip and its reason rather than a clean
        # pass — a green encoding result Parquet never earned would be a lie.
        out["encoding"] = {"status": "skipped", "reason": SKIP_BINARY}
        logger.info("byte-scan skipped: format=%s", fmt)
        return out

    files = manifest_store.load(bucket, manifest_key).get("files") or []
    # Compression is per FILE (inspect-source enforces one FORMAT, not one codec), so a
    # folder can mix plain and .gz. The scannable subset is scanned and the rest counted as
    # skipped, rather than losing the whole figure to one .gz sibling.
    scannable = [f for f in files if not config.is_compressed(f["key"])]
    skipped = len(files) - len(scannable)

    if not scannable:
        out["encoding"] = {"status": "skipped", "reason": SKIP_COMPRESSED}
        logger.info("byte-scan skipped: all %d files compressed", skipped)
        return out

    # THE DIVISION THAT IS THE WHOLE POINT: the budget is a TOTAL. 1000 files get ~2 MiB
    # each, 2 files get ~1 GiB each, and the bytes read never exceed the total whatever the
    # file count or the file sizes are.
    share = max(config.DQ_SCAN_TOTAL_BYTES // len(scannable), 1)

    examined = 0
    invalid = 0
    complete = True
    offsets: list[dict] = []
    for entry in scannable:
        file_examined, in_full, file_invalid, file_offsets = _scan_file(bucket, entry, share)
        examined += file_examined
        invalid += file_invalid
        complete = complete and in_full
        # Each example carries its KEY. A bare offset is unreadable across a 1000-file
        # folder — "byte 4,192" of WHICH file? — and the whole point of keeping examples is
        # that an operator can go and look at one.
        offsets.extend(
            {"key": entry["key"], "offset": offset}
            for offset in file_offsets[: config.DQ_OFFSET_SAMPLE - len(offsets)]
        )

    out["encoding"] = {
        "invalidUtf8Sequences": invalid,
        "sampleOffsets": offsets,
        "bytesExamined": examined,
        "bytesTotal": sum(f.get("size") or 0 for f in scannable),
        # A SKIPPED FILE MAKES THE WHOLE FIGURE SAMPLED. Without that clause, one 13-byte
        # .csv beside ninety-nine 1 GiB .csv.gz files reports coverage "complete" at 100%
        # over a folder where 99 GB was never looked at — the figure reading cleanest
        # exactly where it has seen least. FR-001's own standard: a number that silently
        # means "of the first 0.8%" is worse than no number.
        "coverage": "complete" if complete and not skipped else "sampled",
        "filesScanned": len(scannable),
        "filesSkipped": skipped,
    }
    # PER-FILE FIGURES ARE ACCOUNTED FOR BUT NOT RETURNED (a SPEC-112 FR-001 correction,
    # recorded in the delivery doc). Each file gets its own share and its own
    # complete-vs-sampled verdict above, but a per-file ARRAY on the state is ~1 MB at 1000
    # files x 1024-char keys — over Step Functions' 256 KB payload limit, which raises
    # States.DataLimitExceeded OUTSIDE every Catch. The execution would die without
    # reaching NotifyFailure and the user would be told nothing at all, on exactly the
    # biggest folders: the same failure mode SPEC-110's manifest pointer exists to avoid.
    # The report's encoding block is aggregate anyway (SPEC-112 Data Model).
    logger.info(
        "byte-scan: %d files, %d of %d bytes examined, %d invalid sequences, %d skipped",
        len(scannable),
        examined,
        out["encoding"]["bytesTotal"],
        invalid,
        skipped,
    )
    # No clear here: _scan_file resets before every file, and what survives the last one is
    # at most DQ_OFFSET_SAMPLE ints. Clearing it on the way out would ALSO erase the only
    # externally observable evidence that the cap is doing anything — the test asserting it
    # would pass against an unbounded list.
    return out


def handler(event, context) -> dict:
    """Scan a bounded sample of the source's raw bytes and thread the figure onward."""
    return _scan(event)
