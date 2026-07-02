"""infer-schema — the table-builder Step Function's fourth task.

Scans the inspect-source sample object with a polars LazyFrame directly from S3
(never downloaded to /tmp, never fully materialized), derives the data column schema
(order + types), folds in the user-declared partition columns, and generates the
CREATE EXTERNAL TABLE IF NOT EXISTS DDL that execute-ddl runs. Reads are bounded
regardless of object size: Parquet fetches only the file footer, CSV only the header
row, JSON streams at most JSON_SAMPLE_ROWS rows.

Type rules: Parquet keeps native types; JSON infers, typing date/datetime-looking
strings as date/timestamp; CSV is not type-inferred — every column string, matching
the OpenCSVSerde in the DDL. A cheap head_object runs first so transient S3 errors
propagate for the SFN Retry; a polars scan error on an existing object (corrupt /
wrong format) is terminal schema_inference_failed.
"""

import logging
import re

from tbcommon import clients, notify
from tbcommon.errors import TerminalError

from ddl import build_create_table_ddl
from type_mapping import UnmappableTypeError, map_dtype

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Bounded row count for JSON inference / date detection (schema only, not the dataset).
JSON_SAMPLE_ROWS = 1000

# Date / datetime "looking" strings (JSON date-parsing rule). Deterministic detection —
# polars' scan_ndjson has no date-parsing option, so we classify Utf8 columns here.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def _object_uri(bucket, key):
    """Return the polars source URI — a direct s3:// read (no /tmp; object_store
    fetches only the byte ranges the scan needs, with the role's env credentials)."""
    return f"s3://{bucket}/{key}"


def _check_access(bucket, key):
    """Cheap access probe run before the polars scan.

    Surfaces a transient S3 error (throttling / 5xx) as a retryable boto error before
    the scan, whose errors are terminal — preserving the SFN Retry semantics we would
    otherwise lose reading through polars.
    """
    clients.s3().head_object(Bucket=bucket, Key=key)


def _hive(dtype, name):
    try:
        return map_dtype(dtype)
    except UnmappableTypeError as exc:
        raise TerminalError("unmappable_type", f"column {name!r} has unmappable dtype {dtype}") from exc


def _detect_date_type(series):
    """Return 'date'/'timestamp' if every non-null value looks like one, else None."""
    values = [v for v in series.to_list() if v is not None]
    if not values:
        return None
    if all(isinstance(v, str) and _DATE_RE.match(v) for v in values):
        return "date"
    if all(isinstance(v, str) and _DATETIME_RE.match(v) for v in values):
        return "timestamp"
    return None


def _infer_columns(source, fmt):
    """Return ordered [{name, type}] data columns for the sample object at ``source``
    (an s3:// URI in prod; a local path in tests — polars scans both)."""
    import polars as pl

    if fmt == "parquet":
        schema = pl.scan_parquet(source).collect_schema()
        return [{"name": n, "type": _hive(d, n)} for n, d in schema.items()]

    if fmt == "csv":
        # Header only; no type inference — every column is string.
        schema = pl.scan_csv(source, infer_schema_length=0).collect_schema()
        return [{"name": n, "type": "string"} for n in schema.names()]

    if fmt == "json":
        # Stream at most N rows (n_rows bounds the read; nothing full-materialized).
        frame = pl.scan_ndjson(source, infer_schema_length=JSON_SAMPLE_ROWS, n_rows=JSON_SAMPLE_ROWS).collect()
        columns = []
        for name, dtype in frame.schema.items():
            if dtype == pl.String:
                hive = _detect_date_type(frame[name]) or "string"
            else:
                hive = _hive(dtype, name)
            columns.append({"name": name, "type": hive})
        return columns

    raise TerminalError("schema_inference_failed", f"unknown format {fmt!r}")


def handler(event, context):
    # Notify the actor on a terminal schema failure (best-effort); a transient S3
    # error (not a TerminalError) propagates for the SFN Retry unnotified.
    try:
        return _infer(event)
    except TerminalError as err:
        notify.emit_failure(event, err, "infer")
        raise


def _infer(event):
    fmt = event["format"]
    bucket = event["space"]["bucket"]
    sample_key = event["sampleObjectKey"]

    _check_access(bucket, sample_key)
    source = _object_uri(bucket, sample_key)
    try:
        columns = _infer_columns(source, fmt)
    except TerminalError:
        raise  # unmappable_type / unknown format — already terminal
    except Exception as exc:  # noqa: BLE001 - any scan/parse failure = terminal
        raise TerminalError("schema_inference_failed", f"could not read {sample_key}: {exc}") from exc

    partition_keys = event.get("partitionKeys") or []
    ddl = build_create_table_ddl(
        event["space"]["database"],
        event["tableName"],
        columns,
        partition_keys,
        fmt,
        event["location"],
    )

    out = dict(event)
    out["columns"] = columns
    out["ddl"] = ddl
    logger.info("inferred %d columns for %s.%s", len(columns), event["space"]["database"], event["tableName"])
    return out
