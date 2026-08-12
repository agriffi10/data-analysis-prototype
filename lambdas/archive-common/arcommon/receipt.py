"""The receipt: the one artifact of an archive the user can actually see.

A plain UTF-8 text file in the user's own space at ``{root}archive/{uuid}/receipt.txt``,
deliberately not rendered in the browser — the project has no in-browser preview and this does
not introduce one. The user downloads it and reads it, and the UUID in it is their route to a
restore.

**Both restore fields are written from the first version, with placeholder values.** SPEC-171
rewrites the whole file when a restore is requested; a field that only appeared afterwards would
make the format conditional on the file's own history, so every reader would need to handle two
shapes of the same document.

**The paths name the space ROOT and the archive ROOT, which is a deliberate reading of FR-006.**
The spec's illustrative sample shows a selected folder as the original path, and that would be
wrong for the key layout this arc actually shipped: ``archived_key`` keeps every object's path
relative to the SPACE root, so ``alice/reports/q1.csv`` archives to ``{archiveRoot}reports/q1.csv``
whatever was selected. Naming the selected folder would pair it with an archive prefix that does
not correspond to it, and a selection of 200 items has no single original path at all. Rooted
this way the two lines are exact inverses of each other for every object, for every selection.

The byte size renders through the same rule as the file browser's ``formatSize`` — binary units,
one decimal, a TB ceiling (SPEC-155 FR-007) — so the receipt and the browser never disagree about
one number. The exact byte count rides beside it because the rounded one is not a number anybody
can reconcile against a bill.

Attributes:
  _UNITS: The unit ladder, ending at TB. The ceiling is the shared behaviour, not an oversight:
    beyond it the number keeps growing in TB rather than inventing a unit the rest of the app
    does not render.
  _LABEL_WIDTH: Column the values line up at. One space always separates a label from its value,
    so a label longer than the column still renders a readable line rather than running into it.
  _ABSENT: What an empty value renders as — something rather than nothing, so a reader can tell
    a field with no value from a field that failed to render. An ASCII hyphen rather than the em
    dash the spec's sample shows: this document is downloaded and opened in whatever the user has,
    and the same ASCII-only rule the notification wording follows costs nothing here.
"""

import logging
from datetime import datetime

from cpcommon import clients, errors

from . import messages  # noqa: F401
from .config import RECEIPT_NAME  # noqa: F401

logger = logging.getLogger(__name__)

_UNITS = ("B", "KB", "MB", "GB", "TB")

_LABEL_WIDTH = 18

_ABSENT = "-"


def human_bytes(size: int) -> str:
    """Renders a byte count the way the file browser renders it.

    Args:
      size: The byte count.

    Returns:
      The rounded size with its unit — bytes whole, everything above them to one decimal, and
      TB as the ceiling.

    Raises:
      None.
    """
    if size < 1024:
        return f"{int(size)} B"
    for power, unit in enumerate(_UNITS[1:-1], start=2):
        if size < 1024**power:
            return f"{size / 1024 ** (power - 1):.1f} {unit}"
    return f"{size / 1024 ** (len(_UNITS) - 1):.1f} {_UNITS[-1]}"


def _timestamp(started_at) -> str:
    """Renders the execution's start time as the receipt's "requested" time.

    The time comes from the CONTEXT OBJECT rather than from a clock read here, which is what
    makes the two artifacts agree: ``_manifest.json`` is written before the source is deleted and
    this file after it, so two ``now()`` calls would disagree by however long the deletion took,
    and a re-run would disagree with itself.

    Args:
      started_at: The execution's ISO-8601 start time, as Step Functions supplies it —
        including its trailing ``Z``, which ``fromisoformat`` has parsed natively since
        Python 3.11.

    Returns:
      The time as ``YYYY-MM-DD HH:MM:SS UTC``, or a placeholder when it cannot be parsed — an
      unparseable timestamp must not fail a run whose data is already safely archived.

    Raises:
      None.
    """
    if not isinstance(started_at, str) or not started_at:
        return _ABSENT
    try:
        parsed = datetime.fromisoformat(started_at)
    except ValueError:
        logger.info("the execution start time could not be parsed for the receipt")
        return _ABSENT
    return parsed.strftime("%Y-%m-%d %H:%M:%S UTC")


def _line(label: str, value: str) -> str:
    """Renders one labelled line.

    Args:
      label: The field's label, without its colon.
      value: The field's value.

    Returns:
      The line.

    Raises:
      None.
    """
    return f"{label + ':':<{_LABEL_WIDTH}} {value}"


def render(record: dict) -> str:
    """Renders the receipt's text.

    One writer for the whole document, so the format is decided in exactly one place — SPEC-171
    rewrites this file rather than appending to it, and two renderers would be two formats.

    Args:
      record: The archive's outcome — the request id, the execution's start time, the source and
        archive locations, the object count and the byte total.

    Returns:
      The receipt, ending in a newline.

    Raises:
      None. A missing field renders as a placeholder: the data is already archived by the time
      this runs, and a raise would fail a run whose only remaining work is telling the user what
      happened.
    """
    source = record.get("source") or {}
    archive = record.get("archive") or {}
    total_bytes = record.get("totalBytes") or 0
    lines = [
        _line("Requested", _timestamp(record.get("startedAt"))),
        _line("Request ID", record.get("requestId") or _ABSENT),
        _line("Original path", f"s3://{source.get('bucket')}/{source.get('root')}"),
        _line("Archived path", f"s3://{archive.get('bucket')}/{archive.get('root')}"),
        _line("Total size", f"{human_bytes(total_bytes)} ({total_bytes} bytes)"),
        _line("Files archived", str(record.get("objectCount") or 0)),
        _line("Restore requested", "No"),
        _line("Restored to", _ABSENT),
    ]
    return "\n".join(lines) + "\n"


def write(bucket: str, key: str, record: dict) -> str:
    """Writes the receipt into the space's own bucket and returns its key.

    **The key is passed in rather than derived here**, and that is SPEC-168's design being
    honoured rather than a convenience: validate-authorize resolves the archive prefix and the
    receipt key once, because they are pure functions of the request, so that the copier, the
    receipt writer and SPEC-170's restore read ONE string instead of three agreeing constructions
    of it. Deriving it again here made ``archive.receiptKey`` a field nothing read — the
    "placeholder that outlives its placeholder" the machine's own ``Validated`` state warns about.

    Args:
      bucket: The space's bucket.
      key: The receipt's key, as validate-authorize resolved it.
      record: The outcome ``render`` describes.

    Returns:
      The key the receipt was written to.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the verb — safe,
        because the key is a pure function of the request and the write is a whole-object PUT.
      ClientError: Any deterministic fault propagates, and the verb turns it into the terminal
        failure FR-006 requires: a user with no receipt has no UUID and therefore no route to a
        restore, even though their data is safely archived.
    """
    try:
        clients.s3().put_object(
            Bucket=bucket,
            Key=key,
            Body=render(record).encode(),
            ContentType="text/plain; charset=utf-8",
        )
    except Exception as err:
        errors.raise_if_transient(err, f"put {bucket}/{key}")
        raise
    return key
