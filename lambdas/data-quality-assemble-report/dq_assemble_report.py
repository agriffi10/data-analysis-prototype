"""data-quality assemble-report — join everything into the report (SPEC-112 FR-002/003).

Reads the three Athena result sets (SPEC-111) and the manifest (SPEC-110), computes the one
finding SQL cannot express — cross-file column agreement — and writes the single durable
artefact this whole arc exists to produce.

IT RECOMPUTES NOTHING ATHENA ALREADY COMPUTED. Row counts, null ratios, type consistency
and duplicates arrive as numbers and are consumed as numbers; re-deriving any of them here
would mean reading the data in a Lambda, which is the design this arc replaced.

THE REPORT KEY IS A PURE FUNCTION OF requestId, so a Step Functions Retry or an SQS
redelivery OVERWRITES the same object rather than leaving a second copy. That is the whole
of this pipeline's replay safety — no verb in this codebase does request-id idempotency
checking — and it is why nothing in the report may depend on when it ran except
``completedAt``.

The results are read FROM S3 rather than through athena:GetQueryResults, which the
execution role deliberately does not grant (infra/modules/data-quality/policies/
execution.json.tftpl): the result objects already sit in the requesting space, the role can
already read that prefix, and paginating a 1400-column result through the API would buy
nothing.
"""

import json
import logging
from datetime import datetime, timezone

from cpcommon import clients, errors, events
from cpcommon.errors import TerminalError
from dqcommon import index_store, manifest as manifest_store, messages, notify, report

logger = logging.getLogger()
logger.setLevel(logging.INFO)

#: Basename of the artefact, under {space}/_data-quality-reports/{requestId}/.
REPORT_BASENAME = "report.json"

#: Athena names a result object after its execution id. Constructed rather than listed —
#: one GET instead of a LIST plus a GET, and deterministic under replay.
_RESULT_SUFFIX = ".csv"


def report_key(report_prefix: str) -> str:
    """``{space}/_data-quality-reports/{requestId}/report.json`` — pure in requestId."""
    return f"{report_prefix.rstrip('/')}/{REPORT_BASENAME}"


def _split_uri(uri: str) -> tuple[str, str]:
    """``s3://bucket/a/b/`` -> ``("bucket", "a/b/")``."""
    bucket, _, key = uri[len("s3://") :].partition("/")
    return bucket, key


def _read(bucket: str, key: str) -> bytes:
    try:
        return clients.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as err:  # noqa: BLE001 - retryable faults mapped; the rest propagate
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise


def _result_rows(block) -> list[dict]:
    """Return one query's result rows, or [] when it produced no readable result.

    Athena writes a SELECT's results to ``{OutputLocation}{QueryExecutionId}.csv``. That is
    documented behaviour and it is deterministic, which is worth a GET over a LIST — but it
    is also the ONE assumption in this verb that no unit test can prove, since nothing else
    in this repo has ever read a result file. So a miss falls back to listing the prefix
    rather than failing a check that has already run three queries and a byte scan.
    """
    if not block or block.get("status") == "not_computed":
        return []

    bucket, prefix = _split_uri(block["resultLocation"])
    key = f"{prefix}{block['queryExecutionId']}{_RESULT_SUFFIX}"
    try:
        return report.parse_result(_read(bucket, key))
    except Exception as err:  # noqa: BLE001 - transients already re-raised inside _read
        if errors.error_code(err) not in ("NoSuchKey", "404"):
            raise
        logger.warning("result %s not at the expected key — listing %s", key, prefix)

    found = _find_result(bucket, prefix)
    if not found:
        raise TerminalError(
            messages.QUERY_FAILED, f"no result object under {bucket}/{prefix}"
        )
    return report.parse_result(_read(bucket, found))


def _find_result(bucket: str, prefix: str) -> str:
    """First ``.csv`` under ``prefix`` — the fallback when the constructed key misses.

    ``.csv.metadata`` (Athena's column-type sidecar) is excluded explicitly: it sorts
    adjacent to the result and parsing it as the result would yield a report full of zeros
    rather than an error.
    """
    try:
        listed = clients.s3().list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents") or []
    except Exception as err:  # noqa: BLE001 - retryable faults mapped; the rest propagate
        # The fallback path needs the same mapping as every other S3 call here: a SlowDown
        # arriving as a bare ClientError is not in the Retry list, so a one-off throttle
        # would permanently fail a request that has already paid for three Athena queries.
        errors.raise_if_transient(err, f"list {bucket}/{prefix}")
        raise
    keys = [o["Key"] for o in listed if o["Key"].endswith(_RESULT_SUFFIX)]
    return keys[0] if keys else ""


def _write(bucket: str, key: str, document: dict) -> None:
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    try:
        clients.s3().put_object(
            Bucket=bucket, Key=key, Body=body, ContentType="application/json"
        )
    except Exception as err:  # noqa: BLE001 - retryable faults mapped; the rest propagate
        # Losing the report to a one-off SlowDown must not fail the request after every
        # query has run: the key is a pure function of requestId, so a Retry rewrites it.
        errors.raise_if_transient(err, f"put {bucket}/{key}")
        raise


def _assemble(event: dict) -> dict:
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    manifest_key = events.require(event, "manifestKey", reason=messages.INVALID_REQUEST)
    report_prefix = events.require(event, "reportPrefix", reason=messages.INVALID_REQUEST)
    events.require(event, "requestId", reason=messages.INVALID_REQUEST)

    manifest = manifest_store.load(bucket, manifest_key)
    try:
        document = report.build(
            event,
            manifest,
            _result_rows(event.get("profile")),
            _result_rows(event.get("ragged")),
            _result_rows(event.get("duplicates")),
            event.get("encoding") or {},
            completed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except report.MissingProfileError as err:
        # A failed check, never a clean one. Every exact figure comes from the profile
        # query's total row, so without it the report would assemble into a green verdict
        # over data nothing measured — the one outcome worse than no report at all.
        raise TerminalError(messages.QUERY_FAILED, f"profile result unusable: {err}") from err

    key = report_key(report_prefix)
    _write(bucket, key, document)

    out = dict(event)
    # A SMALL payload, deliberately. The findings stay in the report; SPEC-114's
    # notification is built from these fields alone and must never carry the full document.
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

    return out


@notify.notifies_on_failure("assemble-report")
def handler(event, context) -> dict:
    """Write the report, notify the actor, and thread the summary onward.

    THE SUCCESS NOTIFICATION IS EMITTED HERE, not from a terminal state, because this is the
    last point that holds the summary AND runs Python. ``RecordSuccess`` is a ``Pass``, which
    cannot call anything — adding a NotifySuccess Task would mean a new state, and the state
    list is fixed (SPEC-108). It is emitted AFTER the report object is written, so a
    notification can never link to a report that does not exist; if the write fails this
    line is never reached and the failure path notifies instead.
    """
    out = _assemble(event)
    notify.emit_completed(out)

    # ORDER IS THE CONTRACT, AND IT IS THREE-DEEP: report object, then notification, then
    # index row — most durable to least.
    #
    # The report is written first (in `_assemble`) so the index can never reference a report
    # that does not exist; the reverse would put a row on the dashboard that 404s when
    # clicked. The NOTIFICATION goes before the index because it is the user's only
    # completion signal (SPEC-114) and the index append can cost up to
    # DQ_INDEX_CAS_RETRIES round trips under contention — putting that ahead of the notify
    # means a verb that times out mid-CAS leaves a written report nobody is ever told about,
    # which is the silent-success twin of the silent failure this arc exists to end.
    #
    # `append` never raises: an exhausted CAS or an unwritable index is logged and swallowed.
    # Losing the row costs a dashboard entry; failing here would cost the whole check.
    space = out.get("space") or {}
    out["indexed"] = index_store.append(space.get("bucket", ""), out.get("reportPrefix", ""), out)
    return out
