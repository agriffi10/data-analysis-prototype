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
import logging
import zlib

from cpcommon import clients, events, s3_listing
from cpcommon.errors import TerminalError
from dq_type_mapping import UnmappableTypeError, map_dtype
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

# Chunk size for that streaming read.
_GZIP_CHUNK_BYTES = 256 * 1024

# zlib wbits for a gzip (not raw-deflate) stream.
_GZIP_WBITS = 16 + zlib.MAX_WBITS

# S3 error codes meaning "no such object" for the single-file probe below. head_object
# reports a missing key as 404/NotFound rather than NoSuchKey (that one is GetObject's),
# so all three are matched: a wrong guess here would misread a real folder as an access
# error, or an access error as a folder.
_NOT_FOUND_CODES = frozenset({"404", "NotFound", "NoSuchKey"})


def _error_code(exc) -> str:
    """The S3 error code from a botocore ClientError, or "" if it has none.

    Duck-typed rather than `except ClientError`, matching casio.error_code (shared-space)
    and the table-builder verbs: botocore ships in the Lambda RUNTIME but is not a test
    dependency of this repo, so importing it at module scope makes the verb unimportable
    under `pytest lambdas/` — which is exactly how this was caught in CI.
    """
    return str((getattr(exc, "response", {}) or {}).get("Error", {}).get("Code", ""))


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


def _is_compressed(key: str) -> bool:
    return key.lower().endswith(config.GZIP_SUFFIX)


def _resolve_listing_prefix(bucket: str, location: str) -> str:
    """Return the prefix to list for ``location`` — the key itself, or the folder.

    A single-file location (the user picked one file, not a folder) must yield a
    one-object manifest and proceed normally, so it is listed as its own exact key. A
    folder is listed with a TRAILING SLASH, which is load-bearing: ``list_objects_v2`` is
    a prefix match, not a directory match, so listing ``alice/sales`` without one would
    silently swallow ``alice/sales-archive/`` and ``alice/sales2/`` — the user would get
    a report over files they never selected.

    A ``head_object`` decides which it is, and doubles as the access probe: anything that
    is not a plain "no such key" propagates as a boto error for the SFN's Retry rather
    than being mistaken for a folder.
    """
    try:
        clients.s3().head_object(Bucket=bucket, Key=location)
    except Exception as err:  # noqa: BLE001 - re-raised unless it is a plain "no such key"
        if _error_code(err) in _NOT_FOUND_CODES:
            return f"{location}/"
        raise
    return location


def _list_objects(bucket: str, prefix: str) -> list[tuple[str, int]]:
    """Return the non-ignored data objects under ``prefix`` as ``(key, size)``.

    cpcommon's SEGMENT-LEVEL hidden-path rule (SPEC-107 FR-003) is what keeps this
    pipeline's own ``_data-quality-reports/`` folder from being read back as source data,
    and it also drops the marker, ``athenaresults/``, ``user_settings/`` and zero-byte
    placeholders. Nothing here re-implements those rules.
    """
    return list(s3_listing.list_data_objects(bucket, prefix))


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

    Surfaces an S3 error (missing / denied / throttled object) as a plain boto error the
    SFN's Retry can act on, keeping it distinct from the probe's OWN errors below, which
    are terminal `unreadable_header`. Without it a throttled read would be reported to
    the user as "the columns couldn't be read" — a permanent-sounding verdict on a
    transient fault.
    """
    clients.s3().head_object(Bucket=bucket, Key=key)


def _read_gzip_head(bucket: str, key: str) -> bytes:
    """Return the leading decompressed bytes of a gzip object, reading as little as possible.

    FR-005's "bounded range" is FALSE for gzip: the format is not seekable, so there is no
    byte range that yields the header. The only way in is to stream from byte 0 and
    decompress until the header/sample is in hand — then ABANDON the stream, which is what
    keeps this bounded on a 1 GiB .gz. Stops at the first of: enough lines, or
    GZIP_PROBE_MAX_BYTES of COMPRESSED input consumed.

    The tail after the last newline is dropped: it is a partial line, and handing polars a
    truncated final record would produce a phantom column or a parse error.
    """
    body = clients.s3().get_object(Bucket=bucket, Key=key)["Body"]
    decompressor = zlib.decompressobj(_GZIP_WBITS)
    out = bytearray()
    consumed = 0
    try:
        for chunk in body.iter_chunks(_GZIP_CHUNK_BYTES):
            consumed += len(chunk)
            out += decompressor.decompress(chunk)
            if out.count(b"\n") >= _GZIP_PROBE_LINES or consumed >= GZIP_PROBE_MAX_BYTES:
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


def _columns_from(source, fmt: str) -> list[dict]:
    """Return ordered ``[{name, type}]`` for ``source``.

    ``source`` is an ``s3://`` URI (polars' object_store fetches only the byte ranges the
    scan needs — a Parquet footer, a CSV header) or an in-memory buffer of already-
    decompressed gzip head bytes. Every format yields the same {name, type} shape;
    SPEC-111 needs a type per column because Athena does not auto-detect a Parquet schema.
    """
    import polars as pl

    if fmt == "parquet":
        schema = pl.scan_parquet(source).collect_schema()
        return [{"name": n, "type": _hive(d, n)} for n, d in schema.items()]

    if fmt == "csv":
        # Header only, no type inference: every column is string, matching SPEC-111
        # FR-002's OpenCSVSerde. polars parses the header properly, so a quoted name
        # containing a comma survives — a hand-rolled split(",") would not.
        schema = pl.scan_csv(source, infer_schema_length=0).collect_schema()
        return [{"name": n, "type": "string"} for n in schema.names()]

    if fmt == "json":
        frame = pl.scan_ndjson(
            source, infer_schema_length=JSON_SAMPLE_ROWS, n_rows=JSON_SAMPLE_ROWS
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
            return _columns_from(io.BytesIO(_read_gzip_head(bucket, key)), fmt)
        return _columns_from(_object_uri(bucket, key), fmt)
    except TerminalError:
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


def _inspect(event: dict) -> dict:
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    location = events.require(event, "location", reason=messages.INVALID_REQUEST)

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

    logger.info(
        "inspected %s/%s: format=%s, %d files, partitionKeys=%s",
        bucket,
        listing_prefix,
        fmt,
        len(files),
        [k["name"] for k in partition_keys],
    )
    out = dict(event)
    out["format"] = fmt
    out["fileCount"] = len(files)
    out["files"] = files
    out["partitionKeys"] = partition_keys
    return out


def handler(event, context) -> dict:
    """List + classify the authorized location and carry the request forward."""
    return _inspect(event)
