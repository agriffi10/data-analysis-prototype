"""The per-space runs index — one small entry per completed check.

Without it the dashboard would have to list the reports prefix and read every report to build a
row, and S3 lists lexicographically by key, so ordering by a UUID request id gives no chronology
whatsoever. A recent-checks page would return runs in effectively random order, and sorting
properly would mean fetching every report in the space on every page load. The index makes the
whole dashboard one read.

The write is a compare-and-swap because any two checks in one space can run at once — checks of
different locations are grouped apart, and checks of one location are only started in order, since
the Pipe starts the machine fire-and-forget — so two report assemblies can read-modify-write this
object at once and one would silently lose the other's run.

The loop is ``cpcommon.cas``'s. It used to be duplicated here — the equivalent primitive lived in
a Lambda layer these functions did not attach, so it was copied and labelled "a deliberate twin,
not drift; keep the semantics identical", naming a later spec as the convergence point.
That shipped and the twin drifted anyway: this copy handled the racing 409 that the
original had not yet grown, and the caps diverged. The loop moved into
``cpcommon``, which every data-quality verb imports, so there is no twin to keep in
sync and nothing here to re-derive.

The index is a convenience, never a dependency. Every failure here is logged and swallowed. The
report is the artefact: it is already written and the notification has already fired by the time
this runs, so failing the check because its row could not be recorded would trade a real outcome
for a cosmetic one.

Every call is bounded in time as well as swallowed, because a stall is not a fault. A read that
never answers raises nothing for the swallow to catch; it holds the verb until its Lambda timeout,
which fails a check whose report is written and whose actor has been told it completed. So the
index uses ``cpcommon.clients.s3_bounded``, and every call runs under one ``cpcommon.budget``:
no call starts once ``INDEX_DEADLINE_SECONDS`` have passed and none is waited on past
``budget.CALL_CAP_SECONDS``, so the append holds the verb for at most the sum, and
``test_the_notice_and_the_index_cannot_outlast_assemble_report`` holds that, with the completion
notice's own cap, under the verb's timeout. The archive index is bounded the same way for the same
reason.

Attributes:
  INDEX_BASENAME: The index object's basename, inside a space's reports prefix.
  ENTRY_FIELDS: The keys one entry carries — deliberately the row's fields and nothing more. The
    size of this object is the dashboard's load time, since it is fetched whole on every page
    load, so putting findings in it would make the list page pay to download detail it never
    renders. The heavy findings stay in the per-run report, fetched only on drill-down. The row's
    qualifier is the incomplete flag rather than the approximate one: the approximate flag is true
    on every report, so a tag keyed to it sat on every row and told the user nothing.
  INDEX_DEADLINE_SECONDS: How long one append may keep starting calls before it gives up and
    leaves the run off the dashboard.
"""

import json
import logging

from cpcommon import budget, cas, clients

from . import config

logger = logging.getLogger()

INDEX_BASENAME = "index.json"

ENTRY_FIELDS = (
    "requestId",
    "location",
    "format",
    "verdict",
    "fileCount",
    "hasIncompleteFigures",
    "timestamp",
)

INDEX_DEADLINE_SECONDS = 5


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
        obj = clients.s3_bounded().get_object(Bucket=bucket, Key=key)
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
    clients.s3_bounded().put_object(**kwargs)


def append(bucket: str, report_prefix: str, summary: dict) -> bool:
    """Appends this run to its space's index under a compare-and-swap loop.

    The entry is re-applied to the freshly-read list on every attempt — that is the whole point
    of the loop, since re-using a list read before a losing write would re-introduce the lost
    update the CAS exists to prevent. An entry with the same request id replaces rather than
    duplicating, so a Step Functions retry or an SQS redelivery does not add a second row for one
    run: the report key is a pure function of the request id and gets overwritten, so its row
    must behave the same way. Newest goes last on disk so the cap drops the oldest; the dashboard
    sorts by timestamp itself and never relies on that order.

    ``skip_no_op=False`` keeps the loop this replaced: a redelivery whose entry reproduces the
    current document byte for byte still writes, where the shared default would return early.
    Invisible in the index, but a different set of S3 calls than this ever made.

    the rule widened what is swallowed, in the direction of the contract below rather
    than against it. The entry-replacement transform used to run outside the guard, so a
    malformed index — ``{"entries": ["x"]}`` survives the read's ``isinstance(…, list)`` check
    and then meets ``e.get(…)`` — raised out of here and failed a check that had already
    succeeded and already notified the user. It runs inside the loop now and is logged like any
    other index fault.

    Args:
      bucket: The reports bucket.
      report_prefix: The request's report prefix, which determines the index key.
      summary: The assembled report summary.

    Returns:
      True only when the row was recorded. False means it was not confirmed — at worst a lost
      row, though a write abandoned at the time cap can still land — and never a lost check: the
      report is written, the notification has fired and the user has a working link.

    Raises:
      None. Exhausting the retries, running out of time, an unwritable object, a malformed
      summary — all are logged and swallowed, because the caller runs after the report has been
      written and the actor notified.
    """
    key = index_key(report_prefix)
    entry = entry_from(summary)
    calls = budget.Budget(INDEX_DEADLINE_SECONDS, f"the runs index at {bucket}/{key}")

    def _apply(entries: list) -> list:
        """Replaces this run's row if present, appends it, and trims to the newest cap.

        Args:
          entries: The freshly-read entry list.

        Returns:
          The list to write.

        Raises:
          AttributeError: If a stored entry is not a mapping. Caught by the caller.
        """
        updated = [e for e in entries if e.get("requestId") != entry["requestId"]]
        updated.append(entry)
        return updated[-config.DQ_INDEX_MAX_ENTRIES :]

    try:
        cas.cas_mutate(
            lambda: calls.call(lambda: _read(bucket, key)),
            _apply,
            lambda entries, etag: calls.call(lambda: _write(bucket, key, entries, etag)),
            label=f"{bucket}/{key}",
            skip_no_op=False,
            on_conflict=lambda attempt: logger.info(
                "runs index %s/%s changed under us (attempt %d)", bucket, key, attempt
            ),
        )
    except cas.CasExhausted:
        logger.warning(
            "runs index CAS exhausted after %d attempts for %s; the check succeeded and is "
            "NOT on the dashboard",
            cas.MAX_ATTEMPTS,
            entry["requestId"],
        )
        return False
    except Exception:
        logger.exception("could not write the runs index at %s/%s", bucket, key)
        return False

    logger.info("recorded run %s in %s/%s", entry["requestId"], bucket, key)
    return True
