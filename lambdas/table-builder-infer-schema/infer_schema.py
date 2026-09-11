"""infer-schema — the table-builder Step Function's fourth task.

Probes the sample object inspect-source chose with polars — never downloaded to disk, never
fully materialised — derives the data column schema, folds in the user-declared partition
columns, and generates the CREATE EXTERNAL TABLE DDL that execute-ddl runs. Reads are bounded
regardless of object size: Parquet fetches only the file footer, CSV only the header row, JSON
at most a bounded sample.

Nothing here uses polars' own cloud reader — it does not work in Lambda, which is what broke
every real CSV build. CSV and JSON reach polars as an in-memory boto3-fetched head, Parquet
through a boto3 ranged file object polars seeks to the footer of.

Type rules: Parquet keeps native types; JSON infers, typing date- and datetime-looking strings
accordingly; CSV is not type-inferred, so every column is a string, matching the OpenCSVSerde
in the DDL.

Attributes:
  JSON_SAMPLE_ROWS: Bounded row count for JSON inference and date detection. Schema only,
    never the dataset.
  _DATE_RE: Date-looking string pattern. polars' NDJSON scan has no date-parsing option, so
    string columns are classified here deterministically.
  _DATETIME_RE: Datetime-looking string pattern, same reason.
"""

import io
import logging
import re

from cpcommon import bounded_read, clients, errors, events, observability
from cpcommon import columns as columns_mod
from cpcommon import ddl as ddl_mod
from cpcommon.ddl import build_create_table_ddl
from cpcommon.errors import TerminalError, TransientError
from cpcommon.type_mapping import UnmappableTypeError, map_dtype
from tbcommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")

JSON_SAMPLE_ROWS = 1000

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def _parquet_source(bucket, key):
    """Opens a ranged file object over a Parquet object, whose schema is a footer at the end.

    The seam the tests point at a local file — polars reads either the same way.

    Args:
      bucket: The object's bucket.
      key: The object key.

    Returns:
      A seekable reader polars can pass to its Parquet schema reader.

    Raises:
      None.
    """
    return bounded_read.S3RangeReader(bucket, key)


def _check_access(bucket, key):
    """Probes S3 access before the polars scan, so a fault is distinct from a parse failure.

    A retryable throttle or 5xx becomes a transient error for the SFN Retry — a bare
    ``ClientError`` would not be retried and would permanently fail the build. A deterministic
    fault propagates to the handler wrapper, which notifies the actor so it is not silent.

    Args:
      bucket: The object's bucket.
      key: The object key.

    Returns:
      None.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any deterministic fault propagates.
    """
    try:
        clients.s3().head_object(Bucket=bucket, Key=key)
    except Exception as err:
        errors.raise_if_transient(err, "S3 head probe")
        raise


def _hive(dtype, name):
    """Maps one polars dtype to Hive, turning an unmappable one into a terminal failure.

    Args:
      dtype: The polars dtype.
      name: The column name, for the failure detail.

    Returns:
      The Hive type string.

    Raises:
      TerminalError: ``unmappable_type`` when the dtype has no Hive equivalent.
    """
    try:
        return map_dtype(dtype)
    except UnmappableTypeError as exc:
        raise TerminalError("unmappable_type", f"column {name!r} has unmappable dtype {dtype}") from exc


def _detect_date_type(series):
    """Classifies a string column as a date or timestamp when every value looks like one.

    Args:
      series: The sampled polars series.

    Returns:
      ``"date"``, ``"timestamp"``, or None when the values are not uniformly either.

    Raises:
      None.
    """
    values = [v for v in series.to_list() if v is not None]
    if not values:
        return None
    if all(isinstance(v, str) and _DATE_RE.fullmatch(v) for v in values):
        return "date"
    if all(isinstance(v, str) and _DATETIME_RE.fullmatch(v) for v in values):
        return "timestamp"
    return None


@observability.step("infer-columns")
def _infer_columns(source, fmt):
    """Reads the ordered data columns for one sample object.

    **Call bound: exactly once per invocation** — the two calls in ``_infer`` are the arms of one
    if/else, so exactly one of them runs.

    The span is NOT named ``infer-schema``: that is already this verb's root span, and a child
    sharing its parent's name returns both to the one query an operator would run, with the
    durations double counted. It is named for the operation it performs.

    Parquet goes through the schema reader rather than a lazy scan: over a file object the
    lazy scan reads the whole object in one call, while the schema reader seeks to the footer.
    CSV reads the header only, with no type inference. JSON streams a bounded sample and
    materialises nothing beyond it.

    Args:
      source: An in-memory buffer of head bytes for CSV and JSON, or a seekable file object
        for Parquet. Tests pass local files; polars reads all of them.
      fmt: ``parquet``, ``csv`` or ``json``.

    Returns:
      An ordered list of ``{name, type}`` dicts with Hive types.

    Raises:
      TerminalError: ``unmappable_type`` for a dtype with no Hive equivalent, or
        ``schema_inference_failed`` for an unknown format.
    """
    import polars as pl

    if fmt == "parquet":
        schema = pl.read_parquet_schema(source)
        return [{"name": n, "type": _hive(d, n)} for n, d in schema.items()]

    if fmt == "csv":
        schema = pl.scan_csv(source, infer_schema_length=0).collect_schema()
        return [{"name": n, "type": "string"} for n in schema.names()]

    if fmt == "json":
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


@observability.traced("infer-schema")
@notify.notifies_on_failure("infer")
def handler(event: dict, context) -> dict:
    """Step Functions entry point: infers the schema and builds the CREATE TABLE DDL.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    Args:
      event: The task input, carrying the space, sample key, format and table name.
      context: The Lambda context, unused.

    Returns:
      The event with the inferred columns and rendered DDL attached.

    Raises:
      TerminalError: ``schema_inference_failed``, ``unmappable_type``, ``format_changed`` or
        ``invalid_column_names``. The actor is notified before the SFN Catch records it.
      TransientError: On a retryable S3 fault, passed through for the SFN Retry.
    """
    return _infer(event)


def _check_format_matches_storage(storage, fmt):
    """Refuses a folder whose format no longer matches the table's declared SerDe.

    Runs on the presence of the storage descriptor, which only the refresh path puts on the
    state, so this verb still knows nothing about the request mode and the create path is
    untouched. It runs here rather than in inspect-source because this is the first point
    where both facts exist: inspect-source reports the folder's format, and the table's SerDe
    came from the catalog two states earlier.

    A SerDe this repo does not write is refused the same way. It means the same thing — the
    table and the folder cannot be reconciled by re-deriving columns — and guessing a format
    for it would produce a rebuilt table that reads the files wrongly.

    Args:
      storage: The live table's storage descriptor, carrying its serialization library.
      fmt: The format inspect-source found in the folder.

    Returns:
      None.

    Raises:
      TerminalError: ``format_changed`` when the two disagree or the SerDe is unrecognised.
    """
    library = (storage or {}).get("serializationLibrary")
    declared = ddl_mod.format_of_serde(library)
    if declared != fmt:
        raise TerminalError(
            "format_changed",
            f"table SerDe {library!r} ({declared or 'unrecognised'}) but the folder holds {fmt}",
        )


def _infer(event: dict) -> dict:
    """Probes the sample object, derives the columns and renders the DDL.

    A transient error is re-raised rather than swallowed: the head read runs inside the same
    try, so a throttled GetObject would otherwise be reported as an unreadable file — a
    permanent verdict on a fault the SFN would happily have retried.

    Column names and types are schema, and schema is what a schema bug is about; column values
    are file contents and appear nowhere. The all-string flag records the CSV rule explicitly,
    so a table full of strings reads as the documented decision rather than as inference having
    failed.

    The name check sits between inference and the DDL because this is the only point at which
    the whole schema exists and nothing has been built from it yet. It refuses rather than
    repairs: a rewritten name would no longer match the file's own header, and a table whose
    columns disagree with the data is the harder problem to notice. The names ride out as a
    TOKEN rather than as the error's detail — the user cannot act on the refusal without seeing
    which columns it names, and detail is the operator channel that never reaches them.

    **CREATES ONLY, WHICH MIRRORS THE SPACE-ROOT REFUSAL RATHER THAN CONTRADICTING IT.** A
    refresh re-derives the columns of a table that already exists, so a table built before this
    rule — with a header the rule now rejects — would fail every refresh it was ever given, and
    the only repair would be rewriting the source files. Refusing the create stops the next bad
    table; refusing the refresh strands the ones already there, which is the outcome the whole
    refresh path exists to prevent.

    It selects on the storage descriptor, the same signal the SerDe check above uses, and NOT on
    the request's mode: this verb is shared by both branches and a test forbids it reading the
    mode field, because the moment it does, "a refresh reuses these verbs unchanged" stops being
    true and the two paths begin drifting inside one file. Only the refresh path puts a storage
    descriptor on the state.

    Args:
      event: The task input.

    Returns:
      The event with the columns and DDL attached.

    Raises:
      TerminalError: ``format_changed`` when the folder no longer matches the table's SerDe,
        ``unmappable_type`` for an unmappable dtype, ``invalid_column_names`` when a CREATE's
        header carries a name Athena cannot use, ``schema_inference_failed`` for any other scan
        or parse failure, or ``malformed_event`` for a missing field.
      TransientError: On a retryable S3 fault.
    """
    fmt = events.require(event, "format")
    if event.get("storage"):
        _check_format_matches_storage(event["storage"], fmt)
    bucket = events.require(event, "space", "bucket")
    sample_key = events.require(event, "sampleObjectKey")
    database = events.require(event, "space", "database")
    table_name = events.require(event, "tableName")
    location = events.require(event, "location")

    _check_access(bucket, sample_key)
    try:
        if fmt == "parquet":
            columns = _infer_columns(_parquet_source(bucket, sample_key), fmt)
        else:
            columns = _infer_columns(io.BytesIO(bounded_read.read_head(bucket, sample_key)), fmt)
    except TerminalError:
        raise
    except TransientError:
        raise
    except Exception as exc:
        raise TerminalError("schema_inference_failed", f"could not read {sample_key}: {exc}") from exc

    if not event.get("storage"):
        try:
            columns_mod.check(columns)
        except columns_mod.InvalidColumnNamesError as exc:
            raise TerminalError(
                "invalid_column_names", exc.summary, tokens={"columns": exc.summary}
            ) from exc

    partition_keys = event.get("partitionKeys") or []
    ddl = build_create_table_ddl(database, table_name, columns, partition_keys, fmt, location)

    out = dict(event)
    out["columns"] = columns
    out["ddl"] = ddl
    logger.info("inferred %d columns for %s.%s", len(columns), database, table_name)
    observability.info(
        "inferred schema",
        database=database,
        table=table_name,
        columns=len(columns),
        column_names=[c["name"] for c in columns],
        column_types=sorted({c["type"] for c in columns}),
        format=fmt,
        all_string=fmt == "csv",
    )
    return out
