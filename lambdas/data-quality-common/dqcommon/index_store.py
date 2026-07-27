"""The per-space runs index — one small entry per completed check (SPEC-123 FR-001).

WHY AN INDEX EXISTS AT ALL. Without it the dashboard would have to list
``{space}/_data-quality-reports/`` and GET every ``report.json`` to build a row — one GET
per row — and S3 lists **lexicographically by key**, so ordering by ``requestId`` (a UUID)
gives NO chronology whatsoever. A "recent checks" page would return runs in effectively
random order, and sorting properly would mean fetching every report in the space on every
page load. The index makes the whole dashboard ONE GET.

WHY THE WRITE IS A CAS. Checks of DIFFERENT locations run in parallel — the request queue's
``MessageGroupId`` is the hashed location, so only same-location checks serialize — which
means two ``assemble-report`` invocations can read-modify-write this object at once and one
would silently lose the other's run. That is the same lost-update race SPEC-082 fixed in the
shared-space registry, and this is the same fix: optimistic ETag compare-and-swap with
bounded retry.

WHY THE LOOP IS DUPLICATED HERE. ``shared-space-common/casio.py`` already owns this
discipline, but it is in a DIFFERENT LAMBDA LAYER: the data-quality functions attach
cpcommon + dqcommon (+ polars) and never shared-space-common, so importing it would fail at
cold start. SPEC-125 (fold ``shared-space-common`` onto ``cpcommon``) is where the two
converge; until then this is a deliberate twin, not drift. Keep the semantics identical.

THE INDEX IS A CONVENIENCE, NEVER A DEPENDENCY. Every failure here — an exhausted CAS, an
unreadable object, a write error — is logged and swallowed. The report is the artefact: it
is already written and the notification has already fired by the time this runs, so failing
the check because its *row* could not be recorded would trade a real outcome for a
cosmetic one.
"""

import json
import logging

from cpcommon import clients

from . import config

logger = logging.getLogger()

#: The index object's basename, inside a space's reports prefix.
INDEX_BASENAME = "index.json"

#: The keys one entry carries — deliberately the row's fields and nothing more.
#
# THE SIZE OF THIS OBJECT IS THE DASHBOARD'S LOAD TIME. It is fetched whole on every page
# load, so putting findings (top issues, per-column figures) in it would make the list page
# pay to download detail it never renders. The heavy findings stay in the per-run report,
# fetched only on drill-down.
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
    """``{space}/_data-quality-reports/index.json`` from a request's report prefix.

    The prefix threaded on the state is per-REQUEST
    (``{space}/_data-quality-reports/{requestId}/``); the index is per-SPACE, one level up.
    """
    trimmed = report_prefix.strip("/")
    parent = trimmed.rsplit("/", 1)[0] if "/" in trimmed else trimmed
    return f"{parent}/{INDEX_BASENAME}"


def entry_from(summary: dict) -> dict:
    """Project ``assemble-report``'s summary onto the entry's fields.

    Built by whitelist, never by copying the event: the summary carries the whole threaded
    request (tokens, bucket names, query ids), and a blacklist would leak whichever field
    a later spec adds.
    """
    entry = {field: summary.get(field) for field in ENTRY_FIELDS if field != "timestamp"}
    entry["timestamp"] = summary.get("completedAt")
    return entry


def _read(bucket: str, key: str) -> tuple[list, str | None]:
    """Return ``(entries, etag)``; a missing or unparseable index reads as empty.

    A CORRUPT INDEX IS REBUILT, NOT AN ERROR. The alternative — failing, or refusing to
    write — would mean one bad object permanently stops a space from recording new runs,
    and the entries it would preserve are a convenience whose source of truth (the report
    objects) is intact. The ETag is still returned so the rebuild goes through the same CAS
    and cannot clobber a writer who fixed it in the meantime.
    """
    try:
        obj = clients.s3().get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read()
        etag = obj.get("ETag")
    except Exception as err:  # noqa: BLE001 - absent is the common case, not an error
        logger.info("no readable runs index at %s/%s (%s); starting a new one", bucket, key, err)
        return [], None

    try:
        document = json.loads(body)
        entries = document["entries"]
        if not isinstance(entries, list):
            raise TypeError("entries is not a list")
    except Exception:  # noqa: BLE001 - a corrupt index rebuilds (see docstring)
        logger.warning("runs index at %s/%s is unreadable; rebuilding it", bucket, key)
        return [], etag
    return entries, etag


def _write(bucket: str, key: str, entries: list, etag: str | None) -> None:
    """Conditionally PUT the index: ``If-Match`` the read ETag, or ``If-None-Match: *``.

    Raises the client's error on a precondition failure so the CAS loop can retry.
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
    """True when a conditional PutObject lost to a concurrent writer.

    ``PreconditionFailed``/412 is If-Match losing; ``ConditionalRequestConflict``/409 is
    what S3 returns when two If-None-Match creates race. Both mean "someone else committed
    first, re-read and re-apply" — treating the 409 as a hard error would drop the FIRST
    run a space ever records, which is the one case where the index does not exist yet and
    two parallel checks are most likely to create it simultaneously.
    """
    code = str(((getattr(exc, "response", {}) or {}).get("Error") or {}).get("Code", ""))
    return code in ("PreconditionFailed", "412", "ConditionalRequestConflict", "409")


def append(bucket: str, report_prefix: str, summary: dict) -> bool:
    """Append this run to its space's index under CAS. Returns True iff it was recorded.

    NEVER RAISES. Exhausting the retries, an unwritable object, a malformed summary — all
    are logged and swallowed, because the caller is ``assemble-report`` AFTER the report
    has been written and the actor notified. See the module docstring.
    """
    key = index_key(report_prefix)
    entry = entry_from(summary)

    for attempt in range(config.DQ_INDEX_CAS_RETRIES):
        entries, etag = _read(bucket, key)
        # RE-APPLIED TO THE FRESHLY-READ LIST on every attempt — that is the whole point of
        # the loop. Re-using a list read before a losing write would re-introduce the
        # lost update the CAS exists to prevent.
        #
        # Same-requestId replacement keeps a Step Functions Retry or an SQS redelivery from
        # adding a second row for one run: the report key is a pure function of requestId
        # and gets overwritten, so its row must behave the same way.
        updated = [e for e in entries if e.get("requestId") != entry["requestId"]]
        updated.append(entry)
        # Newest last on disk, so the cap drops the OLDEST. The dashboard sorts by
        # timestamp itself and never relies on this order.
        updated = updated[-config.DQ_INDEX_MAX_ENTRIES :]
        try:
            _write(bucket, key, updated, etag)
            logger.info("recorded run %s in %s/%s", entry["requestId"], bucket, key)
            return True
        except Exception as err:  # convenience write; never fails the check
            if not _is_precondition(err):
                logger.exception("could not write the runs index at %s/%s", bucket, key)
                return False
            logger.info("runs index %s/%s changed under us (attempt %d)", bucket, key, attempt + 1)

    # THE RUN IS SIMPLY MISSING FROM THE DASHBOARD. The report is written, the notification
    # has fired, and the user has a working link — so this is a lost row, not a lost check.
    logger.warning(
        "runs index CAS exhausted after %d attempts for %s; the check succeeded and is "
        "NOT on the dashboard",
        config.DQ_INDEX_CAS_RETRIES,
        entry["requestId"],
    )
    return False
