"""The receipt: the one artifact of an archive the user can actually see.

A plain UTF-8 text file in the user's own space at ``{root}archive/{uuid}/receipt.txt``,
deliberately not rendered in the browser — the project has no in-browser preview and this does
not introduce one. The user downloads it and reads it, and the UUID in it is their route to a
restore.

**Both restore fields are written from the first version, with placeholder values.** The restore
rewrites the whole file when a restore is requested; a field that only appeared afterwards would
make the format conditional on the file's own history, so every reader would need to handle two
shapes of the same document.

**The paths name the space ROOT and the archive ROOT, which is deliberate.**
The spec's illustrative sample shows a selected folder as the original path, and that would be
wrong for the key layout this arc actually shipped: ``archived_key`` keeps every object's path
relative to the SPACE root, so ``alice/reports/q1.csv`` archives to ``{archiveRoot}reports/q1.csv``
whatever was selected. Naming the selected folder would pair it with an archive prefix that does
not correspond to it, and a selection of 200 items has no single original path at all. Rooted
this way the two lines are exact inverses of each other for every object, for every selection.

The byte size renders through the same rule as the file browser's ``formatSize`` — binary units,
one decimal, a TB ceiling — so the receipt and the browser never disagree about
one number. The exact byte count rides beside it because the rounded one is not a number anybody
can reconcile against a bill.

**the restore rewrites the two restore lines IN PLACE and touches nothing else**, which is the
only way the document can carry both halves. The archive lines record the archive run — its
start time above all, which no restore run knows and cannot recompute — so a rewrite that
re-rendered the whole file from the restore's own state would silently blank the ``Requested``
line. The rewrite is therefore keyed on the two LABELS and keeps every other line verbatim,
and ``render`` remains the only thing that decides what a fresh document looks like.

Attributes:
  RESTORE_REQUESTED_LABEL: The label the rewrite replaces with the restore's timestamp.
  RESTORED_TO_LABEL: The label the rewrite replaces with where the data landed.
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

RESTORE_REQUESTED_LABEL = "Restore requested"

RESTORED_TO_LABEL = "Restored to"

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

    One writer for the whole document, so the format is decided in exactly one place — the restore
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
        _line(RESTORE_REQUESTED_LABEL, "No"),
        _line(RESTORED_TO_LABEL, _ABSENT),
    ]
    return "\n".join(lines) + "\n"


def restore_lines(restore: dict) -> dict:
    """Renders the two restore fields' VALUES from a restore's outcome.

    Three outcomes and three sentences, and the second is the one that has to be careful. On
    ``incomplete`` the ``Restored to`` field must not name a destination as though the restore
    landed there — it records the attempt and what it left behind, so the receipt never claims a
    restore that did not finish.

    Args:
      restore: The restore's state — its ``requestedAt`` timestamp, its ``status``
        (``requested``, ``restored`` or ``incomplete``), the destination path and, on the
        incomplete path, how many objects did land.

    Returns:
      ``{label: value}`` for the two restore lines.

    Raises:
      None. A missing field renders as a placeholder, for ``render``'s own reason: by the time
      this is written the data has usually already moved, and a raise would fail a run whose
      only remaining work is telling the user what happened.
    """
    status = restore.get("status")
    destination = restore.get("destination") or _ABSENT
    if status == "restored":
        landed = destination
    elif status == "incomplete":
        landed = (
            f"Restore did not finish - {restore.get('restored') or 0} of "
            f"{restore.get('expected') or 0} file(s) were written to {destination}. "
            "The archive is intact."
        )
    else:
        landed = _ABSENT
    return {
        RESTORE_REQUESTED_LABEL: _timestamp(restore.get("requestedAt")),
        RESTORED_TO_LABEL: landed,
    }


def rewrite(text: str, restore: dict) -> str:
    """Replaces the two restore lines in an existing receipt, keeping every other line verbatim.

    **Keyed on the LABEL rather than on the line's position**, because position is a property of
    the version of ``render`` that wrote the document and the label is a property of the field.
    A receipt written by a future ``render`` with a line inserted above them still rewrites
    correctly, and one written by an older one still finds them.

    A label the document does not carry is APPENDED rather than dropped. That case is not
    reachable from anything this plane wrote — every receipt has carried both fields since
    The first version, deliberately, so the format would never be conditional on the
    file's own history — and it is handled because the alternative is a rewrite that silently
    records nothing.

    Args:
      text: The existing receipt.
      restore: The restore's state, as ``restore_lines`` describes it.

    Returns:
      The rewritten receipt, ending in a newline.

    Raises:
      None.
    """
    values = restore_lines(restore)
    seen = set()
    lines = []
    for line in text.splitlines():
        label = line.split(":", 1)[0].strip()
        if label in values:
            seen.add(label)
            lines.append(_line(label, values[label]))
        else:
            lines.append(line)
    lines.extend(_line(label, value) for label, value in values.items() if label not in seen)
    return "\n".join(lines) + "\n"


def write(bucket: str, key: str, record: dict) -> str:
    """Writes the receipt into the space's own bucket and returns its key.

    **The key is passed in rather than derived here**, and that is the design being
    honoured rather than a convenience: validate-authorize resolves the archive prefix and the
    receipt key once, because they are pure functions of the request, so that the copier, the
    receipt writer and the restore read ONE string instead of three agreeing constructions
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
        failure the rule requires: a user with no receipt has no UUID and therefore no route to a
        restore, even though their data is safely archived.
    """
    return write_text(bucket, key, render(record))


def write_text(bucket: str, key: str, text: str) -> str:
    """Puts a rendered receipt, whether it was composed fresh or rewritten.

    Args:
      bucket: The space's bucket.
      key: The receipt's key.
      text: The document.

    Returns:
      The key the receipt was written to.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any deterministic fault propagates.
    """
    try:
        clients.s3().put_object(
            Bucket=bucket,
            Key=key,
            Body=text.encode(),
            ContentType="text/plain; charset=utf-8",
        )
    except Exception as err:
        errors.raise_if_transient(err, f"put {bucket}/{key}")
        raise
    return key


def read(bucket: str, key: str) -> str | None:
    """Reads an existing receipt back, returning None only for a PROVEN absence.

    **The 404-only rule is the guard's discipline applied to a write rather than to a read**, and
    for the same reason turned around. The caller's fallback for "there is no receipt" is to
    compose a fresh one, which loses the archive's own ``Requested`` timestamp — the one field a
    restore cannot recompute. So an ambiguous answer (a 403, a fault with no status) must not
    take that branch: it raises, the state's ``Retry`` runs, and the run fails rather than
    overwriting a document it merely failed to read.

    Args:
      bucket: The space's bucket.
      key: The receipt's key.

    Returns:
      The receipt's text, or None when S3 proved it is not there.

    Raises:
      TransientError: On a throttle or 5xx.
      ClientError: On any other fault, including a 403.
    """
    try:
        body: bytes = clients.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
        return body.decode()
    except Exception as err:
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        meta = getattr(err, "response", None) or {}
        if int((meta.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0) == 404:
            logger.info("no existing receipt at %s/%s", bucket, key)
            return None
        raise
