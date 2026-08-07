"""The per-space runs index — one small entry per completed check.

Without it the dashboard would have to list the reports prefix and read every report to build a
row, and S3 lists lexicographically by key, so ordering by a UUID request id gives no chronology
whatsoever. A recent-checks page would return runs in effectively random order, and sorting
properly would mean fetching every report in the space on every page load. The index makes the
whole dashboard one read.

The write is a compare-and-swap because checks of different locations run in parallel — the
request queue serialises only same-location checks — so two report assemblies can
read-modify-write this object at once and one would silently lose the other's run.

The loop is duplicated here rather than shared: the equivalent primitive lives in a different
Lambda layer that the data-quality functions never attach, so importing it would fail at cold
start. A deliberate twin, not drift; keep the semantics identical.

The index is a convenience, never a dependency. Every failure here is logged and swallowed. The
report is the artefact: it is already written and the notification has already fired by the time
this runs, so failing the check because its row could not be recorded would trade a real outcome
for a cosmetic one.

Attributes:
  INDEX_BASENAME: The index object's basename, inside a space's reports prefix.
  ENTRY_FIELDS: The keys one entry carries — deliberately the row's fields and nothing more. The
    size of this object is the dashboard's load time, since it is fetched whole on every page
    load, so putting findings in it would make the list page pay to download detail it never
    renders. The heavy findings stay in the per-run report, fetched only on drill-down.
"""

import json
import logging

from cpcommon import clients

from . import config

logger = logging.getLogger()

INDEX_BASENAME = "index.json"

ENTRY_FIELDS = (
    "requestId",
    "location",
    "format",
    "verdict",
    "fileCount",
    "hasApproximateFigures",
    "timestamp",
)


def index_key(report_prefix: str) -> str:
    """Derives a space's index key from one request's report prefix.

    The prefix threaded on the state is per request; the index is per space, one level up.

    Args:
      report_prefix: The request's report prefix.

    Returns:
      The index object's key.

    Raises:
      None.
    """
    trimmed = report_prefix.strip("/")
    parent = trimmed.rsplit("/", 1)[0] if "/" in trimmed else trimmed
    return f"{parent}/{INDEX_BASENAME}"


def entry_from(summary: dict) -> dict:
    """Projects the report summary onto the index entry's fields.

    Built by allowlist, never by copying the event: the summary carries the whole threaded
    request — tokens, bucket names, query ids — and a denylist would leak whichever field a later
    change adds.

    Args:
      summary: The assembled report summary.

    Returns:
      The index entry.

    Raises:
      None.
    """
    entry = {field: summary.get(field) for field in ENTRY_FIELDS if field != "timestamp"}
    entry["timestamp"] = summary.get("completedAt")
    return entry


def _read(bucket: str, key: str) -> tuple[list, str | None]:
    """Reads the index and its entity tag, treating a missing or corrupt object as empty.

    A corrupt index is rebuilt rather than treated as an error. Failing, or refusing to write,
    would mean one bad object permanently stops a space from recording new runs, and the entries
    it would preserve are a convenience whose source of truth — the report objects — is intact.
    The tag is still returned so the rebuild goes through the same compare-and-swap and cannot
    clobber a writer who fixed it in the meantime.

    Args:
      bucket: The reports bucket.
      key: The index key.

    Returns:
      An ``(entries, etag)`` tuple.

    Raises:
      None.
    """
    try:
        obj = clients.s3().get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read()
        etag = obj.get("ETag")
    except Exception as err:  # noqa: BLE001
        logger.info("no readable runs index at %s/%s (%s); starting a new one", bucket, key, err)
        return [], None

    try:
        document = json.loads(body)
        entries = document["entries"]
        if not isinstance(entries, list):
            raise TypeError("entries is not a list")
    except Exception:  # noqa: BLE001
        logger.warning("runs index at %s/%s is unreadable; rebuilding it", bucket, key)
        return [], etag
    return entries, etag


def _write(bucket: str, key: str, entries: list, etag: str | None) -> None:
    """Writes the index conditionally on the tag it was read at.

    Args:
      bucket: The reports bucket.
      key: The index key.
      entries: The full entry list to write.
      etag: The tag to match, or None to write only if the object is absent.

    Returns:
      None.

    Raises:
      ClientError: On a precondition failure, so the CAS loop can retry, or any other S3 fault.
    """
    kwargs = {
        "Bucket": bucket,
        "Key": key,
        "Body": json.dumps({"entries": entries}, separators=(",", ":")).encode(),
        "ContentType": "application/json",
    }
    if etag is None:
        kwargs["IfNoneMatch"] = "*"
    else:
        kwargs["IfMatch"] = etag
    clients.s3().put_object(**kwargs)


def _is_precondition(exc) -> bool:
    """Reports whether a conditional write lost to a concurrent writer.

    One code is a failed match-on-tag; the other is what S3 returns when two create-only writes
    race. Both mean someone else committed first, so re-read and re-apply. Treating the conflict
    as a hard error would drop the first run a space ever records — the one case where the index
    does not exist yet and two parallel checks are most likely to create it simultaneously.

    Args:
      exc: The write fault.

    Returns:
      True when the fault is a precondition failure.

    Raises:
      None.
    """
    code = str(((getattr(exc, "response", {}) or {}).get("Error") or {}).get("Code", ""))
    return code in ("PreconditionFailed", "412", "ConditionalRequestConflict", "409")


def append(bucket: str, report_prefix: str, summary: dict) -> bool:
    """Appends this run to its space's index under a compare-and-swap loop.

    The entry is re-applied to the freshly-read list on every attempt — that is the whole point
    of the loop, since re-using a list read before a losing write would re-introduce the lost
    update the CAS exists to prevent. An entry with the same request id replaces rather than
    duplicating, so a Step Functions retry or an SQS redelivery does not add a second row for one
    run: the report key is a pure function of the request id and gets overwritten, so its row
    must behave the same way. Newest goes last on disk so the cap drops the oldest; the dashboard
    sorts by timestamp itself and never relies on that order.

    Args:
      bucket: The reports bucket.
      report_prefix: The request's report prefix, which determines the index key.
      summary: The assembled report summary.

    Returns:
      True only when the row was recorded. On False the report is written, the notification has
      fired and the user has a working link — so it is a lost row, not a lost check.

    Raises:
      None. Exhausting the retries, an unwritable object, a malformed summary — all are logged
      and swallowed, because the caller runs after the report has been written and the actor
      notified.
    """
    key = index_key(report_prefix)
    entry = entry_from(summary)

    for attempt in range(config.DQ_INDEX_CAS_RETRIES):
        entries, etag = _read(bucket, key)
        updated = [e for e in entries if e.get("requestId") != entry["requestId"]]
        updated.append(entry)
        updated = updated[-config.DQ_INDEX_MAX_ENTRIES :]
        try:
            _write(bucket, key, updated, etag)
            logger.info("recorded run %s in %s/%s", entry["requestId"], bucket, key)
            return True
        except Exception as err:
            if not _is_precondition(err):
                logger.exception("could not write the runs index at %s/%s", bucket, key)
                return False
            logger.info("runs index %s/%s changed under us (attempt %d)", bucket, key, attempt + 1)

    logger.warning(
        "runs index CAS exhausted after %d attempts for %s; the check succeeded and is "
        "NOT on the dashboard",
        config.DQ_INDEX_CAS_RETRIES,
        entry["requestId"],
    )
    return False
