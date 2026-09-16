"""data-quality assemble-report — joins everything into the report.

Reads the three Athena result sets and the manifest, computes the one finding SQL cannot express
— cross-file column agreement — and writes the single durable artefact this whole arc exists to
produce.

It recomputes nothing Athena already computed. Row counts, null ratios, type consistency and
duplicates arrive as numbers and are consumed as numbers; re-deriving any of them here would mean
reading the data in a Lambda, which is the design this arc replaced.

The report key is a pure function of the request id, so a retry or a redelivery overwrites the
same object rather than leaving a second copy. That is the whole of this pipeline's replay
safety — no verb in this codebase does request-id idempotency checking — and it is why nothing in
the report may depend on when it ran except its completion timestamp.

The results are read from S3 rather than through the query-results API, which the execution role
deliberately does not grant: the result objects already sit in the requesting space, the role can
already read that prefix, and paginating a wide result through the API would buy nothing.

The service name is the control plane, not the function: one data-quality run is nine
invocations, and they are only one queryable set if they share it. The per-verb identity rides as
the ``verb`` field.

Attributes:
  REPORT_BASENAME: Basename of the artefact, under the request's report prefix.
  _RESULT_SUFFIX: Athena names a result object after its execution id. The key is constructed
    rather than listed — one read instead of a list plus a read, and deterministic under replay.
"""

import json
import logging
from datetime import UTC, datetime

from cpcommon import clients, errors, events, observability
from cpcommon.errors import TerminalError
from dqcommon import index_store, messages, notify, report, sql
from dqcommon import manifest as manifest_store

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="data-quality")

REPORT_BASENAME = "report.json"

_RESULT_SUFFIX = ".csv"


def report_key(report_prefix: str) -> str:
    """Derives the report object's key, purely from the request's report prefix.

    Args:
      report_prefix: The request's report prefix.

    Returns:
      The report key.

    Raises:
      None.
    """
    return f"{report_prefix.rstrip('/')}/{REPORT_BASENAME}"


def _split_uri(uri: str) -> tuple[str, str]:
    """Splits an ``s3://`` URI into its bucket and key.

    Args:
      uri: The full URI.

    Returns:
      A ``(bucket, key)`` tuple.

    Raises:
      None.
    """
    bucket, _, key = uri[len("s3://") :].partition("/")
    return bucket, key


def _read(bucket: str, key: str) -> bytes:
    """Reads one object's bytes, mapping a retryable fault.

    Args:
      bucket: The object's bucket.
      key: The object key.

    Returns:
      The object's bytes.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any deterministic fault propagates.
    """
    try:
        return clients.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as err:
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise


@observability.step("read-results")
def _result_rows(block) -> list[dict]:
    """Reads one query's result rows, or none when it produced no readable result.

    Athena writes a select's results to a file named after its execution id under the output
    location. That is documented and deterministic, which is worth a direct read over a listing —
    but it is also the one assumption in this verb no unit test can prove, since nothing else in
    this repo has ever read a result file. So a miss falls back to listing the prefix rather than
    failing a check that has already run three queries and a byte scan.

    Args:
      block: The state's block for one query, or None when it was never submitted.

    Returns:
      The parsed rows, empty for a query that was not computed.

    Raises:
      TerminalError: ``query_failed`` when no result object can be found at all.
      TransientError: On a retryable S3 fault.
    """
    if not block or block.get("status") == "not_computed":
        return []

    bucket, prefix = _split_uri(block["resultLocation"])
    key = f"{prefix}{block['queryExecutionId']}{_RESULT_SUFFIX}"
    try:
        return report.parse_result(_read(bucket, key))
    except Exception as err:
        if errors.error_code(err) not in ("NoSuchKey", "404"):
            raise
        logger.warning("result %s not at the expected key — listing %s", key, prefix)

    found = _find_result(bucket, prefix)
    if not found:
        raise TerminalError(
            messages.QUERY_FAILED, f"no result object under {bucket}/{prefix}"
        )
    return report.parse_result(_read(bucket, found))


@observability.step("find-result")
def _find_result(bucket: str, prefix: str) -> str:
    """Finds the first result object under a prefix, as a fallback when the key misses.

    Athena's column-type sidecar is excluded by the suffix check: it sorts adjacent to the result,
    and parsing it as the result would yield a report full of zeros rather than an error.

    Args:
      bucket: The results bucket.
      prefix: The query's output prefix.

    Returns:
      The first matching key, or "" when there is none.

    Raises:
      TransientError: On a retryable S3 fault. The fallback path needs the same mapping as every
        other read here — a throttle arriving as a bare client error is not in the Retry list, so
        a one-off would permanently fail a request that has already paid for three queries.
      ClientError: Any deterministic fault propagates.
    """
    try:
        listed = clients.s3().list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents") or []
    except Exception as err:
        errors.raise_if_transient(err, f"list {bucket}/{prefix}")
        raise
    keys = [o["Key"] for o in listed if o["Key"].endswith(_RESULT_SUFFIX)]
    return keys[0] if keys else ""


@observability.step("write-report")
def _write(bucket: str, key: str, document: dict) -> None:
    """Writes the report object.

    Args:
      bucket: The reports bucket.
      key: The report key.
      document: The assembled report.

    Returns:
      None.

    Raises:
      TransientError: On a retryable S3 fault. Losing the report to a one-off throttle must not
        fail the request after every query has run: the key is a pure function of the request id,
        so a retry rewrites it.
      ClientError: Any deterministic fault propagates.
    """
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    try:
        clients.s3().put_object(
            Bucket=bucket, Key=key, Body=body, ContentType="application/json"
        )
    except Exception as err:
        errors.raise_if_transient(err, f"put {bucket}/{key}")
        raise


def _reported_location(event: dict, location: str) -> str:
    """Spells the checked location the way the report, the notification and the runs row carry it.

    A folder ends in a slash and a file does not. That is the form the report and runs-index
    contracts specify, and the one the report page's Open folder and the runs list read: without
    the slash a folder reads as a file, and Open folder lands on its parent. The slash cannot be
    taken from the threaded location, because validate-authorize normalises the location and
    normalisation drops it.

    So the answer is the one inspect-source decided and carried as ``pathFilter``, which a folder
    target does not have. It is read through ``sql.carried_path_filter``, as create-temp-tables and
    start-profile-query read it, so a state without the key is refused rather than read as a
    folder: a report that named a file as a folder would open the wrong place just as quietly.

    Args:
      event: The task input, carrying the single-file decision.
      location: The authorized location as validate-authorize threaded it.

    Returns:
      The location with one trailing slash for a folder target, or unchanged for a single file.

    Raises:
      TerminalError: ``invalid_request`` when the state carries no ``pathFilter``, or a malformed
        one.
    """
    if sql.carried_path_filter(event) is not None:
        return location
    return f"{location.rstrip('/')}/"


def _assemble(event: dict) -> dict:
    """Reads the results and manifest, builds the report, writes it, and summarises it.

    The summary threaded onward is deliberately small: the findings stay in the report, and the
    notification is built from these fields alone and must never carry the full document.

    The record carries counts and the key, never a result row. This verb holds the parsed Athena
    result set in memory, so every figure is derived from user data and none of it is user data —
    a row count is a measurement, a row is the file.

    Args:
      event: The task input, carrying the space, manifest key, report prefix and query blocks.

    Returns:
      The event with the location spelled as the report spells it, and the report key and summary
      fields attached.

    Raises:
      TerminalError: ``invalid_request`` for a missing field — the carried ``pathFilter`` included,
        refused before anything is read or written — or a manifest naming a file outside the
        checked location, or ``query_failed`` when no result object exists or the profile
        result is unusable — a failed check, never a clean one, since every exact figure comes
        from the profile query's total row and without it the report would assemble into a green
        verdict over data nothing measured.
      TransientError: On a retryable S3 fault.
    """
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    manifest_key = events.require(event, "manifestKey", reason=messages.INVALID_REQUEST)
    report_prefix = events.require(event, "reportPrefix", reason=messages.INVALID_REQUEST)
    location = events.require(event, "location", reason=messages.INVALID_REQUEST)
    events.require(event, "requestId", reason=messages.INVALID_REQUEST)
    request = {**event, "location": _reported_location(event, location)}

    manifest = manifest_store.load(bucket, manifest_key, location)
    try:
        document = report.build(
            request,
            manifest,
            _result_rows(event.get("profile")),
            _result_rows(event.get("ragged")),
            _result_rows(event.get("duplicates")),
            event.get("encoding") or {},
            completed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except report.MissingProfileError as err:
        raise TerminalError(messages.QUERY_FAILED, f"profile result unusable: {err}") from err

    key = report_key(report_prefix)
    _write(bucket, key, document)

    out = dict(request)
    out["reportKey"] = key
    out["verdict"] = document["verdict"]
    out["hasApproximateFigures"] = document["hasApproximateFigures"]
    out["hasIncompleteFigures"] = document["hasIncompleteFigures"]
    out["completedAt"] = document["completedAt"]
    out["topIssues"] = document["topIssues"]
    out["fileCount"] = document["fileCount"]

    logger.info(
        "report %s: verdict=%s files=%d rows=%d issues=%d",
        key,
        document["verdict"],
        document["fileCount"],
        document["exact"]["rowCount"],
        len(document["topIssues"]),
    )
    observability.info(
        "assembled report",
        report_key=key,
        verdict=document["verdict"],
        files=document["fileCount"],
        row_count=document["exact"]["rowCount"],
        findings=len(document["topIssues"]),
        approximate=document["hasApproximateFigures"],
        incomplete=document["hasIncompleteFigures"],
    )

    return out


@observability.traced("assemble-report")
@notify.notifies_on_failure("assemble-report")
def handler(event, context) -> dict:
    """Writes the report, notifies the actor, and threads the summary onward.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    The success notification is emitted here, not from a terminal state, because this is the last
    point that holds the summary and runs Python — the success state is a Pass, which cannot call
    anything, and adding a notify task would mean a new state in a fixed list. It is emitted after
    the report object is written, so a notification can never link to a report that does not
    exist; if the write fails this line is never reached and the failure path notifies instead.

    Order is the contract, and it is three deep: report object, then notification, then index row
    — most durable to least. The report is written first so the index can never reference a report
    that does not exist, since the reverse would put a row on the dashboard that fails when
    clicked. The notification goes before the index because it is the user's only completion
    signal, and the index append can cost several round trips under contention — putting that
    ahead of the notification means a verb that times out mid-append leaves a written report
    nobody is ever told about, the silent-success twin of the silent failure this arc exists to
    end. The append never raises: losing the row costs a dashboard entry, failing here would cost
    the whole check.

    The recorded failure detail is safe for every raise site in this verb: one message is a
    literal and the other names a bucket and prefix, and neither quotes a result row.

    Args:
      event: The task input.
      context: The Lambda context, unused.

    Returns:
      The event with the report key, summary fields and index outcome attached.

    Raises:
      TerminalError: ``invalid_request`` or ``query_failed``.
      TransientError: On a retryable S3 fault.
    """
    try:
        out = _assemble(event)
    except TerminalError as err:
        observability.error(
            "assemble-report failed",
            step="read-results",
            error_type=type(err).__name__,
            reason=err.reason,
            detail=err.detail,
            tokens=err.tokens or {},
        )
        raise
    notify.emit_completed(out)

    space = out.get("space") or {}
    out["indexed"] = index_store.append(space.get("bucket", ""), out.get("reportPrefix", ""), out)
    return out
