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

from .. import clients, errors
from ..errors import TerminalError

MANIFEST_BASENAME = "manifest.json"

_SUCCEEDED = "SUCCEEDED"
_INPUT_ATTRIBUTED = ("FAILED", "PENDING")


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


def _failures_from_output(record: dict, unreadable_reason: str) -> list:
    """Reads the per-item failures a succeeded batch reported.

    Args:
      record: One exported ``SUCCEEDED`` record.
      unreadable_reason: The domain reason code for an unattributable record.

    Returns:
      The batch's failure entries, empty when it copied everything.

    Raises:
      TerminalError: ``unreadable_reason`` when the output was omitted or is unparseable.
    """
    output = _payload(record, "Output", unreadable_reason)
    failures = output.get("failures")
    return [entry for entry in failures if isinstance(entry, dict)] if isinstance(failures, list) else []


def _failures_from_input(record: dict, batch_failure_reason: str, unreadable_reason: str) -> list:
    """Turns a whole-batch failure into one failure entry per item it carried.

    Args:
      record: One exported ``FAILED`` or ``PENDING`` record.
      batch_failure_reason: The domain reason code for an item whose batch never completed.
      unreadable_reason: The domain reason code for an unattributable record.

    Returns:
      One entry per item in the child's input batch.

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
    return [
        {"recipient": item.get("recipient"), "reason": batch_failure_reason}
        for item in items
        if isinstance(item, dict)
    ]


def read_failed_items(
    bucket: str, manifest_key: str, *, batch_failure_reason: str, unreadable_reason: str
) -> list:
    """Reads a Map Run's export and returns every failed item, attributed to its recipient.

    Args:
      bucket: The results bucket from the Map state's ``ResultWriterDetails``.
      manifest_key: The run manifest's key from the same place.
      batch_failure_reason: The reason code for an item whose whole batch failed.
      unreadable_reason: The reason code for an export that cannot be read or attributed.

    Returns:
      ``[{"recipient": …, "reason": …}, …]`` — empty when every item copied.

    Raises:
      TransientError: On a retryable S3 fault reading the export.
      TerminalError: ``unreadable_reason`` when the run manifest or any result file is absent,
        unparseable, or carries a record whose payload was omitted.
    """
    manifest = _read_json(bucket, manifest_key, unreadable_reason)
    result_files = manifest.get("ResultFiles")
    if not isinstance(result_files, dict):
        raise TerminalError(
            unreadable_reason, f"transfer results manifest {bucket}/{manifest_key} lists no files"
        )

    failures: list = []
    for group in (_SUCCEEDED, *_INPUT_ATTRIBUTED):
        for entry in result_files.get(group) or []:
            key = entry.get("Key") if isinstance(entry, dict) else None
            if not key:
                continue
            records = _read_json(bucket, key, unreadable_reason)
            for record in records if isinstance(records, list) else []:
                if group == _SUCCEEDED:
                    failures.extend(_failures_from_output(record, unreadable_reason))
                else:
                    failures.extend(
                        _failures_from_input(record, batch_failure_reason, unreadable_reason)
                    )
    return failures
