"""The per-space archive index — one small entry per archive, so the restore list can label it.

``{root}system_settings/archive/index.json`` in the space's own bucket, beside the receipt
folders, where users can read and cannot write. The browser lists the receipt folders to learn
which archives exist and reads this one document to learn what to call them: a name, when the
archive was made and by whom, what it held, and what its last restore did.

**The index is a label and never a dependency — the receipt folder is the authority.** Every
failure here is logged and swallowed, the same stance as ``dqcommon.index_store``: by the time
anything is recorded the archive has completed or the restore has moved, and failing a run
because its label could not be written would trade a real outcome for a cosmetic one. An archive
with no entry still appears in the restore list, unlabelled, and is restored exactly as before.

**Every write is a compare-and-swap** (``cpcommon.cas``), because every archive of a space shares
this one object and two can finish at the same moment. Entries are keyed on the archive id, so a
retried verb replaces its own row rather than adding a second.

**Three readings of what is there, and they are treated differently.** A proven absence starts a
new document. A document that is not JSON, or is version 1 with the wrong shape, is REBUILT by the
archive side — users cannot write this folder, so an index left corrupt would switch labels off
for the space for good — and left alone by the restore side, which has only a row to change. A
document of a HIGHER version came from a newer build and is never overwritten by either. Any
other read fault, a 403 above all, raises into the caller's catch rather than being read as
absence: the conditional write would refuse the overwrite anyway, but a fault is not a reason to
try.

**Serialized unescaped, with compact separators, and that is paired with the entry cap.** The
browser fetches the whole document through the object content route, whose stored cap and
Lambda's response ceiling both bind; escaped, a full index of worst-case entries passed both.
``lambdas/test_archive_index_fits_the_read_route.py`` builds the worst case and measures it.

Attributes:
  INDEX_VERSION: The document version this build reads and writes.
  ITEMS_SHOWN: How many of the selected items an entry names — the restore list's "reports/,
    q1.csv and 1 more". The selection can hold two hundred; the index is fetched whole on every
    opening of the list, so it carries the few a row shows and the count.
  ITEM_PATH_MAX_CHARS: The longest item path an entry keeps, in code points, before it is cut
    with an ellipsis. A key may be 1,024 bytes; a row shows a fraction of that.
  ELLIPSIS: What a cut path ends with.
  RESTORE_STATUSES: The three stages ``update-receipt`` records, and nothing else.
  _CORRUPT: The reading of a document that is not a version-1 index.
  _NEWER: The reading of a document written by a newer build.
"""

import json
import logging
from datetime import UTC, datetime

from cpcommon import cas, clients, errors

from .config import ARCHIVE_INDEX_MAX_ENTRIES

logger = logging.getLogger(__name__)

INDEX_VERSION = 1

ITEMS_SHOWN = 3

ITEM_PATH_MAX_CHARS = 200

ELLIPSIS = "…"

RESTORE_STATUSES = frozenset({"requested", "restored", "incomplete"})

_CORRUPT = object()

_NEWER = object()


def _cut(path: str) -> str:
    """Shortens an item path to the longest an entry keeps.

    Args:
      path: The item's path relative to the space root.

    Returns:
      The path, or its first code points followed by an ellipsis.

    Raises:
      None.
    """
    if len(path) <= ITEM_PATH_MAX_CHARS:
        return path
    return path[: ITEM_PATH_MAX_CHARS - 1] + ELLIPSIS


def entry_from(event: dict, file_count: int) -> dict:
    """Builds an archive's index entry from write-receipt's state.

    Every field comes off the state the archive run already carries, so the entry and the receipt
    written a moment earlier cannot disagree: the start time is the receipt's ``Requested`` line,
    and the file count is the one the receipt and the notification name.

    Args:
      event: The archive run's state at write-receipt — the request id, the actor, the
        authorized source with its normalised selection, the archive block with its name, the
        execution stamp and the byte total.
      file_count: The archive's file count, as ``counts.file_count`` gives it.

    Returns:
      The entry, with ``restore`` None.

    Raises:
      None. A missing field is recorded as absent: the archive has completed, and a label is
      not a reason to fail it.
    """
    source = event.get("source") or {}
    archive = event.get("archive") or {}
    root = source.get("root") or ""
    selection = source.get("items") or []
    items = []
    for item in selection[:ITEMS_SHOWN]:
        key = item.get("key") or ""
        path = key[len(root) :] if root and key.startswith(root) else key
        items.append({"kind": item.get("kind"), "path": _cut(path)})
    return {
        "archiveId": event.get("requestId"),
        "name": archive.get("name"),
        "archivedAt": (event.get("execution") or {}).get("startedAt"),
        "archivedBy": (event.get("actor") or {}).get("username"),
        "items": items,
        "itemCount": len(selection),
        "fileCount": file_count,
        "totalBytes": event.get("totalBytes") or 0,
        "restore": None,
    }


def _is_absent(err: Exception) -> bool:
    """Reports whether a read fault proves the index does not exist.

    Args:
      err: The fault the read raised.

    Returns:
      True for a 404 or a ``NoSuchKey``, and for nothing else — a 403 is not an absence.

    Raises:
      None.
    """
    meta = getattr(err, "response", None) or {}
    status = int((meta.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0)
    return status == 404 or errors.error_code(err) in {"NoSuchKey", "404", "NotFound"}


def _read(bucket: str, key: str) -> tuple:
    """Reads the index and its entity tag, and says which of the readings it is.

    Args:
      bucket: The space's bucket.
      key: The index key.

    Returns:
      ``(document, etag)`` — the document is None for a proven absence, ``_CORRUPT`` for one
      that is not a version-1 index, ``_NEWER`` for one of a higher version, and the parsed
      document otherwise.

    Raises:
      Exception: Any read fault that does not prove absence, so the caller swallows it rather
        than writing over a document it could not see.
    """
    try:
        stored = clients.s3().get_object(Bucket=bucket, Key=key)
    except Exception as err:
        if _is_absent(err):
            return None, None
        raise
    etag = stored.get("ETag")
    try:
        document = json.loads(stored["Body"].read())
    except ValueError:
        return _CORRUPT, etag
    version = document.get("version") if isinstance(document, dict) else None
    if isinstance(version, int) and not isinstance(version, bool) and version > INDEX_VERSION:
        return _NEWER, etag
    archives = document.get("archives") if isinstance(document, dict) else None
    well_formed = (
        version == INDEX_VERSION
        and isinstance(archives, list)
        and all(isinstance(entry, dict) for entry in archives)
    )
    return (document if well_formed else _CORRUPT), etag


def _write(bucket: str, key: str, document: dict, etag: str | None) -> None:
    """Writes the index conditionally on the tag it was read at.

    Args:
      bucket: The space's bucket.
      key: The index key.
      document: The whole document to write.
      etag: The tag to match, or None to write only if the object is absent.

    Returns:
      None.

    Raises:
      ClientError: On a precondition failure, so the loop re-reads, or any other S3 fault.
    """
    body = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    kwargs = {"Bucket": bucket, "Key": key, "Body": body, "ContentType": "application/json"}
    if etag is None:
        kwargs["IfNoneMatch"] = "*"
    else:
        kwargs["IfMatch"] = etag
    clients.s3().put_object(**kwargs)


def _mutate(bucket: str, key: str, apply, archive_id) -> bool:
    """Runs one compare-and-swap over the index, swallowing every way it can fail.

    Args:
      bucket: The space's bucket.
      key: The index key.
      apply: The transform over what ``_read`` returns; returning its input unchanged writes
        nothing.
      archive_id: The archive the change is about, for the log.

    Returns:
      True when the loop finished, whether it wrote or found nothing to change; False when it
      failed.

    Raises:
      None.
    """
    try:
        cas.cas_mutate(
            lambda: _read(bucket, key),
            apply,
            lambda document, etag: _write(bucket, key, document, etag),
            label=f"{bucket}/{key}",
            on_conflict=lambda attempt: logger.info(
                "archive index %s/%s changed under us (attempt %d)", bucket, key, attempt
            ),
        )
    except cas.CasExhausted:
        logger.warning(
            "archive index CAS exhausted for %s; the archive is unlabelled in the restore list",
            archive_id,
        )
        return False
    except Exception:
        logger.exception("could not update the archive index at %s/%s", bucket, key)
        return False
    return True


def record_archive(bucket, key, build_entry) -> bool:
    """Records a completed archive in its space's index.

    The entry is BUILT here, inside the boundary that swallows, rather than by the caller: by the
    time this runs the source is deleted and the receipt written, so even a state shaped in a way
    nobody anticipated must cost the label and not the run.

    Args:
      bucket: The space's bucket.
      key: The index key, as validate-authorize resolved it; None skips the index — a run
        validated before the key existed can reach this verb after a deploy.
      build_entry: Returns the entry, as ``entry_from`` builds it.

    Returns:
      True when the entry was recorded.

    Raises:
      None.
    """
    if not bucket or not key:
        logger.info("no archive index key on the state; the archive is not labelled")
        return False
    try:
        entry = build_entry()
    except Exception:
        logger.exception("could not build the archive's index entry; it is not labelled")
        return False

    def _apply(document):
        """Replaces this archive's row, appends it, and keeps the newest entries.

        Args:
          document: What ``_read`` returned.

        Returns:
          The document to write, or ``_NEWER`` unchanged so nothing is written.

        Raises:
          None.
        """
        if document is _NEWER:
            return document
        archives = [] if document is None or document is _CORRUPT else document["archives"]
        kept = [row for row in archives if row.get("archiveId") != entry["archiveId"]]
        kept.append(entry)
        return {"version": INDEX_VERSION, "archives": kept[-ARCHIVE_INDEX_MAX_ENTRIES:]}

    return _mutate(bucket, key, _apply, entry.get("archiveId"))


def record_restore(bucket, key, archive_id, status: str, requested_at) -> bool:
    """Records what a restore did on the archive's existing entry.

    **Rows are never created from this side.** An archive with no entry — made before the index
    existed, or dropped past the cap — stays unlabelled, rather than gaining a row that knows a
    restore happened and nothing about the archive it was of.

    Args:
      bucket: The space's bucket.
      key: The index key; None skips the index, for the same deploy-skew reason as
        ``record_archive``.
      archive_id: The archive the restore is of.
      status: ``requested``, ``restored`` or ``incomplete``.
      requested_at: The restore execution's start time, which the ASL seeds on every stage.

    Returns:
      True when the loop finished, whether or not there was an entry to change.

    Raises:
      None.
    """
    if not bucket or not key or status not in RESTORE_STATUSES:
        logger.info("no archive index key or no known status; the restore is not labelled")
        return False
    updated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _apply(document):
        """Sets the restore on this archive's row, when the document and the row both exist.

        Args:
          document: What ``_read`` returned.

        Returns:
          The document to write, or the input unchanged so nothing is written.

        Raises:
          None.
        """
        if document is None or document is _CORRUPT or document is _NEWER:
            return document
        archives = document["archives"]
        if not any(row.get("archiveId") == archive_id for row in archives):
            return document
        restore = {"status": status, "requestedAt": requested_at, "updatedAt": updated_at}
        return {
            **document,
            "archives": [
                {**row, "restore": restore} if row.get("archiveId") == archive_id else row
                for row in archives
            ],
        }

    return _mutate(bucket, key, _apply, archive_id)
