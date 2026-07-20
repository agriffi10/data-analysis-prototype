"""data-quality inspect-source — the control plane's second verb (SPEC-110).

Given an authorized location, lists the objects under it, classifies each by FILE
EXTENSION, enforces that the folder is a single consistent format, probes EVERY file's
header/schema, detects Hive-style partition directories, and (SPEC-110 phase 3) writes
the manifest.

Two things here differ from the Lambda-era design and are deliberate:

- **Parquet is a supported input.** The natural workflow is convert-then-verify: run the
  file converter on a messy CSV, then check the resulting Parquet. Rejecting Parquet
  would leave the two arcs unable to talk to each other.
- **There is no total-size cap.** That ceiling was a Lambda artefact. Athena reads the
  data now, so the only caps left are on OBJECT COUNT (the manifest and the cross-file
  comparison scale with the number of files, not their size) and on COMPRESSED object
  size (config.DQ_MAX_GZIP_OBJECT_BYTES — gzip is not splittable).

This verb reads listings, object metadata, and bounded headers ONLY. Bulk reading is
Athena's job (SPEC-111); byte-level reading is byte-scan's (SPEC-112).
"""

import io
import json
import logging
import os
import zlib

from cpcommon import clients, errors, events, s3_listing
from cpcommon.errors import TerminalError, TransientError
from cpcommon.type_mapping import UnmappableTypeError, map_dtype
from dqcommon import config, messages

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Rows the JSON probe reads to infer types. Bounds the read (polars' n_rows stops the
# scan) while giving type inference more than a single row to work with — a lone row of
# nulls would otherwise type a whole column as null.
JSON_SAMPLE_ROWS = 1000

# Lines the gzip probe decompresses before giving up on finding more: a CSV needs one
# (the header); NDJSON wants a sample.
_GZIP_PROBE_LINES = JSON_SAMPLE_ROWS + 1

# The stated bound for the gzip probe (FR-005): COMPRESSED bytes pulled from S3 before
# the stream is abandoned. Small enough that the probe is cheap on a 1 GiB .gz, large
# enough to hold a header line of any realistic width after decompression.
GZIP_PROBE_MAX_BYTES = 8 * 1024 * 1024  # 8 MiB

# The SECOND bound, and the one that actually protects the function: DECOMPRESSED bytes
# held in memory. Bounding the compressed side alone is not enough — that is the whole
# point of a compression bomb. deflate reaches ~1032:1, so ONE 256 KiB chunk can expand to
# ~264 MB and the 8 MiB compressed bound to ~8 GB, against this verb's 1024 MB
# (locals.tf). A .json.gz that is one long single-line array, or a .csv.gz of repetitive
# padded rows, sits far under DQ_MAX_GZIP_OBJECT_BYTES and so passes _enforce_caps — then
# OOM-kills the Lambda. An OOM is not a TerminalError: the actor gets NO notification and
# no reason, which is the silent-failure class this arc exists to eliminate. 32 MiB is
# orders of magnitude more than a header plus JSON_SAMPLE_ROWS rows needs, and a source
# whose first rows genuinely exceed it fails as unreadable_header — loudly, with a reason.
GZIP_PROBE_MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024  # 32 MiB

# Chunk size for that streaming read.
_GZIP_CHUNK_BYTES = 256 * 1024

# zlib wbits for a gzip (not raw-deflate) stream.
_GZIP_WBITS = 16 + zlib.MAX_WBITS

#: The manifest's filename inside the request's report prefix (FR-006).
MANIFEST_BASENAME = "manifest.json"

# S3 error codes meaning "no such object" for the single-file probe below. head_object
# reports a missing key as 404/NotFound rather than NoSuchKey (that one is GetObject's),
# so all three are matched: a wrong guess here would misread a real folder as an access
# error, or an access error as a folder.
_NOT_FOUND_CODES = frozenset({"404", "NotFound", "NoSuchKey"})


# Transient S3 faults now go through cpcommon.errors.raise_if_transient (the canonical
# classifier); the folder-vs-file probe below uses cpcommon.errors.error_code for the
# NoSuchKey/404 check. Both were local copies here until the SPEC-110 follow-up
# consolidated them.


def _classify(key: str) -> str | None:
    """Return the canonical format for ``key``, or None if the extension is unsupported.

    ONE trailing ``.gz`` is stripped before the lookup, so ``data.csv.gz`` classifies as
    csv. Two cases are unsupported by design rather than by omission:

    - a BARE ``.gz`` (no inner extension) — nothing says what is inside it, and this arc
      does not sniff content;
    - ``.parquet.gz`` — Athena cannot read it, and polars cannot range-read a footer
      through gzip, so it is rejected rather than half-supported.

    Classification is on the extension only; content is never sniffed (an accepted
    arc-wide limitation).
    """
    name = key.rsplit("/", 1)[-1].lower()
    if name.endswith(config.GZIP_SUFFIX):
        name = name[: -len(config.GZIP_SUFFIX)]
        if "." not in name:
            return None  # bare ".gz"
        if name.endswith(".parquet"):
            return None  # gzipped Parquet: unreadable by Athena, un-probeable by polars
    dot = name.rfind(".")
    if dot == -1:
        return None
    return config.EXT_FORMAT.get(name[dot:])


#: Shared with byte-scan (SPEC-112): the two verbs must agree on what "compressed" means,
#: or a file this one classifies as gzipped csv gets its DEFLATE output scanned as text.
_is_compressed = config.is_compressed


def _resolve_listing_prefix(bucket: str, location: str) -> str:
    """Return the prefix to list for ``location`` — the key itself, or the folder.

    A single-file location (the user picked one file, not a folder) must yield a
    one-object manifest and proceed normally, so it is listed as its own exact key. A
    folder is listed with a TRAILING SLASH, which is load-bearing: ``list_objects_v2`` is
    a prefix match, not a directory match, so listing ``alice/sales`` without one would
    silently swallow ``alice/sales-archive/`` and ``alice/sales2/`` — the user would get
    a report over files they never selected.

    A ``head_object`` decides which it is, and doubles as the access probe: a retryable
    fault becomes a ``TransientError`` for the SFN's Retry (see ``errors.raise_if_transient`` —
    a bare boto error would NOT be retried), and nothing but a plain "no such key" is read
    as a folder.

    A ZERO-BYTE hit is treated as a folder, not a file. S3 has no directories: a folder is
    a zero-byte placeholder object (SPEC-016 writes them), so an object AT the location key
    with no bytes IS the folder. Without this, a placeholder at ``alice/sales`` would make
    the head succeed, the prefix would stay slash-less, and the listing would quietly pull
    in ``alice/sales-archive/`` and ``alice/sales2/`` — the placeholder itself is dropped by
    s3_listing (size 0), so nothing would fail and the user would get a report over files
    they never selected.
    """
    try:
        head = clients.s3().head_object(Bucket=bucket, Key=location)
    except Exception as err:  # noqa: BLE001 - re-raised unless it is a plain "no such key"
        if errors.error_code(err) in _NOT_FOUND_CODES:
            return f"{location}/"
        errors.raise_if_transient(err, f"head {bucket}/{location}")
        raise
    if not head.get("ContentLength"):
        return f"{location}/"
    return location


def _list_objects(bucket: str, prefix: str) -> list[tuple[str, int]]:
    """Return the non-ignored data objects under ``prefix`` as ``(key, size)``.

    cpcommon's SEGMENT-LEVEL hidden-path rule (SPEC-107 FR-003) is what keeps this
    pipeline's own ``_data-quality-reports/`` folder from being read back as source data,
    and it also drops the marker, ``athenaresults/``, ``user_settings/`` and zero-byte
    placeholders. Nothing here re-implements those rules.

    A throttled page mid-pagination is retryable, so it is mapped rather than left to
    surface as an unretried ClientError (``errors.raise_if_transient``). s3_listing's own
    docstring says transient errors "propagate so the Step Function's Retry can handle
    them" — that is true only for a verb that maps them, which is why this wraps.
    """
    try:
        return list(s3_listing.list_data_objects(bucket, prefix))
    except Exception as err:  # noqa: BLE001 - retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, f"list {bucket}/{prefix}")
        raise


def _enforce_caps(objects: list[tuple[str, int]]) -> None:
    """Apply the object-count cap and the compressed-object size cap."""
    if len(objects) > config.DQ_MAX_OBJECTS:
        raise TerminalError(
            messages.TOO_MANY_FILES,
            f"{len(objects)} objects exceeds DQ_MAX_OBJECTS={config.DQ_MAX_OBJECTS}",
        )
    for key, size in objects:
        if _is_compressed(key) and size > config.DQ_MAX_GZIP_OBJECT_BYTES:
            raise TerminalError(
                messages.COMPRESSED_SOURCE_TOO_LARGE,
                f"{key} is {size} bytes, over DQ_MAX_GZIP_OBJECT_BYTES="
                f"{config.DQ_MAX_GZIP_OBJECT_BYTES} (gzip is not splittable)",
            )


def _resolve_format(objects: list[tuple[str, int]], location: str) -> str:
    """Return the single canonical format of ``objects``, or raise a terminal.

    Mirrors table-builder's rule (table-builder-inspect-source/inspect_source.py:106-113)
    so a folder Table Builder rejects for mixed formats is rejected here for the same
    reason: any unsupported extension is terminal, and more than one surviving format is
    terminal.
    """
    if not objects:
        raise TerminalError(messages.NO_DATA_FILES, f"no data files under {location!r}")

    formats = set()
    for key, _size in objects:
        fmt = _classify(key)
        if fmt is None:
            # Plain, with NO convert-first guidance for .xlsx: Excel is unsupported
            # everywhere (the file-converter arc does not handle it either), so pointing
            # the user at a converter would send them somewhere that cannot help.
            raise TerminalError(messages.UNSUPPORTED_FORMAT, f"unsupported file: {key}")
        formats.add(fmt)

    if len(formats) > 1:
        raise TerminalError(
            messages.MIXED_FORMATS, f"multiple formats present: {sorted(formats)}"
        )
    return next(iter(formats))


def _object_uri(bucket: str, key: str) -> str:
    """Return the polars source URI — a direct s3:// read (mirrors infer_schema.py:39-42).

    No /tmp, no download: object_store fetches only the byte ranges the scan needs (a
    Parquet footer, a CSV header) using the role's env credentials.
    """
    return f"s3://{bucket}/{key}"


def _check_access(bucket: str, key: str) -> None:
    """Cheap access probe run before each read (mirrors infer_schema.py:44-52).

    Catches the common S3 faults — object missing, access denied, throttling — before the
    scan, keeping them distinct from the probe's own errors below, which are terminal
    ``unreadable_header``. A throttle here becomes a ``TransientError`` so the SFN retries
    it; without that mapping it would arrive as an unretried ``ClientError`` and be
    recorded as a permanent failure (see ``errors.raise_if_transient``).

    It does NOT close the gap, and the limit is worth stating plainly: this is a
    check-then-act, and the polars scan afterwards is what actually pulls the footer. If
    S3 throttles THAT read, polars raises its own ComputeError, which ``_probe_columns``
    cannot tell apart from a corrupt file and so terminalizes as unreadable_header — a
    permanent-sounding verdict on a transient fault. Narrowing it would mean pattern-
    matching AWS text out of a polars exception, which is fragile in a different way.
    table-builder's infer-schema carries the same shape (infer_schema.py:44-52); if this
    is ever fixed, fix it in both.
    """
    try:
        clients.s3().head_object(Bucket=bucket, Key=key)
    except Exception as err:  # noqa: BLE001 - retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, f"head {bucket}/{key}")
        raise


def _stream_gzip_head(bucket: str, key: str) -> bytearray:
    """Stream a gzip object from byte 0 and return the bounded, decompressed head.

    FR-005's "bounded range" is FALSE for gzip: the format is not seekable, so there is no
    byte range that yields the header. The only way in is to stream from byte 0 and
    decompress until the header/sample is in hand — then ABANDON the stream, which is what
    keeps this bounded on a 1 GiB .gz. Stops at the first of: enough lines, enough
    COMPRESSED input consumed, or enough DECOMPRESSED output held.

    Split out from _read_gzip_head so the buffer this returns — the one that would OOM the
    function — is directly assertable. The truncation below is not: it drops everything
    after the last newline, so on a compression bomb (one newline, then gigabytes) the
    truncated result is 15 bytes however large this buffer grew. A test asserting on that
    passes whether or not any bound exists, which is precisely the bug review caught.
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
        for chunk in body.iter_chunks(_GZIP_CHUNK_BYTES):
            consumed += len(chunk)
            # max_length caps THIS call's output, and is the guard that matters: checking
            # len(out) after an unbounded decompress() is too late, because the allocation
            # that kills the function already happened inside the call. One 256 KiB chunk
            # of deflate can expand to ~264 MB.
            headroom = GZIP_PROBE_MAX_DECOMPRESSED_BYTES - len(out)
            out += decompressor.decompress(chunk, headroom)
            if (
                out.count(b"\n") >= _GZIP_PROBE_LINES
                or consumed >= GZIP_PROBE_MAX_BYTES
                or len(out) >= GZIP_PROBE_MAX_DECOMPRESSED_BYTES
            ):
                break
    finally:
        body.close()  # abandon the rest of the object; do not drain it
    return out


def _read_gzip_head(bucket: str, key: str) -> bytes:
    """The bounded gzip head, trimmed to whole lines.

    The tail after the last newline is dropped: it is a partial record, and handing polars
    a truncated final row would produce a phantom column or a parse error.
    """
    out = _stream_gzip_head(bucket, key)
    end = out.rfind(b"\n")
    return bytes(out[: end + 1]) if end != -1 else bytes(out)


def _read_plain_head(bucket: str, key: str) -> bytes:
    """Bounded head of a PLAIN (uncompressed) line-delimited object, whole lines only.

    Why this exists at all: polars' object_store cloud reader (a scan over an s3:// URI)
    does NOT work in this Lambda even with the role's credentials handed in via
    storage_options — it fails with "failed to allocate N bytes to download" (SPEC-111
    live finding). boto3 authenticates and reads fine, so CSV/JSON are read the same way
    the gzip path already is: fetch a bounded head via boto3 and hand polars an in-memory
    buffer, which polars reads without object_store.

    The head is enough for the probe — a CSV header is line 1, and JSON type inference
    samples the first JSON_SAMPLE_ROWS lines — so this never downloads a whole large file,
    the property the s3:// scan was chosen for. Parquet is NOT read here (its schema lives
    in a footer at the END of the file); see _probe_columns.
    """
    try:
        body = clients.s3().get_object(Bucket=bucket, Key=key)["Body"]
    except Exception as err:  # noqa: BLE001 - retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise
    out = bytearray()
    try:
        for chunk in body.iter_chunks(_GZIP_CHUNK_BYTES):
            out += chunk
            # Same two bounds the gzip head uses: enough lines for the JSON sample (a CSV
            # needs only the first), and a hard byte ceiling so one pathologically long
            # line can't grow the buffer without limit.
            if out.count(b"\n") >= _GZIP_PROBE_LINES or len(out) >= GZIP_PROBE_MAX_DECOMPRESSED_BYTES:
                break
    finally:
        body.close()  # abandon the rest of the object; do not drain it
    end = out.rfind(b"\n")
    return bytes(out[: end + 1]) if end != -1 else bytes(out)


def _hive(dtype, name: str) -> str:
    try:
        return map_dtype(dtype)
    except UnmappableTypeError as exc:
        raise TerminalError(
            messages.UNREADABLE_HEADER, f"column {name!r} has unmappable dtype {dtype}"
        ) from exc


def _storage_options() -> dict:
    """Credentials for polars' object_store cloud reader, from the Lambda role's env.

    polars does NOT reuse the ambient AWS credential chain the way boto3 does: its
    object_store S3 reader needs the role's creds handed in EXPLICITLY as storage_options,
    even inside a Lambda where boto3 finds them automatically. Without this, a scan over
    s3:// fails with "failed to allocate N bytes to download" — an unauthenticated GET,
    not an allocation problem (observed on the SPEC-111 live run; the bucket-policy
    allowlist was already fixed, and boto3 in the same invocation authenticates fine).

    The Lambda runtime injects AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY /
    AWS_SESSION_TOKEN (temporary role creds — the session token is mandatory or the
    request is rejected) and AWS_REGION. object_store's config keys are the aws_* forms.
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


def _columns_from(source, fmt: str, storage_options: dict | None = None) -> list[dict]:
    """Return ordered ``[{name, type}]`` for ``source``.

    ``source`` is an ``s3://`` URI (polars' object_store fetches only the byte ranges the
    scan needs — a Parquet footer, a CSV header) or an in-memory buffer of already-
    decompressed gzip head bytes. Every format yields the same {name, type} shape;
    SPEC-111 needs a type per column because Athena does not auto-detect a Parquet schema.

    ``storage_options`` carries the role's credentials for the URI case (see
    ``_storage_options``); it is ``None`` for an in-memory buffer, where polars ignores it.
    """
    import polars as pl

    if fmt == "parquet":
        schema = pl.scan_parquet(source, storage_options=storage_options).collect_schema()
        return [{"name": n, "type": _hive(d, n)} for n, d in schema.items()]

    if fmt == "csv":
        # Header only, no type inference: every column is string, matching SPEC-111
        # FR-002's OpenCSVSerde. polars parses the header properly, so a quoted name
        # containing a comma survives — a hand-rolled split(",") would not.
        schema = pl.scan_csv(
            source, infer_schema_length=0, storage_options=storage_options
        ).collect_schema()
        return [{"name": n, "type": "string"} for n in schema.names()]

    if fmt == "json":
        frame = pl.scan_ndjson(
            source,
            infer_schema_length=JSON_SAMPLE_ROWS,
            n_rows=JSON_SAMPLE_ROWS,
            storage_options=storage_options,
        ).collect()
        return [{"name": n, "type": _hive(d, n)} for n, d in frame.schema.items()]

    raise TerminalError(messages.UNREADABLE_HEADER, f"unknown format {fmt!r}")


def _probe_columns(bucket: str, key: str, fmt: str) -> list[dict]:
    """Return the ordered ``[{name, type}]`` columns of one object.

    A file whose header/schema cannot be read fails the WHOLE request rather than being
    skipped: checking a folder while quietly ignoring a file we cannot parse would produce
    a report that omits the worst file in it.
    """
    _check_access(bucket, key)
    try:
        if _is_compressed(key):
            # The gzip head is already in memory (boto3-fetched), so no storage_options.
            return _columns_from(io.BytesIO(_read_gzip_head(bucket, key)), fmt)
        if fmt == "parquet":
            # Parquet's schema lives in a FOOTER at the END of the file — a head read
            # can't reach it — so polars reads the footer via object_store RANGE requests
            # over the s3:// URI, with the role's creds in storage_options.
            #
            # UNVERIFIED LIVE (SPEC-111): object_store's full-download path fails in this
            # Lambda even with credentials (that is why CSV/JSON moved to the boto3 buffer
            # above), but a footer range-GET is a different access pattern and may or may
            # not work. This path needs a real Parquet source to confirm; if it also fails,
            # the fix is a boto3 footer read (last-N-bytes) rather than object_store.
            return _columns_from(_object_uri(bucket, key), fmt, _storage_options())
        # CSV / JSON: header (CSV) or sample rows (JSON) live at the START, so a bounded
        # boto3 head read + polars-from-memory avoids object_store, which does not work in
        # this Lambda (SPEC-111 live finding; see _read_plain_head).
        return _columns_from(io.BytesIO(_read_plain_head(bucket, key)), fmt)
    except (TerminalError, TransientError):
        # TransientError must pass through: _read_gzip_head runs INSIDE this try, so a
        # throttled GetObject would otherwise be swallowed by the catch-all below and
        # reported as "the columns couldn't be read" — a permanent verdict on a fault the
        # SFN would happily have retried.
        raise
    except Exception as exc:  # noqa: BLE001 - a corrupt/mistyped object is terminal, not retryable
        raise TerminalError(
            messages.UNREADABLE_HEADER, f"could not read the schema of {key}: {exc}"
        ) from exc


def _relative_dirs(key: str, listing_prefix: str) -> list[str]:
    """Return ``key``'s directory segments beneath ``listing_prefix``."""
    rel = key[len(listing_prefix):] if key.startswith(listing_prefix) else key
    return rel.split("/")[:-1]


def _detect_partition_keys(objects: list[tuple[str, int]], listing_prefix: str) -> list[dict]:
    """Return the ordered Hive partition keys + their observed values, or [] if flat.

    Keys are AUTO-DETECTED from the paths here — unlike table-builder, where the user
    DECLARES them and each object is validated against that declaration. With no
    declaration to check against, consistency has to be derived from the data itself.

    Every object must therefore yield the SAME ordered keys, and a partitioned source may
    not carry a plain (non key=value) directory segment. The disaster this prevents:
    SPEC-111 builds the temp table with LOCATION at the folder root and PROJECTION over
    these keys, so Athena only ever resolves LOCATION/{key}={value}/ paths. An object
    outside those paths belongs to no partition, is never scanned, and is SILENTLY OMITTED
    from the report — the user would get a clean verdict over a folder we did not fully
    read. That is the same harm unreadable_header refuses, so it is refused here too.
    """
    dirs_by_key = {key: _relative_dirs(key, listing_prefix) for key, _ in objects}
    if not any("=" in seg for dirs in dirs_by_key.values() for seg in dirs):
        return []  # flat: plain nested folders are fine, Athena reads them recursively

    expected: tuple[str, ...] | None = None
    values: dict[str, list[str]] = {}
    for key, dirs in dirs_by_key.items():
        plain = [seg for seg in dirs if "=" not in seg]
        if plain:
            raise TerminalError(
                messages.PARTITION_LAYOUT_MISMATCH,
                f"{key} has non-partition folder segment(s) {plain} in a partitioned source",
            )
        names = tuple(seg.split("=", 1)[0] for seg in dirs)
        if expected is None:
            expected = names
        elif names != expected:
            raise TerminalError(
                messages.PARTITION_LAYOUT_MISMATCH,
                f"{key} has partition keys {list(names)}, but the source uses {list(expected)}",
            )
        for seg in dirs:
            name, value = seg.split("=", 1)
            if not name or not value:
                # An empty key or value is the same harm as a layout mismatch: Hive spells
                # an absent value __HIVE_DEFAULT_PARTITION__, so SPEC-111 would emit a
                # projection enum containing "" — a partition that resolves to nothing,
                # whose files are then silently missing from the report.
                raise TerminalError(
                    messages.PARTITION_LAYOUT_MISMATCH,
                    f"{key} has an empty partition key or value in segment {seg!r}",
                )
            seen = values.setdefault(name, [])
            if value not in seen:
                seen.append(value)

    for name, seen in values.items():
        if len(seen) > config.DQ_MAX_PARTITION_VALUES:
            raise TerminalError(
                messages.TOO_MANY_PARTITION_VALUES,
                f"partition key {name!r} has {len(seen)} values, over "
                f"DQ_MAX_PARTITION_VALUES={config.DQ_MAX_PARTITION_VALUES}",
            )

    # Sorted for determinism: the manifest and SPEC-111's projection enum are compared
    # across retries, and listing order is not guaranteed stable.
    return [{"name": name, "values": sorted(values[name])} for name in expected]


def _manifest_key(report_prefix: str) -> str:
    """Return the manifest's S3 key — a PURE FUNCTION of the request's report prefix.

    validate-authorize derives reportPrefix from requestId alone, so this key is too. That
    is what makes the pipeline replay-safe: a Retry re-runs the whole verb and overwrites
    the manifest byte-identically, which is the only idempotency this codebase has — no
    verb here does request-id bookkeeping.
    """
    return f"{report_prefix.rstrip('/')}/{MANIFEST_BASENAME}"


def _write_manifest(bucket: str, key: str, manifest: dict) -> None:
    """Write the manifest to S3, canonically and compactly.

    What each argument is actually for, stated precisely because it is easy to overclaim:

    - ``separators`` drops JSON's default whitespace. At DQ_MAX_OBJECTS files with wide
      column lists that is a real size saving in the object we write and assemble-report
      later reads back.
    - ``sort_keys`` makes the output canonical rather than dependent on how the dict above
      happened to be built. It is defence against a future edit, NOT what makes a replay
      byte-identical — that follows from the manifest being a pure function of the request
      and the listing (mutation-testing this argument away changes nothing today, and the
      comment should not pretend otherwise).
    """
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    try:
        clients.s3().put_object(
            Bucket=bucket, Key=key, Body=body, ContentType="application/json"
        )
    except Exception as err:  # noqa: BLE001 - retryable faults mapped; the rest propagate
        # Losing the manifest to a one-off SlowDown must not fail the request: the whole
        # verb is replay-safe (the key is a pure function of the request), so a Retry
        # simply rewrites it. Unmapped, this arrives as an unretried ClientError and the
        # user's reason becomes raw AWS text — after all the probing work is done.
        errors.raise_if_transient(err, f"put {bucket}/{key}")
        raise


def _inspect(event: dict) -> dict:
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    location = events.require(event, "location", reason=messages.INVALID_REQUEST)
    request_id = events.require(event, "requestId", reason=messages.INVALID_REQUEST)
    report_prefix = events.require(event, "reportPrefix", reason=messages.INVALID_REQUEST)

    listing_prefix = _resolve_listing_prefix(bucket, location)
    objects = _list_objects(bucket, listing_prefix)
    _enforce_caps(objects)
    fmt = _resolve_format(objects, location)
    partition_keys = _detect_partition_keys(objects, listing_prefix)

    # EVERY file is probed, not one sample: the per-file column lists are what SPEC-112's
    # cross-file agreement check compares, and a single sample cannot show disagreement.
    files = [
        {"key": key, "size": size, "columns": _probe_columns(bucket, key, fmt)}
        for key, size in objects
    ]

    manifest_key = _manifest_key(report_prefix)
    _write_manifest(
        bucket,
        manifest_key,
        {
            "requestId": request_id,
            "format": fmt,
            "fileCount": len(files),
            "partitionKeys": partition_keys,
            "files": files,
        },
    )

    logger.info(
        "inspected %s/%s: format=%s, %d files, partitionKeys=%s -> %s",
        bucket,
        listing_prefix,
        fmt,
        len(files),
        [k["name"] for k in partition_keys],
        manifest_key,
    )

    # The state output THREADS the request object and adds four small keys. The file list
    # and the column lists stay in the manifest and are passed by POINTER (manifestKey);
    # partition VALUES stay there too, since there can be DQ_MAX_PARTITION_VALUES of them
    # per key. The disaster this prevents: a state payload over 256 KB raises
    # States.DataLimitExceeded, which is thrown OUTSIDE every Catch — so the execution dies
    # without reaching NotifyFailure and the user is never told anything at all, on exactly
    # the biggest folders. dict(event) is deliberate: dropping requestId/actor would make
    # RecordSuccess/RecordFailure hard-fail on an absent JSONPath key (States.Runtime,
    # equally uncatchable), so "only these keys" means "add only these", not "keep only
    # these" (SPEC-110 FR-006).
    out = dict(event)
    out["manifestKey"] = manifest_key
    out["format"] = fmt
    out["fileCount"] = len(files)
    out["partitionKeys"] = [k["name"] for k in partition_keys]
    return out


def handler(event, context) -> dict:
    """Inspect the authorized location, write the manifest, and pass its KEY onward."""
    return _inspect(event)
