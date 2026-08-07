"""inspect-source — the table-builder Step Function's third task.

Lists the request's prefix and confirms the folder is a table-able source before any schema
inference. Paths are checked against the user-declared partition keys, never derived here:
empty keys require flat data, and non-empty keys must appear as Hive ``key=value/`` segments,
in declared order, with no extra segment. The data objects must all be a single supported
format, classified by extension.

The service name is the control plane, not the function, so one build's five invocations stay
one queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  _EXT_FORMAT: File extension to canonical format. NDJSON and JSONL are both JSON.
"""

import logging

from cpcommon import errors, events, observability, s3_listing
from cpcommon.errors import TerminalError
from tbcommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")

_EXT_FORMAT = {
    ".parquet": "parquet",
    ".csv": "csv",
    ".json": "json",
    ".ndjson": "json",
    ".jsonl": "json",
}


def _format_of(key):
    """Classifies one object key by its file extension.

    Args:
      key: The object key.

    Returns:
      The canonical format, or None when the extension is unsupported or absent.

    Raises:
      None.
    """
    dot = key.rfind(".")
    if dot == -1:
        return None
    return _EXT_FORMAT.get(key[dot:].lower())


def _validate_layout(rel_dirs, declared_names):
    """Checks one object's directory segments against the declared partition keys.

    A flat request allows no ``key=value/`` nesting on any data object. A partitioned request
    requires the segments to be exactly the declared keys, in order, with none missing,
    reordered or extra.

    Args:
      rel_dirs: The object's path under the prefix, split on slashes, excluding the filename.
      declared_names: The ordered declared partition-key names; empty means flat.

    Returns:
      None.

    Raises:
      TerminalError: ``unexpected_partitioning`` when a flat request finds nesting, or
        ``partition_layout_mismatch`` when the segments do not match the declared keys.
    """
    if not declared_names:
        if any("=" in seg for seg in rel_dirs):
            raise TerminalError(
                "unexpected_partitioning",
                "flat request but data is nested under key=value/ folders",
            )
        return
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


@observability.traced("inspect-source")
@notify.notifies_on_failure("inspect")
def handler(event: dict, context) -> dict:
    """Step Functions entry point: inspects the source folder and emits the listing state.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    Args:
      event: The task input, carrying the space and any declared partition keys.
      context: The Lambda context, unused.

    Returns:
      The event with the format, partitioned flag, sample key, file count and location added.

    Raises:
      TerminalError: On any layout or format problem, notified to the actor before the SFN
        Catch records it.
      TransientError: On a retryable S3 fault, passed through un-notified for the SFN Retry.
    """
    return _inspect(event)


def _inspect(event: dict) -> dict:
    """Lists the prefix, validates every object's layout and format, and shapes the state.

    The listing is materialised inside a mapped try: a throttle during pagination would
    otherwise surface mid-iteration as a bare ClientError this verb's Retry list does not name,
    permanently failing the build. Materialising also isolates the throttle-prone S3 call from
    the loop-body logic.

    The recorded partition key names are declared, not detected — this plane takes them from
    the user rather than inferring them, so they are a statement of intent that every object
    was then validated against.

    Args:
      event: The task input.

    Returns:
      The event with the format, partitioned flag, sample key, file count and location added.
      The location is the prefix, the partition root, recomputed defensively when absent.

    Raises:
      TerminalError: ``no_data_files`` for an empty folder, ``unsupported_format`` when an
        unsupported file is present, ``mixed_formats`` when several formats are, or a layout
        reason from ``_validate_layout``.
      TransientError: On a retryable S3 fault.
    """
    bucket = events.require(event, "space", "bucket")
    prefix = events.require(event, "space", "prefix")
    declared_names = [k["name"] for k in (event.get("partitionKeys") or [])]

    formats = set()
    unsupported = None
    sample_by_format = {}
    file_count = 0

    try:
        objects = list(s3_listing.list_data_objects(bucket, prefix))
    except Exception as err:
        errors.raise_if_transient(err, f"list {bucket}/{prefix}")
        raise

    for key, _size in objects:
        fmt = _format_of(key)
        if fmt is None:
            unsupported = unsupported or key
            continue
        rel = key.removeprefix(prefix)
        rel_dirs = rel.split("/")[:-1]
        _validate_layout(rel_dirs, declared_names)

        formats.add(fmt)
        sample_by_format.setdefault(fmt, key)
        file_count += 1

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
    out["location"] = event.get("location") or f"s3://{bucket}/{prefix}"
    logger.info("inspected %s: %s, %d files, partitioned=%s", prefix, fmt, file_count, bool(declared_names))
    observability.info(
        "inspected source",
        prefix=prefix,
        format=fmt,
        files=file_count,
        partition_key_names=list(declared_names or []),
        partitioned=bool(declared_names),
    )
    return out
