"""collect-transfer-results — turns a Map Run's export back into per-recipient outcomes.

The Distributed Map fans out over ``(recipient x object)`` pairs, so per-recipient isolation
stops being a property of a Map item and becomes this verb's job: read the run's exported
results, attribute every failed item to its recipient, and emit the one flat per-recipient list
the terminal summary — and SPEC-167's notifications — are built from.

**Both halves of the export are read, and that is the thing about it that surprises.** Step
Functions files a child execution by its STATUS, not by what its payload says, and the batch
copier deliberately succeeds while carrying per-item failures. A collector reading only
``FAILED_n.json`` would therefore report universal success while a recipient received an
incomplete folder. ``cpcommon.transfer.results`` reads both and this verb reconciles the item
count it returns against the manifest's, because an export can be well-formed and still cover
only some of the batches.

**An earlier terminal is never overwritten.** A recipient the guard refused had its outcome
decided before any byte moved; attribution may only turn an ACCEPTED recipient into a failed
one, never resurrect a refused one because none of its items failed — it had none.

**Counts, never keys.** This list rides the state through the terminal Pass states, and a
failed-key list is the unbounded term that breaches the 256 KB payload limit — where the limit
error lands ON the Map and destroys every per-recipient outcome it exists to preserve.

It notifies nobody: every per-recipient outcome is told to the sender once, from the terminal
summary, by SPEC-167's producer.

The service name is the control plane, not the function, so one send's invocations and its Map
fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging
from collections import Counter

from cpcommon import errors, observability
from cpcommon.errors import TerminalError
from cpcommon.transfer import results as results_mod
from fscommon import notify, paths

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-send")

COPY_FAILED = "copy_failed"
RESULTS_UNREADABLE = "transfer_results_unreadable"


def _failed_item_counts(event, accepted: int) -> Counter:
    """Reads the Map Run's export and counts the failed items per recipient.

    **"No items" is only believable when no recipient was accepted**, and that distinction is
    the difference between the ordinary skip and a silent universal success. An execution where
    the Choice skipped the Map has no run to read and no items either — the "everybody was
    already holding it" path. But a ``transfer`` block that is absent, malformed, or reports
    zero items while a recipient DID clear the guard is a wiring fault, and reading it as "no
    failures" would tell every one of those recipients the send went well without a single S3
    call having been made. The manifest builder cannot produce that combination: it writes a
    line per (accepted recipient x planned object) and the plan reader refuses an empty object
    list, so an accepted recipient always means a positive item count.

    Args:
      event: The request, carrying the ``transfer`` block and the Map state's output.
      accepted: How many recipients cleared the guard, which is what makes a zero item count
        either expected or impossible.

    Returns:
      Failed item counts keyed by ``(kind, name)``. A destination is that pair: nothing stops a
      shared space being named after a user, so counting on the name alone would deny one of
      them a copy the other lost.

    Raises:
      TerminalError: ``transfer_results_unreadable`` when a recipient was accepted but no
        transfer was reported, or when the Map ran and its export cannot be read, attributed, or
        reconciled with the manifest. Whole-request, because the alternative is telling every
        recipient the send went well without having checked.
      TransientError: On a retryable S3 fault reading the export.
    """
    transfer = event.get("transfer")
    expected = transfer.get("itemCount") if isinstance(transfer, dict) else None
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        expected = None
    if not expected:
        if accepted:
            raise TerminalError(
                RESULTS_UNREADABLE,
                f"{accepted} recipient(s) cleared the guard but no transfer was reported, so "
                "nothing can be said about what they received",
            )
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


def _recipient_of(record: dict) -> dict:
    """Reads a guard record's recipient, tolerating either shape the guard Map can produce.

    A cleared record carries the recipient check-target-absent resolved; a refused one carries
    it as it was annotated upstream. Both name a kind and a name, which is all an outcome needs.

    Args:
      record: One guard Map record.

    Returns:
      The recipient, or an empty mapping when the record carries none.

    Raises:
      None.
    """
    recipient = record.get("recipient")
    return recipient if isinstance(recipient, dict) else {}


def _refusal_reason(record: dict) -> str:
    """Reads why a recipient was refused, from whichever of the two shapes recorded it.

    The guard returns its EXPECTED refusals as data — an unresolved recipient, a name conflict —
    so those carry a reason string already. Its Map item's ``Catch`` produces the other shape for
    a fault nobody predicted, and that one carries the raw Step Functions ``{Error, Cause}``,
    which only ``cpcommon.errors.failure_reason`` may decode (never ASL: ``States.StringToJson``
    raises an uncatchable ``States.Runtime`` on a Cause that is absent or not JSON).

    Args:
      record: One refused guard record.

    Returns:
      The stable reason code; never empty, so the sender's message always resolves to a
      sentence.

    Raises:
      None.
    """
    reason = record.get("reason")
    if isinstance(reason, str) and reason:
        return reason
    return errors.failure_reason(record.get("error"))


def _entry(record: dict, failed_items: int) -> dict:
    """Shapes one recipient's outcome from its guard record and its failed item count.

    The raw ``{Error, Cause}`` is decoded here and NOT carried forward, which is a payload
    decision rather than a tidying one: a Cause runs to hundreds of bytes with its stack, and
    carrying it would put a second copy of every refusal on a state already holding the guard's.

    Args:
      record: The guard Map's record for this recipient.
      failed_items: How many of this recipient's items failed to copy.

    Returns:
      A uniform outcome entry — every key always present, because the terminal Pass states
      reference them by path and an absent path raises an uncatchable ``States.Runtime``.

    Raises:
      None.
    """
    recipient = _recipient_of(record)
    kind, name = recipient.get("kind"), recipient.get("name")

    if record.get("status") != "ok":
        return {
            "kind": kind,
            "name": name,
            "status": "failed",
            "reason": _refusal_reason(record),
            "detail": record.get("detail") or "",
            "failedItems": 0,
        }
    if failed_items:
        return {
            "kind": kind,
            "name": name,
            "status": "failed",
            "reason": COPY_FAILED,
            "detail": "",
            "failedItems": failed_items,
        }
    return {"kind": kind, "name": name, "status": "ok", "reason": "", "detail": "", "failedItems": 0}


def _item_names(event) -> list:
    """Derives the names the send delivered under, for the terminal summary.

    Here rather than in a Pass state because ASL cannot map keys to their last segment, and here
    rather than upstream because this is the LAST state holding the selection they come from —
    ShapeSummary drops it, and SPEC-167's notification names them to both parties.

    Args:
      event: The request, carrying the authorized source and its normalised items.

    Returns:
      The item names, in selection order. Empty when the selection is absent, which is not worth
      failing a completed transfer over: by this point the copy has happened, and a summary with
      no names is a worse notification, not a wrong outcome.

    Raises:
      None. ``item_name`` refuses a key with no final segment, but nothing that reached this
      state can carry one — validate-authorize refused it and the guard would have failed on it
      — so a raise here would turn a successful send into a whole-request failure over wording.
    """
    names = []
    for item in ((event.get("source") or {}).get("items") or []):
        try:
            names.append(paths.item_name(item.get("key") or ""))
        except Exception:  # noqa: BLE001
            logger.info("an item key had no name; leaving it out of the summary")
    return names


@observability.traced("collect-transfer-results")
@notify.notifies_on_failure("collect")
def handler(event, context) -> dict:
    """Step Functions entry point: attributes the transfer's failures to their recipients.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified. The decorator IS wanted here, unlike on the per-recipient verbs: this
    verb's failure is a whole-request one, and the machine's own notify-failure state suppresses
    a terminal error precisely because it assumes the decorator already spoke.

    Args:
      event: The request, carrying the guard Map's results, the transfer block and the Map
        state's output.
      context: The Lambda context, unused.

    Returns:
      The request with an ``outcomes`` list — one uniform entry per recipient — and the item
      names the summary reports.

    Raises:
      TerminalError: ``transfer_results_unreadable`` when the export cannot be read or a batch
        cannot be attributed.
      TransientError: On a retryable S3 fault reading the export.
    """
    return _collect_transfer_results(event)


def _collect_transfer_results(event) -> dict:
    """Counts failed items per recipient and shapes the per-recipient outcomes.

    ``guardResults`` and ``source`` are both CONSUMED rather than carried, and for one reason:
    this verb's output is the state, and the state has a 256 KB limit whose breach is
    uncatchable. ``guardResults`` holds a raw ``{Error, Cause}`` per faulted recipient, and
    ``source`` holds the whole selection — which the item names replace here, since they are
    derived from it and are what the summary reports. Carrying both alongside ``itemNames``
    would put two copies of the selection on one state at the moment the run is otherwise
    finished.

    Args:
      event: The request with its guard results and Map Run output.

    Returns:
      The request with its per-recipient outcome list and the item names, and without the guard
      results or the selection they replace.

    Raises:
      TerminalError: ``transfer_results_unreadable`` when the export cannot be attributed.
      TransientError: On a retryable S3 fault.
    """
    records = [record for record in event.get("guardResults") or [] if isinstance(record, dict)]
    counts = _failed_item_counts(event, sum(1 for r in records if r.get("status") == "ok"))
    entries = [
        _entry(
            record,
            counts.get(
                (_recipient_of(record).get("kind"), _recipient_of(record).get("name")), 0
            ),
        )
        for record in records
    ]

    delivered = sum(1 for entry in entries if entry["status"] == "ok")
    logger.info("transfer attributed: %d of %d recipients received cleanly", delivered, len(entries))
    observability.info(
        "transfer results attributed",
        recipients=len(entries),
        delivered=delivered,
        failed_items=sum(counts.values()),
    )
    names = _item_names(event)
    return {
        **{key: value for key, value in event.items() if key not in ("guardResults", "source")},
        "itemNames": names,
        "outcomes": entries,
    }
