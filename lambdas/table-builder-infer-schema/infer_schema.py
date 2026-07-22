"""infer-schema — the table-builder Step Function's fourth task.

Probes the inspect-source sample object with polars (never downloaded to /tmp, never
fully materialized), derives the data column schema (order + types), folds in the
user-declared partition columns, and generates the CREATE EXTERNAL TABLE IF NOT EXISTS
DDL that execute-ddl runs. Reads are bounded regardless of object size: Parquet fetches
only the file footer, CSV only the header row, JSON at most JSON_SAMPLE_ROWS rows.

CSV/JSON reach polars as an in-memory boto3-fetched head rather than an ``s3://`` URI:
polars' own cloud reader does not work in Lambda (it tries to download the whole object),
which is what broke every real CSV build until this was ported from data-quality — see
``cpcommon.bounded_read``. Parquet still scans the URI because its schema lives in a
footer at the END of the file.

Type rules: Parquet keeps native types; JSON infers, typing date/datetime-looking
strings as date/timestamp; CSV is not type-inferred — every column string, matching
the OpenCSVSerde in the DDL. A cheap head_object runs first so transient S3 errors
propagate for the SFN Retry; a polars scan error on an existing object (corrupt /
wrong format) is terminal schema_inference_failed.
"""

import io
import logging
import re

from cpcommon import bounded_read, clients, errors, events
from tbcommon import notify
from cpcommon.errors import TerminalError, TransientError
from cpcommon.ddl import build_create_table_ddl
from cpcommon.type_mapping import UnmappableTypeError, map_dtype

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Bounded row count for JSON inference / date detection (schema only, not the dataset).
JSON_SAMPLE_ROWS = 1000

# Date / datetime "looking" strings (JSON date-parsing rule). Deterministic detection —
# polars' scan_ndjson has no date-parsing option, so we classify Utf8 columns here.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def _object_uri(bucket, key):
    """Return the polars source URI (Parquet only — its footer needs ranged reads)."""
    return bounded_read.object_uri(bucket, key)


def _check_access(bucket, key):
    """Cheap access probe run before the polars scan.

    Runs before the scan so an S3 fault is distinct from the scan's own errors (which are
    terminalized as ``schema_inference_failed``). A retryable throttle/5xx becomes a
    ``TransientError`` for the SFN Retry (``cpcommon.errors.raise_if_transient``) — a bare
    ``ClientError`` would NOT be retried and would permanently fail the build. A deterministic fault
    (missing/denied) propagates to the handler wrapper, which notifies the actor
    (@notifies_on_failure) so it isn't silent.
    """
    try:
        clients.s3().head_object(Bucket=bucket, Key=key)
    except Exception as err:  # noqa: BLE001 - retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, "S3 head probe")
        raise


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


def _infer_columns(source, fmt, storage_options=None):
    """Return ordered [{name, type}] data columns for the sample object at ``source``.

    ``source`` is an in-memory buffer of head bytes (CSV / JSON), an ``s3://`` URI
    (Parquet, where ``storage_options`` carries the role's credentials), or a local path
    in tests — polars reads all three. ``storage_options`` is ignored for a buffer.
    """
    import polars as pl

    if fmt == "parquet":
        schema = pl.scan_parquet(source, storage_options=storage_options).collect_schema()
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


@notify.notifies_on_failure("infer")
def handler(event: dict, context) -> dict:
    """SFN entry point: infer the schema and build the ``CREATE EXTERNAL TABLE`` DDL.

    Delegates to ``_infer`` and notifies the actor on a terminal schema failure
    (best-effort). Any other error escaping ``_infer`` (e.g. an S3 access-probe failure)
    is surfaced to the actor by ``@notifies_on_failure`` before the SFN ``Catch`` records
    it.
    """
    return _infer(event)


def _infer(event: dict) -> dict:
    fmt = events.require(event, "format")
    bucket = events.require(event, "space", "bucket")
    sample_key = events.require(event, "sampleObjectKey")
    database = events.require(event, "space", "database")
    table_name = events.require(event, "tableName")
    location = events.require(event, "location")

    _check_access(bucket, sample_key)
    try:
        if fmt == "parquet":
            # The Parquet schema lives in a footer at the END of the file, which a head
            # read cannot reach, so polars reads it over the URI with explicit creds.
            columns = _infer_columns(_object_uri(bucket, sample_key), fmt, bounded_read.storage_options())
        else:
            # CSV / JSON: schema is at the START, so a bounded boto3 head read keeps
            # polars off object_store, which does not work here (cpcommon.bounded_read).
            columns = _infer_columns(io.BytesIO(bounded_read.read_head(bucket, sample_key)), fmt)
    except TerminalError:
        raise  # unmappable_type / unknown format — already terminal
    except TransientError:
        # The head read runs INSIDE this try, so a throttled GetObject would otherwise be
        # swallowed below and reported as an unreadable file — a permanent verdict on a
        # fault the SFN would happily have retried.
        raise
    except Exception as exc:  # noqa: BLE001 - any scan/parse failure = terminal
        raise TerminalError("schema_inference_failed", f"could not read {sample_key}: {exc}") from exc

    partition_keys = event.get("partitionKeys") or []
    ddl = build_create_table_ddl(database, table_name, columns, partition_keys, fmt, location)

    out = dict(event)
    out["columns"] = columns
    out["ddl"] = ddl
    logger.info("inferred %d columns for %s.%s", len(columns), database, table_name)
    return out
