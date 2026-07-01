"""inspect-source — the table-builder Step Function's third task (SPEC-068).

List the request's prefix and confirm the folder is a table-able source BEFORE any
schema inference:

  1. **Layout** — validate the objects' paths against the request's USER-DECLARED
     ``partitionKeys`` (SPEC-067; keys are declared, never derived here). Empty keys ⇒
     require FLAT data (no ``key=value/`` nesting). Non-empty ⇒ require each declared
     key present as a Hive ``key=value/`` segment, in declared order, with no extra
     undeclared segment.
  2. **Format** — the data objects must be a SINGLE supported format (Parquet / CSV /
     JSON-NDJSON), classified by extension, ignoring the marker / results / hidden files.

On success it emits the facts ``infer-schema`` (SPEC-069) needs — ``format``,
``partitioned``, a representative ``sampleObjectKey``, the table ``location`` (the
prefix / partition root), ``fileCount`` — carrying the validated request (incl.
``partitionKeys``) through UNCHANGED. Any layout/format problem is a terminal failure
with a specific reason; transient S3 errors propagate (raised) for the SFN ``Retry``.
"""

import logging

from tbcommon import s3_listing, notify
from tbcommon.errors import TerminalError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Extension → canonical format. NDJSON / JSONL are all "json".
_EXT_FORMAT = {
    ".parquet": "parquet",
    ".csv": "csv",
    ".json": "json",
    ".ndjson": "json",
    ".jsonl": "json",
}


def _format_of(key):
    """Return the canonical format for a key, or None if the extension is unsupported."""
    dot = key.rfind(".")
    if dot == -1:
        return None
    return _EXT_FORMAT.get(key[dot:].lower())


def _validate_layout(rel_dirs, declared_names):
    """Validate one object's relative directory segments against the declared keys.

    ``rel_dirs`` is the object's path under the prefix split on "/", excluding the
    filename. ``declared_names`` is the ordered list of declared partition-key names
    ([] = flat). Raises ``TerminalError`` on a mismatch.
    """
    if not declared_names:
        # Flat request: no key=value/ nesting is allowed on any data object.
        if any("=" in seg for seg in rel_dirs):
            raise TerminalError(
                "unexpected_partitioning",
                "flat request but data is nested under key=value/ folders",
            )
        return
    # Partitioned request: the dir segments must be exactly the declared keys as Hive
    # key=value/ segments, in order (no missing / reordered / extra segment).
    parsed = []
    for seg in rel_dirs:
        if "=" not in seg:
            raise TerminalError(
                "partition_layout_mismatch",
                f"non-partition folder segment {seg!r} in a partitioned source",
            )
        parsed.append(seg.split("=", 1)[0])
    if parsed != declared_names:
        raise TerminalError(
            "partition_layout_mismatch",
            f"path keys {parsed} do not match declared keys {declared_names} (in order)",
        )


def handler(event, context):
    # Notify the actor on any terminal failure (SPEC-072, best-effort) before the SFN
    # Catch records it; transient S3 errors aren't TerminalError, so they propagate for
    # the Retry without a notification.
    try:
        return _inspect(event)
    except TerminalError as err:
        notify.emit_failure(event, err, "inspect")
        raise


def _inspect(event):
    bucket = event["space"]["bucket"]
    prefix = event["space"]["prefix"]
    declared_names = [k["name"] for k in (event.get("partitionKeys") or [])]

    formats = set()
    unsupported = None
    sample_by_format = {}
    file_count = 0

    for key, _size in s3_listing.list_data_objects(bucket, prefix):
        fmt = _format_of(key)
        if fmt is None:
            unsupported = unsupported or key
            continue
        # Validate this object's partition layout against the declared keys.
        rel = key[len(prefix):] if key.startswith(prefix) else key
        rel_dirs = rel.split("/")[:-1]
        _validate_layout(rel_dirs, declared_names)

        formats.add(fmt)
        sample_by_format.setdefault(fmt, key)
        file_count += 1

    # ── Format decision (specific terminal reasons) ──────────────────────────
    if file_count == 0:
        if unsupported is not None:
            raise TerminalError("unsupported_format", f"only unsupported files present (e.g. {unsupported})")
        raise TerminalError("no_data_files", f"no data files under {prefix!r}")
    if len(formats) > 1:
        raise TerminalError("mixed_formats", f"multiple formats present: {sorted(formats)}")
    if unsupported is not None:
        raise TerminalError("unsupported_format", f"unsupported file mixed in: {unsupported}")

    fmt = next(iter(formats))
    out = dict(event)
    out["format"] = fmt
    out["partitioned"] = bool(declared_names)
    out["sampleObjectKey"] = sample_by_format[fmt]
    out["fileCount"] = file_count
    # location is the table LOCATION (the prefix / partition root) — carried from
    # validate-authorize; recompute defensively if absent.
    out["location"] = event.get("location") or f"s3://{bucket}/{prefix}"
    logger.info("inspected %s: %s, %d files, partitioned=%s", prefix, fmt, file_count, bool(declared_names))
    return out
