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

import logging

from botocore.exceptions import ClientError
from cpcommon import clients, events, s3_listing
from cpcommon.errors import TerminalError
from dqcommon import config, messages

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# S3 error codes meaning "no such object" for the single-file probe below. head_object
# reports a missing key as 404/NotFound rather than NoSuchKey (that one is GetObject's),
# so all three are matched: a wrong guess here would misread a real folder as an access
# error, or an access error as a folder.
_NOT_FOUND_CODES = frozenset({"404", "NotFound", "NoSuchKey"})


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
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") in _NOT_FOUND_CODES:
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


def _inspect(event: dict) -> dict:
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    location = events.require(event, "location", reason=messages.INVALID_REQUEST)

    listing_prefix = _resolve_listing_prefix(bucket, location)
    objects = _list_objects(bucket, listing_prefix)
    _enforce_caps(objects)
    fmt = _resolve_format(objects, location)

    logger.info(
        "inspected %s/%s: format=%s, %d files", bucket, listing_prefix, fmt, len(objects)
    )
    out = dict(event)
    out["format"] = fmt
    out["fileCount"] = len(objects)
    return out


def handler(event, context) -> dict:
    """List + classify the authorized location and carry the request forward."""
    return _inspect(event)
