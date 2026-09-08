"""Reads a Map Run's exported results back into per-item failures.

A top-level Distributed Map's own output is a pointer — ``{MapRunArn, ResultWriterDetails}`` —
because the alternative, an array of every child's result, breaches the 256 KB state limit at
the scale the Map exists for. This module follows that pointer: the run's ``manifest.json``,
then the ``SUCCEEDED_n`` / ``FAILED_n`` / ``PENDING_n`` files it lists.

**Both paths are required, and the reason is the one thing about this export that surprises.**
Step Functions files a child by its EXECUTION STATUS, not by what its payload says. The batch
copier deliberately succeeds while carrying per-item failures, so those failures are exported
under ``SUCCEEDED`` — a collector reading only ``FAILED_n.json`` would report universal success
while a recipient received an incomplete dataset and a table over it. ``FAILED``/``PENDING``
cover the other half: an exhausted retry, a timed-out Lambda, a run stopped mid-flight, where
no output exists and attribution has to come from the child's INPUT.

An omitted payload is the third case and it is not "no failures found". Step Functions may
export a record with ``Included: false`` when a payload is too large; that record's items
cannot be attributed to anyone, so the whole request fails with a reason rather than quietly
telling every recipient it went well.

Attributes:
  MANIFEST_BASENAME: The object a Map Run's ``ResultWriter`` writes its index to.
  _SUCCEEDED: Result-file group whose records carry a per-item ``failures`` list in the output.
  _INPUT_ATTRIBUTED: Result-file groups with no usable output, attributed from the input batch.
"""

import json

from .. import clients, errors, observability
from ..errors import TerminalError

MANIFEST_BASENAME = "manifest.json"

_SUCCEEDED = "SUCCEEDED"
_INPUT_ATTRIBUTED = ("FAILED", "PENDING")


def results_location(event, *, unreadable_reason: str) -> tuple:
    """Reads where the Map Run exported its results, off the Map state's output.

    Args:
      event: The request, carrying the Map state's output under ``mapRun``.
      unreadable_reason: The caller's registered terminal reason for an unreadable export.

    Returns:
      ``(bucket, key)`` of the run's manifest.

    Raises:
      TerminalError: ``unreadable_reason`` when the Map state reported no export. The run has
        finished by the time a collector is invoked, so an absent pointer is a fault rather than
        a race, and treating it as one would retry forever against a finished run.
    """
    details = (event.get("mapRun") or {}).get("ResultWriterDetails") or {}
    bucket, key = details.get("Bucket"), details.get("Key")
    if not bucket or not key:
        raise TerminalError(
            unreadable_reason,
            "the transfer ran but its results export was not reported by the Map state",
        )
    return bucket, key


def _read_json(bucket: str, key: str, unreadable_reason: str):
    """Reads one exported result object and parses it.

    Args:
      bucket: The results bucket.
      key: The object's key.
      unreadable_reason: The domain reason code for a results export that cannot be read.

    Returns:
      The parsed object.

    Raises:
      TransientError: On a retryable S3 fault; the caller's Retry re-runs the verb.
      TerminalError: ``unreadable_reason`` when the object is absent, unreadable or not JSON.
        Absent is terminal rather than transient: the Map Run has finished by the time this
        runs, so its export is not still being written.
    """
    try:
        body = clients.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as err:
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise TerminalError(
            unreadable_reason, f"could not read transfer results {bucket}/{key}: {err}"
        ) from err
    try:
        return json.loads(body)
    except ValueError as err:
        raise TerminalError(
            unreadable_reason, f"transfer results {bucket}/{key} are not valid JSON: {err}"
        ) from err


def _payload(record: dict, field: str, unreadable_reason: str) -> dict:
    """Parses a record's ``Input`` or ``Output`` after checking it was actually exported.

    Args:
      record: One exported child-execution record.
      field: ``Input`` or ``Output``.
      unreadable_reason: The domain reason code for an unattributable record.

    Returns:
      The parsed payload.

    Raises:
      TerminalError: ``unreadable_reason`` when the payload was omitted from the export or
        cannot be parsed. Never returns an empty payload for either — an omitted batch is
        unattributable, and treating it as "no failures" is the silent success this whole
        module exists to prevent.
    """
    details = record.get(f"{field}Details")
    if isinstance(details, dict) and details.get("Included") is False:
        raise TerminalError(
            unreadable_reason,
            f"a child execution's {field} was omitted from the results export, so the items "
            "in it cannot be attributed to a recipient",
        )
    raw = record.get(field)
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        raise TerminalError(
            unreadable_reason, f"a child execution record carries no {field} to attribute"
        )
    try:
        parsed = json.loads(raw)
    except ValueError as err:
        raise TerminalError(
            unreadable_reason, f"a child execution's {field} is not valid JSON: {err}"
        ) from err
    if not isinstance(parsed, dict):
        raise TerminalError(
            unreadable_reason, f"a child execution's {field} is not an object"
        )
    return parsed


def _from_output(record: dict, unreadable_reason: str) -> tuple:
    """Reads the per-item failures a succeeded batch reported, and how many items it covered.

    The count matters as much as the failures: it is what lets the caller check that the export
    accounts for every item the manifest listed, rather than trusting that the groups this module
    knows about are the only ones there were.

    Args:
      record: One exported ``SUCCEEDED`` record.
      unreadable_reason: The domain reason code for an unattributable record.

    Returns:
      ``(failures, items covered)``.

    Raises:
      TerminalError: ``unreadable_reason`` when the output was omitted, is unparseable, or does
        not carry the batch verb's ``copied`` count.
    """
    output = _payload(record, "Output", unreadable_reason)
    copied = output.get("copied")
    raw = output.get("failures")
    failures = [entry for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []
    if not isinstance(copied, int) or isinstance(copied, bool):
        raise TerminalError(
            unreadable_reason,
            "a succeeded child execution's output carries no item count, so the export cannot be "
            "checked against the manifest",
        )
    return failures, copied + len(failures)


def _from_input(
    record: dict, batch_failure_reason: str, unreadable_reason: str, echo_fields: tuple
) -> tuple:
    """Turns a whole-batch failure into one failure entry per item it carried.

    Every item in the batch fails, including any the child had already copied before it died. That
    is fail-closed on purpose: a batch that failed as a whole reported nothing per item, so which
    of its items landed is genuinely unknown, and the conservative answer is the only honest one.

    Args:
      record: One exported ``FAILED`` or ``PENDING`` record.
      batch_failure_reason: The domain reason code for an item whose batch never completed.
      unreadable_reason: The domain reason code for an unattributable record.
      echo_fields: The manifest-line fields copied onto each failure record — the SAME set
        ``copy_batch`` echoes, because the caller joins the two halves of the export into one list
        and a record shaped differently on one half is one it cannot attribute.

    Returns:
      ``(failures, items covered)``.

    Raises:
      TerminalError: ``unreadable_reason`` when the input was omitted or is unparseable.
    """
    payload = _payload(record, "Input", unreadable_reason)
    items = payload.get("Items")
    if not isinstance(items, list):
        raise TerminalError(
            unreadable_reason,
            "a failed child execution's input carries no item batch to attribute",
        )
    failures = [
        {field: item.get(field) for field in echo_fields} | {"reason": batch_failure_reason}
        for item in items
        if isinstance(item, dict)
    ]
    return failures, len(items)


@observability.step("read-failed-items")
def read_failed_items(
    bucket: str,
    manifest_key: str,
    *,
    batch_failure_reason: str,
    unreadable_reason: str,
    echo_fields: tuple,
) -> dict:
    """Reads a Map Run's export and returns every failed item, attributed to its recipient.

    **Call bound: at most once per invocation**, in each of the four collect verbs that reach it.
    AT MOST rather than exactly: file-send, table-share and file-ops all return early when the
    request transferred nothing, so a verb can complete without reading an export. Never more
    than once — the loops below walk the export's result files INSIDE this one span rather than
    opening one each, which is what keeps a deep export two events rather than two per file.

    **Every unrecognised shape raises**, and that direction is the whole design. A reader that
    skips what it does not understand reports a clean run over an export it never read, and the
    caller then creates tables over datasets that may be missing objects. So an entry naming no
    object, a result file that is not a list of records, and a manifest listing no files are all
    terminal rather than empty — and the caller is handed the item count so it can check the
    export against the manifest it wrote.

    Args:
      bucket: The results bucket from the Map state's ``ResultWriterDetails``.
      manifest_key: The run manifest's key from the same place.
      batch_failure_reason: The reason code for an item whose whole batch failed.
      unreadable_reason: The reason code for an export that cannot be read or attributed.
      echo_fields: The manifest-line fields each failure record carries, which is the caller's
        attribution vocabulary rather than this module's. It must match what the batch verb echoed:
        the two halves of the export are joined into one list, and a record shaped differently on
        one half is one the caller cannot attribute.

    Returns:
      ``{"failures": [{<echoed fields>, "reason"}, …], "items": n}`` — ``failures`` empty when
      every item copied, ``items`` the number of manifest items the export accounted for.

    Raises:
      TransientError: On a retryable S3 fault reading the export.
      TerminalError: ``unreadable_reason`` when the run manifest or any result file is absent,
        unparseable, of an unexpected shape, or carries a record whose payload was omitted.
    """
    manifest = _read_json(bucket, manifest_key, unreadable_reason)
    result_files = manifest.get("ResultFiles")
    if not isinstance(result_files, dict):
        raise TerminalError(
            unreadable_reason, f"transfer results manifest {bucket}/{manifest_key} lists no files"
        )

    failures: list = []
    items = 0
    for group in (_SUCCEEDED, *_INPUT_ATTRIBUTED):
        for entry in result_files.get(group) or []:
            key = entry.get("Key") if isinstance(entry, dict) else None
            if not key:
                raise TerminalError(
                    unreadable_reason,
                    f"the {group} results of {bucket}/{manifest_key} name a file with no key, so "
                    "the batches in it cannot be attributed",
                )
            records = _read_json(bucket, key, unreadable_reason)
            if not isinstance(records, list):
                raise TerminalError(
                    unreadable_reason, f"transfer results {bucket}/{key} are not a list of records"
                )
            for record in records:
                found, covered = (
                    _from_output(record, unreadable_reason)
                    if group == _SUCCEEDED
                    else _from_input(
                        record, batch_failure_reason, unreadable_reason, echo_fields
                    )
                )
                failures.extend(found)
                items += covered
    return {"failures": failures, "items": items}
