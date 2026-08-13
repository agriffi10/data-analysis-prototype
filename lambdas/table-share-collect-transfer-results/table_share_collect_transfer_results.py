"""collect-transfer-results — turns a Map Run's export back into per-recipient outcomes.

The Distributed Map fans out over ``(recipient x object)`` pairs, so per-recipient isolation
stops being a property of a Map item and becomes this verb's job: read the run's exported
results, attribute every failed item to its recipient, and emit the one per-recipient list the
rest of the machine already understands — the accepted recipients go on to ``create-table``,
the rest carry their terminal outcome to the summary.

**A recipient with even one failed item does not get a table.** A partial copy under a table
definition is worse than no table: the recipient would query a dataset silently missing rows.

**The sender is notified from here, and only for a copy failure.** Every other per-recipient
failure notifies from the failing verb's own decorator; a copy failure has no such verb since
SPEC-160, because the batch that failed spans several recipients and succeeds anyway.

The service name is the control plane, not the function, so one share's invocations and its
Map fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging
from collections import Counter

from cpcommon import errors, observability
from cpcommon.errors import TerminalError
from cpcommon.transfer import results as results_mod
from tscommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-share")

COPY_FAILED = "copy_failed"
RESULTS_UNREADABLE = "transfer_results_unreadable"


def _failed_item_counts(event) -> Counter:
    """Reads the Map Run's export and counts the failed items per recipient.

    An execution where the Choice skipped the Map has no run to read, and no items either —
    that is the "every recipient conflicted" path, not a missing export.

    **The export is checked against the manifest, not merely parsed.** The engine raises on any
    shape it does not recognise, but an export can be well-formed and still cover only some of the
    batches — and a partial export read as a clean run is the exact failure this plane must not
    have: every recipient would be told the share went well and given a table over a dataset that
    may be missing objects. So the item count the export accounts for must equal the count
    build-transfer-manifest wrote.

    Args:
      event: The request, carrying the ``transfer`` block and the Map state's output.

    Returns:
      Failed item counts keyed by ``(kind, name)`` — a destination is that pair, and nothing stops
      a shared space being named after a user, so counting on the name alone would deny one of them
      a copy the other lost.

    Raises:
      TerminalError: ``transfer_results_unreadable`` when the Map ran but its export cannot be
        read, attributed, or reconciled with the manifest. Whole-request, because the alternative
        is telling every recipient the share went well without having checked.
      TransientError: On a retryable S3 fault reading the export.
    """
    expected = (event.get("transfer") or {}).get("itemCount")
    if not expected:
        return Counter()

    bucket, key = results_mod.results_location(event, unreadable_reason=RESULTS_UNREADABLE)

    outcome = results_mod.read_failed_items(
        bucket,
        key,
        batch_failure_reason=COPY_FAILED,
        unreadable_reason=RESULTS_UNREADABLE,
    )
    if outcome["items"] != expected:
        raise TerminalError(
            RESULTS_UNREADABLE,
            f"the transfer results account for {outcome['items']} of {expected} items, so some "
            "batches cannot be attributed to a recipient",
        )
    return Counter(
        (failure.get("kind"), failure.get("recipient")) for failure in outcome["failures"]
    )


def _recipient_of(guard_record: dict) -> dict:
    """Reads a guard record's recipient, tolerating either shape the guard Map can produce.

    An accepted record carries the recipient check-target-absent resolved; a refused one
    carries the recipient as it was when the guard rejected it. Both are dicts with a kind and
    a name, which is all the outcome entry needs.

    Args:
      guard_record: One guard Map record.

    Returns:
      The recipient, or an empty mapping if the record carries none.

    Raises:
      None.
    """
    recipient = guard_record.get("recipient")
    return recipient if isinstance(recipient, dict) else {}


def _entry(guard_record: dict, failed_items: int) -> dict:
    """Shapes one recipient's outcome from its guard record and its failed item count.

    A recipient the guard already refused keeps that outcome untouched: attribution may only
    turn an accepted recipient into a failed one, never rewrite an earlier terminal or
    resurrect a refused recipient because no item of its own failed (it had none).

    Args:
      guard_record: The guard Map's record for this recipient.
      failed_items: How many of this recipient's items failed to copy.

    **The raw ``{Error, Cause}`` is decoded here and NOT carried forward**, and that is a payload
    decision rather than a tidying one. A Cause runs to hundreds of bytes with its stack, and the
    state would otherwise hold one per refused recipient three times over — in ``guardResults``,
    here, and again in the finish Map's results — against a 256 KB limit whose breach lands ON a
    Map and destroys every per-recipient outcome. The reason code is what a reader needs; the raw
    error is still in the execution history at the state that produced it.

    Args:
      guard_record: The guard Map's record for this recipient.
      failed_items: How many of this recipient's items failed to copy.

    Returns:
      A uniform outcome entry. Every key is always present — the finish Map's pass-through
      references them by path, and an absent path raises an uncatchable ``States.Runtime``.

    Raises:
      None.
    """
    recipient = _recipient_of(guard_record)
    kind, name = recipient.get("kind"), recipient.get("name")

    if guard_record.get("status") != "ok":
        return {
            "kind": kind,
            "name": name,
            "status": "failed",
            "reason": errors.failure_reason(guard_record.get("error")),
            "failedItems": 0,
            "recipient": None,
        }
    if failed_items:
        return {
            "kind": kind,
            "name": name,
            "status": "failed",
            "reason": COPY_FAILED,
            "failedItems": failed_items,
            "recipient": None,
        }
    return {
        "kind": kind,
        "name": name,
        "status": "ok",
        "reason": "",
        "failedItems": 0,
        "recipient": recipient,
    }


@observability.traced("collect-transfer-results")
@notify.notifies_on_failure("collect")
def handler(event, context) -> dict:
    """Step Functions entry point: attributes the transfer's failures to their recipients.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    Args:
      event: The request, carrying the guard Map's results, the transfer block and the Map
        state's output.
      context: The Lambda context, unused.

    Returns:
      The request with an ``outcomes`` list, one uniform entry per recipient.

    Raises:
      TerminalError: ``transfer_results_unreadable`` when the export cannot be read or a batch
        cannot be attributed.
      TransientError: On a retryable S3 fault reading the export.
    """
    return _collect_transfer_results(event)


def _collect_transfer_results(event) -> dict:
    """Counts failed items per recipient, shapes the outcomes and notifies the copy failures.

    Counts and names, never keys: this list rides the state through one more Map, and a failed-key
    list is the unbounded term that breaches the 256 KB payload limit — where the limit error lands
    ON the Map and destroys every per-recipient outcome it exists to keep.

    **``guardResults`` is consumed, not carried.** It is this verb's input and its raw
    ``{Error, Cause}`` per refused recipient is the state's heaviest per-recipient term. Leaving it
    on the state alongside the outcomes and then the finish Map's results would hold three copies
    of it at once, and a 50-recipient share where most conflict is the ordinary case, not the
    pathological one.

    Args:
      event: The request with its guard results and Map Run output.

    Returns:
      The request with its per-recipient outcome list, and without the guard results it replaces.

    Raises:
      TerminalError: ``transfer_results_unreadable`` when the export cannot be attributed.
      TransientError: On a retryable S3 fault.
    """
    counts = _failed_item_counts(event)
    guard_results = event.get("guardResults") or []
    entries = [
        _entry(record, counts.get((_recipient_of(record).get("kind"), _recipient_of(record).get("name")), 0))
        for record in guard_results
        if isinstance(record, dict)
    ]

    for entry in entries:
        if entry["reason"] == COPY_FAILED:
            notify.emit_recipient_failure(event, entry["kind"] or "", entry["name"] or "", COPY_FAILED)

    copied = sum(1 for entry in entries if entry["status"] == "ok")
    logger.info(
        "transfer attributed: %d of %d recipients copied cleanly", copied, len(entries)
    )
    observability.info(
        "transfer results attributed",
        recipients=len(entries),
        copied=copied,
        failed_items=sum(counts.values()),
    )
    return {**{k: v for k, v in event.items() if k != "guardResults"}, "outcomes": entries}
