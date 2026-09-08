"""convert — the verb that actually produces the file, and the only one on this plane that writes.

It reads the result object Athena wrote, gives every column the type Athena declared, writes one
file in the format the user chose, and uploads it to the destination validate-authorize already
proved they may write. Nothing here re-authorizes: the destination key was contained and the
protected folders refused two states ago, and re-deriving either would be a second copy of a rule.

**An expected refusal is a RETURN VALUE, not a raise.** Four outcomes are things the user asked
for and cannot have — an unmappable column type, a result that will not parse, Excel's row
ceiling, and a destination name taken since the browser last looked — and each comes back as
``{"outcome": "refused", "reason": ...}`` for the machine's Choice to route. A raise would reach
the failure terminal by a path that cannot carry the row count that refusal has to name.

**Parquet and JSON never materialise the frame.** The read is ``scan_csv`` over the downloaded
file and the write is ``sink_*``, so memory holds a batch at a time and the ceiling is the
scratch disk rather than RAM. Excel cannot stream — the workbook is built whole — which is why
its ceiling is Excel's own row limit instead. The row count for the two streamed formats is read
back from the written file, by ``rccommon.parquet_footer`` and by counting record separators;
a count taken with polars would be the one ``collect`` that makes the streaming guard unprovable.

**A refusal is logged by its CODE, never by its detail.** A detail can carry the destination
key, and the plane's log line is plain text — a newline in a key forges a second line in it.
``check_prefix`` and ``check_filename`` both refuse control characters, so this is the second of
two gates rather than the only one.

**The transient boundary is the upload.** Anything before it may raise ``TransientError`` for the
machine to retry; nothing after it may, because a retry of an invocation that already completed
its conditional ``PutObject`` meets its own object and reports ``destination_occupied`` to a user
whose save in fact succeeded. The machine retries this verb on ``TransientError`` alone, and a
test holds the upload path free of it.

Attributes:
  SCRATCH_ROOT: Where the downloaded object and the written file live. Emptied on entry and the
    request's own directory removed on exit, so a warm container never carries one request's
    bytes into the next.
  CONTENT_TYPES: The ``Content-Type`` each format is stored under. No user metadata is written:
    the SQL, the execution id and the actor are not stamped onto the object.
  EXCEL_MAX_ROWS: Excel's own data-row ceiling — one less than its 1,048,576 rows, because the
    header takes one. Its COLUMN ceiling is deliberately absent: describe-results refuses a
    result set wider than the state can carry, at a third of Excel's 16,384, so a check here
    could never fire and would read as a fence that stops nobody.
  EXCEL_EXACT_INTEGER: The largest integer an Excel cell holds exactly; it stores every number
    as a double.
  EXCEL_EXACT_DIGITS: The significant digits a double holds, which is what bounds a decimal.
  SINGLE_PUT_MAX_BYTES: The largest object S3 accepts as one ``PutObject``.
  PART_BYTES: The multipart part size, chosen so the part ceiling is far above anything the
    size cap admits.
  _CARRIED: The keys this verb threads on unchanged. ``columns`` and ``resultsBytes`` are read
    and deliberately not returned — nothing downstream reads either.
"""

import logging
import pathlib
import re
import shutil

import polars as pl
from cpcommon import clients, config, errors, events, observability
from cpcommon.errors import TerminalError
from rccommon import notify, parquet_footer, reasons, types
from rccommon.config import max_result_bytes

logger = logging.getLogger()
logger.setLevel(logging.INFO)
observability.init(service="results-conversion")

SCRATCH_ROOT = pathlib.Path("/tmp/results-conversion")  # noqa: S108

CONTENT_TYPES = {
    "parquet": "application/vnd.apache.parquet",
    "json": "application/x-ndjson",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

EXCEL_MAX_ROWS = 1_048_575
EXCEL_EXACT_INTEGER = 2**53
EXCEL_EXACT_DIGITS = 15

SINGLE_PUT_MAX_BYTES = 5 * 1024**3
PART_BYTES = 256 * 1024**2

_CARRIED = (
    "requestId",
    "username",
    "format",
    "onConflict",
    "queryExecutionId",
    "resultsKey",
    "destination",
)


class _Refusal(Exception):
    """An outcome the user asked for and cannot have, on its way to becoming a return value.

    Raised internally so the writers can refuse from wherever they discover the problem, and
    caught at the one place that shapes the verb's return. It never leaves this module.

    Attributes:
      reason: The registered reason code.
      detail: Operator text, logged and never sent to the user.
      tokens: What the user-facing wording needs beyond the format and the file name.
    """

    def __init__(self, reason: str, detail: str, tokens: dict | None = None):
        """Records the refusal's code and the wording it needs.

        Args:
          reason: The registered reason code.
          detail: Operator text.
          tokens: Wording tokens, or None.

        Returns:
          None.

        Raises:
          None.
        """
        self.reason, self.detail, self.tokens = reason, detail, tokens or {}
        super().__init__(f"{reason}: {detail}")


def _scratch() -> pathlib.Path:
    """Empties the scratch root and returns the one directory this invocation works in.

    Emptied on ENTRY rather than only on exit, because the exit path of a previous invocation
    cannot run if that invocation was killed by the function's own timeout — and the container
    it leaves behind is reused.

    **The name is FIXED and carries no request id.** The id is the caller's string, checked only
    for being non-empty, and ``Path / "..%s"`` walks out of the root while ``Path / "/tmp/x"``
    replaces it outright — either of which puts the directory somewhere the sweep above will not
    find it, which is the warm-container property this function exists for. A Lambda container
    runs one invocation at a time, so the id bought nothing; it is in the log line instead.

    Args:
      None.

    Returns:
      The created directory.

    Raises:
      OSError: If the scratch root cannot be created, which is a fault rather than a refusal.
    """
    shutil.rmtree(SCRATCH_ROOT, ignore_errors=True)
    directory = SCRATCH_ROOT / "request"
    directory.mkdir(parents=True)
    return directory


@observability.step("download-results")
def _download(bucket: str, key: str, target: pathlib.Path, fmt: str, described_bytes: int) -> None:
    """Streams the result object onto the scratch disk, re-checking its size as it is read.

    **Call bound: at most once per invocation** — one call in ``_convert``, which ``handler``
    calls once. This verb gets THREE spans rather than one because its body is download, write,
    upload with three comparable costs: a single span covering almost the whole root would tell
    an operator nothing about which of the three was slow.

    The size is re-read here and not trusted from describe-results: a result that grew between
    the two states would otherwise be read past the cap the budget was derived from. It is a
    FAULT rather than a user error — Athena does not rewrite a finished execution's output, so
    a changed size means something this plane does not model.

    ``download_fileobj`` rather than ``get()["Body"].read()``, because the whole point of the
    scratch disk is that the object never exists in memory at once.

    Args:
      bucket: The user-space bucket.
      key: The result object's key.
      target: Where to write it.
      fmt: The output format, which decides the cap: the streamed formats are bounded by the
        scratch disk and Excel by memory, an order of magnitude apart.
      described_bytes: The size describe-results measured, for the log line only.

    Returns:
      None.

    Raises:
      TransientError: On a throttled or failing S3 call, for the machine to retry.
      RuntimeError: If the object's live size is over the cap.
      Exception: Any other S3 failure, as a fault.
    """
    try:
        head = clients.s3().head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        errors.raise_if_transient(exc, "S3")
        raise
    live = int(head["ContentLength"])
    cap = max_result_bytes(fmt)
    if live > cap:
        raise RuntimeError(
            f"result object grew to {live} bytes, over {cap}, since it was described"
        )
    logger.info("downloading %d byte(s) (described as %d)", live, described_bytes)
    try:
        with target.open("wb") as handle:
            clients.s3().download_fileobj(bucket, key, handle)
    except Exception as exc:
        errors.raise_if_transient(exc, "S3")
        raise


def _frame(source: pathlib.Path, schema: dict) -> pl.LazyFrame:
    """Opens the downloaded CSV with the schema given rather than inferred.

    ``infer_schema_length=0`` is what makes "given" true: with any other value polars samples
    the values, and a column of numeric-looking strings Athena declared ``varchar`` would come
    back as a number. NULL and the empty string are distinguished by polars' own default — an
    unquoted empty field is NULL, ``""`` is an empty string — which is exactly Athena's encoding.

    **The header is checked against the metadata first, and that is not belt-and-braces.**
    Measured on polars 1.12: given ``schema_overrides`` whose keys do not match the header,
    ``scan_csv`` RENAMES the columns to the override keys and applies the types POSITIONALLY,
    silently and without an error; given a header in a different order it keeps the file's
    order and matches types by name. So a divergence between what Athena reported and what
    Athena wrote produces a file with the wrong names or the wrong types and no complaint from
    anything. Both facts come from the same execution, so a disagreement is a fault rather than
    a user error — but it must not be a quiet one.

    ``collect_schema`` reads the header alone and materialises nothing, which is what lets the
    streaming guard forbid ``collect`` outright while this still works.

    Args:
      source: The downloaded result object.
      schema: The dtypes, from ``rccommon.types.schema_of``, in the order Athena reported.

    Returns:
      The lazy frame. Nothing is read until a sink or a collect pulls on it.

    Raises:
      RuntimeError: When the CSV's header is not the columns the metadata named, in order.
    """
    header = pl.scan_csv(source, infer_schema_length=0).collect_schema().names()
    if header != list(schema):
        raise RuntimeError(
            f"the result object's header has {len(header)} column(s) and the execution's "
            f"metadata named {len(schema)}, or they are not in the same order"
        )
    return pl.scan_csv(source, schema_overrides=schema, infer_schema_length=0)


def _unreadable(exc: Exception) -> _Refusal:
    """Turns a polars parse failure into a refusal that names the column and the offset.

    **polars' message is never forwarded.** It quotes the offending CELL as well as the column
    and the byte offset, and a cell is data this plane does not put in front of anyone. The
    column and the offset are lifted out into the operator DETAIL; anything that will not yield
    them refuses without them rather than falling back to the raw text.

    They stay in the detail and reach no wording token, so the sentence the user reads carries
    no column name at all here — which is the one place this plane's "a column name is user
    data returned to the user who wrote it" rule does not apply, because the message that would
    carry it is the same message polars built around the cell value.

    polars reports no row number, so neither does the refusal.

    Args:
      exc: Whatever polars raised.

    Returns:
      The refusal.

    Raises:
      None.
    """
    text = str(exc)
    column = re.search(r"at column '([^']*)'", text)
    offset = re.search(r"offset in the file is (\d+) bytes", text)
    where = f" at byte {offset.group(1)}" if offset else ""
    named = f" in column {column.group(1)!r}" if column else ""
    return _Refusal(reasons.RESULTS_UNREADABLE, f"a value{named} did not parse{where}")


def _write_parquet(frame: pl.LazyFrame, target: pathlib.Path) -> int:
    """Streams the frame to one Parquet file and reads its row count back from the footer.

    Compression is polars' own default and is deliberately not named here, so the suite's
    assertion is about what the library does rather than about what this call asked for.

    Args:
      frame: The typed lazy frame.
      target: Where to write.

    Returns:
      The number of data rows written.

    Raises:
      _Refusal: ``results_unreadable`` when a value does not parse as its declared type.
    """
    try:
        frame.sink_parquet(target)
    except Exception as exc:
        raise _unreadable(exc) from exc
    return parquet_footer.row_count(target)


def _write_ndjson(frame: pl.LazyFrame, schema: dict, target: pathlib.Path) -> int:
    """Streams the frame to newline-delimited JSON, one object per line.

    Datetime columns are rendered explicitly rather than left to polars, whose NDJSON writer
    emits ``2020-01-02 03:04:05.123`` — a space separator with trailing zeros stripped, which is
    not ISO-8601 and not to microseconds. The cast is a lazy expression, so the write still
    streams. Everything else is already what the format needs: a decimal is a JSON string of its
    exact digits, because a JSON number would round it.

    Args:
      frame: The typed lazy frame.
      schema: The dtypes, to find the datetime columns without pulling on the frame.
      target: Where to write.

    Returns:
      The number of data rows written, counted as record separators. A JSON string escapes an
      embedded newline, so a raw one is only ever the end of an object.

    Raises:
      _Refusal: ``results_unreadable`` when a value does not parse as its declared type.
    """
    stamps = [
        pl.col(name).dt.to_string("%Y-%m-%dT%H:%M:%S%.6f")
        for name, dtype in schema.items()
        if isinstance(dtype, pl.Datetime)
    ]
    try:
        (frame.with_columns(stamps) if stamps else frame).sink_ndjson(target)
    except Exception as exc:
        raise _unreadable(exc) from exc
    rows = 0
    with target.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            rows += chunk.count(b"\n")
    return rows


def _write_excel(frame: pl.LazyFrame, target: pathlib.Path) -> tuple[int, bool]:
    """Materialises the frame and writes one workbook with a single sheet.

    **No workbook is passed in.** polars builds its own with ``strings_to_formulas: False``, and
    that default is the whole of the formula-injection guard: a cell beginning ``=`` is written
    as a string rather than evaluated. Handing in a workbook would put that setting in this
    verb's gift, which is why the suite's plant is exactly that.

    Args:
      frame: The typed lazy frame.
      target: Where to write.

    Returns:
      The row count, and whether the precision sentence applies.

    Raises:
      _Refusal: ``excel_row_limit`` with the count, writing nothing; ``results_unreadable``
        when a value does not parse as its declared type. The COLUMN ceiling is not checked
        here — it is a fact about the metadata and is refused before the download.
    """
    try:
        materialised = frame.collect()
    except Exception as exc:
        raise _unreadable(exc) from exc
    if materialised.height > EXCEL_MAX_ROWS:
        raise _Refusal(
            reasons.EXCEL_ROW_LIMIT,
            f"{materialised.height} rows, over {EXCEL_MAX_ROWS}",
            {"count": materialised.height},
        )
    materialised.write_excel(target, worksheet="results")
    return materialised.height, _loses_precision(materialised)


def _loses_precision(materialised: pl.DataFrame) -> bool:
    """Reports whether this frame holds a value Excel cannot represent exactly.

    Excel stores every number as a double, so an integer above 2^53 and a decimal carrying more
    than fifteen significant digits both round on the way in. The magnitude is taken from the
    column's ``min`` and ``max``, which come back as PYTHON ints and therefore cannot overflow
    the way ``Series.abs()`` does on Int64's most negative value. Computed from the frame rather
    than assumed from the schema for integers, because a ``bigint`` column of small numbers
    loses nothing and warning about it would train the reader to ignore the sentence.

    Args:
      materialised: The collected frame.

    Returns:
      True when the notification should carry the precision sentence.

    Raises:
      None.
    """
    for name, dtype in materialised.schema.items():
        if isinstance(dtype, pl.Decimal) and (dtype.precision or 38) > EXCEL_EXACT_DIGITS:
            return True
        if dtype in (pl.Int64, pl.UInt64):
            column = materialised[name]
            extremes = [abs(value) for value in (column.min(), column.max()) if value is not None]
            if extremes and max(extremes) >= EXCEL_EXACT_INTEGER:
                return True
    return False


@observability.step("upload-conversion")
def _upload(destination: dict, source: pathlib.Path, fmt: str, on_conflict: str) -> int:
    """Uploads the written file, refusing a name taken since the browser last looked.

    **Call bound: at most once per invocation** — one call in ``_convert``, reached only once the
    write has succeeded.

    ``If-None-Match: "*"`` is what makes the refusal race-free without a lock, and it goes on
    the ``CompleteMultipartUpload`` when the file is too large for one ``PutObject`` — the
    condition has to be on the call that creates the object, and for a multipart that is the
    complete rather than the parts.

    Nothing here raises ``TransientError``: a retry of this verb after the object exists would
    meet its own write and report the user's success as a name conflict.

    The condition is written as "everything except an explicit overwrite" rather than "refuse".
    The two are identical over the closed vocabulary the validator enforces and differ only if
    a value ever escapes it — where this one refuses and the other silently overwrites
    somebody's file.

    Args:
      destination: The resolved destination, carrying the bucket and the key.
      source: The written file.
      fmt: The output format, which decides the ``Content-Type``.
      on_conflict: ``refuse`` or ``overwrite``.

    Returns:
      The uploaded size in bytes.

    Raises:
      _Refusal: ``destination_occupied`` when the name is taken and the answer was ``refuse``.
      Exception: Any other S3 failure, as a fault.
    """
    size = source.stat().st_size
    condition = {} if on_conflict == "overwrite" else {"IfNoneMatch": "*"}
    common = {
        "Bucket": destination["bucket"],
        "Key": destination["key"],
        "ContentType": CONTENT_TYPES[fmt],
    }
    if size <= SINGLE_PUT_MAX_BYTES:
        with source.open("rb") as handle:
            try:
                clients.s3().put_object(Body=handle, **common, **condition)
            except Exception as exc:
                raise _occupied_or_raise(exc, destination["key"]) from exc
        return size
    _multipart(common, condition, source)
    return size


def _multipart(common: dict, condition: dict, source: pathlib.Path) -> None:
    """Uploads one file in parts, conditioning the completion and aborting on any failure.

    The abort is not tidiness: an incomplete multipart upload holds storage indefinitely and is
    invisible in a listing, which is why the execution role is granted the abort alongside the
    put.

    Args:
      common: Bucket, key and content type.
      condition: The conditional header, or an empty dict for an overwrite.
      source: The written file.

    Returns:
      None.

    Raises:
      _Refusal: ``destination_occupied`` when the completion's condition fails.
      Exception: Any other S3 failure, as a fault.
    """
    started = clients.s3().create_multipart_upload(**common)
    upload_id = started["UploadId"]
    try:
        parts = []
        with source.open("rb") as handle:
            while chunk := handle.read(PART_BYTES):
                number = len(parts) + 1
                written = clients.s3().upload_part(
                    Bucket=common["Bucket"],
                    Key=common["Key"],
                    PartNumber=number,
                    UploadId=upload_id,
                    Body=chunk,
                )
                parts.append({"ETag": written["ETag"], "PartNumber": number})
        clients.s3().complete_multipart_upload(
            Bucket=common["Bucket"],
            Key=common["Key"],
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
            **condition,
        )
    except Exception as exc:
        clients.s3().abort_multipart_upload(
            Bucket=common["Bucket"], Key=common["Key"], UploadId=upload_id
        )
        raise _occupied_or_raise(exc, common["Key"]) from exc


def _occupied_or_raise(exc: Exception, key: str) -> Exception:
    """Classifies an S3 write failure as the name being taken, or leaves it a fault.

    Args:
      exc: Whatever S3 raised.
      key: The destination key, for the operator detail.

    Returns:
      The refusal to raise, when the precondition failed.

    Raises:
      Exception: The original error, for anything that is not a precondition failure.
    """
    if errors.error_code(exc) in ("PreconditionFailed", "ConditionalRequestConflict"):
        return _Refusal(reasons.DESTINATION_OCCUPIED, f"{key} already exists")
    raise exc


@observability.traced("convert")
@notify.notifies_on_failure("convert")
def handler(event, context) -> dict:
    """Step Functions entry point: reads the result set and writes the file.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that failed.

    Args:
      event: The described request object.
      context: The Lambda context, unused.

    Returns:
      The request with the outcome attached — converted or refused. A refusal is a return value,
      routed by the machine's Choice; only a fault raises.

    Raises:
      TerminalError: ``malformed_event`` when a carried key is missing.
      TransientError: On a retryable S3 fault, always before anything is written.
    """
    return _convert(event)


def _convert(event) -> dict:
    """Types the result set, writes the file, uploads it, and cleans up on every path.

    The download reads ``config.USER_SPACE_BUCKET`` and NOT ``destination["bucket"]``. An
    execution's result object is always under the actor's own space; the destination may be a
    SHARED space in another bucket, and the two coincide only for a personal one — which is why
    a suite whose fixtures were all personal could not tell the two apart, and why the fake in
    this verb's tests refuses a read aimed anywhere else.

    Args:
      event: The described request object.

    Returns:
      The verb's one return shape.

    Raises:
      TerminalError: ``malformed_event`` when a carried key is missing.
      TransientError: On a retryable S3 fault before the upload.
      Exception: Any fault, including a result object that grew since it was described.
    """
    carried = {key: events.require(event, key) for key in _CARRIED}
    columns = events.require(event, "columns")
    described_bytes = events.require(event, "resultsBytes")
    destination = carried["destination"]
    scratch = _scratch()
    try:
        try:
            schema = types.schema_of(columns)
        except TerminalError as err:
            raise _Refusal(err.reason, err.detail, err.tokens) from err
        source = scratch / "results.csv"
        _download(
            config.USER_SPACE_BUCKET,
            carried["resultsKey"],
            source,
            carried["format"],
            described_bytes,
        )
        target = scratch / destination["key"].rsplit("/", 1)[-1]
        rows, precision_note = _write(carried["format"], _frame(source, schema), schema, target)
        written = _upload(destination, target, carried["format"], carried["onConflict"])
    except _Refusal as refusal:
        logger.info("refused %s for %s", refusal.reason, carried["requestId"])
        observability.info(
            "conversion refused",
            actor=carried["username"],
            format=carried["format"],
            outcome="refused",
            reason=refusal.reason,
        )
        return {
            **carried,
            "traceparent": observability.run_traceparent(),
            "outcome": "refused",
            "reason": refusal.reason,
            "rows": 0,
            "bytes": 0,
            "precisionNote": False,
            "tokens": refusal.tokens or None,
        }
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    logger.info("converted %d row(s) into %d byte(s)", rows, written)
    observability.info(
        "conversion written",
        actor=carried["username"],
        format=carried["format"],
        outcome="converted",
        rows=rows,
        written_bytes=written,
        precision_note=precision_note,
    )
    return {
        **carried,
        "traceparent": observability.run_traceparent(),
        "outcome": "converted",
        "reason": None,
        "rows": rows,
        "bytes": written,
        "precisionNote": precision_note,
        "tokens": None,
    }


@observability.step("write-conversion")
def _write(fmt: str, frame: pl.LazyFrame, schema: dict, target: pathlib.Path) -> tuple[int, bool]:
    """Dispatches to the writer for one format.

    **Call bound: at most once per invocation** — one call in ``_convert``. The span goes on the
    dispatcher rather than on each of the three writers, so one name covers every format and a
    query groups across them.

    Args:
      fmt: The output format, already checked against the closed vocabulary by the validator.
      frame: The typed lazy frame.
      schema: The dtypes.
      target: Where to write.

    Returns:
      The row count, and whether the precision sentence applies. Only Excel can set the latter.

    Raises:
      _Refusal: Whatever the chosen writer refuses.
      KeyError: For a format outside the vocabulary, which the validator has already refused —
        a fault here rather than a refusal, because it would mean the two disagree.
    """
    if fmt == "parquet":
        return _write_parquet(frame, target), False
    if fmt == "json":
        return _write_ndjson(frame, schema, target), False
    if fmt == "xlsx":
        return _write_excel(frame, target)
    raise KeyError(f"no writer for format {fmt!r}")
