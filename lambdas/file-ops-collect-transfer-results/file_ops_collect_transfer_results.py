"""collect-transfer-results — turns a Map Run's export back into per-item outcomes and one gate.

The Distributed Map fans out over ``(item x object)`` pairs, so per-item isolation stops being a
property of a Map item and becomes this verb's job: read the run's exported results, attribute every
failed object to the item it belonged to, and decide which items may have their source removed.

**Both halves of the export are read, and that is the thing about it that surprises.** Step
Functions files a child execution by its STATUS, not by what its payload says, and the batch copier
deliberately succeeds while carrying per-item failures. A collector reading only ``FAILED_n.json``
would therefore report universal success over an incomplete copy — and here that success is what
authorises a DELETION.

**THE SKIP BRANCH IS RECOGNISED POSITIVELY, NEVER BY THE ABSENCE OF AN EXPORT.** A ``delete`` has
nothing to copy, so it reaches this verb with the Map skipped and every still-``cleared`` item is
deletable. The tempting implementation — "no Map output, therefore the skip branch" — would let a
``move`` that arrived here without an export mark every cleared item deletable, and the next state
would delete a source nothing had copied. So the operation is tested, and for a ``copy`` or a
``move`` a missing export with any cleared item is a whole-request failure.

**COUNTS AND KEYS GO TO S3, NOT ONTO THE STATE.** Measured at the selection cap, the deletable list
and the per-item counts are ~100 KB on top of a state already carrying the selection and one outcome
record per item — over Step Functions' 256 KB limit. The overflow would land on THIS verb's result,
which is after the copy: ``States.DataLimitExceeded`` escapes every ``Catch``, so the user would be
told nothing at all about an operation that had already moved their data. Only the count rides.

**Successes are derived by subtraction, never listed.** The engine reports a per-batch integer and
per-item failures; a per-item success list would be a key list by another name, and a key list is
the unbounded term.

It notifies nobody: every per-item outcome is told to the actor once, at the end, by the producer.

The service name is the control plane, not the function, so one operation's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging
from collections import Counter

from cpcommon import observability
from cpcommon.errors import TerminalError
from cpcommon.transfer import results as results_mod
from focommon import notify, outcomes, plan

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-ops")

COPY_FAILED = "copy_failed"
RESULTS_UNREADABLE = "transfer_results_unreadable"

ITEM_KEY = ("itemKey",)


def _expected(event) -> int:
    """Returns how many manifest lines the transfer was told to copy.

    Args:
      event: The request, carrying the ``transfer`` block the manifest builder wrote.

    Returns:
      The line count, or 0 when the block names none.

    Raises:
      None.
    """
    transfer = event.get("transfer")
    count = transfer.get("itemCount") if isinstance(transfer, dict) else None
    return count if isinstance(count, int) and not isinstance(count, bool) and count > 0 else 0


def _failed_counts(event, expected: int, cleared: int) -> Counter:
    """Reads the Map Run's export and counts the failed objects per selected item.

    Args:
      event: The request, carrying the ``transfer`` block and the Map state's output.
      expected: How many manifest lines were written.
      cleared: How many items were still cleared, which is what makes a zero line count either
        expected or impossible.

    Returns:
      Failed object counts keyed by item key.

    Raises:
      TerminalError: ``transfer_results_unreadable`` when items were cleared but no transfer was
        reported, or when the export cannot be read, attributed, or reconciled with the manifest.
        Whole-request, because the alternative is authorising a deletion over a copy nobody checked.
      TransientError: On a retryable S3 fault reading the export.
    """
    if not expected:
        if cleared:
            raise TerminalError(
                RESULTS_UNREADABLE,
                f"{cleared} item(s) were cleared to copy but no transfer was reported, so nothing "
                "can be said about what was copied",
            )
        return Counter()

    bucket, key = results_mod.results_location(event, unreadable_reason=RESULTS_UNREADABLE)
    outcome = results_mod.read_failed_items(
        bucket,
        key,
        batch_failure_reason=COPY_FAILED,
        unreadable_reason=RESULTS_UNREADABLE,
        echo_fields=ITEM_KEY,
    )
    if outcome["items"] != expected:
        raise TerminalError(
            RESULTS_UNREADABLE,
            f"the transfer results account for {outcome['items']} of {expected} objects, so some "
            "batches cannot be attributed to the item they belonged to",
        )
    return Counter(failure.get("itemKey") for failure in outcome["failures"])


def _planned_lines(event) -> dict:
    """Returns how many manifest lines each item contributed, as the builder recorded.

    Read from the builder's own report rather than recomputed from the plan: what has to be
    reconciled is the manifest against the plan, and deriving both sides from the plan would make
    the check a tautology.

    Args:
      event: The request, carrying the ``transfer`` block.

    Returns:
      Item key to line count.

    Raises:
      None.
    """
    transfer = event.get("transfer") if isinstance(event.get("transfer"), dict) else {}
    return {
        entry["itemKey"]: entry.get("lines")
        for entry in (transfer.get("itemLines") or [])
        if isinstance(entry, dict) and isinstance(entry.get("itemKey"), str)
    }


@observability.traced("collect-transfer-results")
@notify.notifies_on_failure("collect-transfer-results")
def handler(event, context) -> dict:
    """Step Functions entry point: attributes the transfer's failures and decides what may be
    deleted.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out, so
    if it were outermost the span would close as successful on an invocation that actually failed
    and notified. The decorator IS wanted here, unlike on the batch verb: this verb's failure is a
    whole-request one.

    Args:
      event: The request, carrying the transfer block, the Map state's output and the outcome list.
      context: The Lambda context, unused.

    Returns:
      The request with ``deletableCount``, the transfer-results document's key, and the COMPLETE
      outcome list with copy failures recorded.

    Raises:
      TerminalError: ``transfer_results_unreadable`` when the export cannot be attributed, or
        ``plan_unreadable`` / ``plan_superseded`` when the plan is not this run's.
      TransientError: On a retryable S3 fault.
    """
    return _collect_transfer_results(event)


def _collect_transfer_results(event) -> dict:
    """Counts failed objects per item, writes the results document and reports the gate's count.

    The plan is re-read because the per-item planned object counts live only there — they are what
    "every object confirmed copied" is measured against, and they are far too large to have ridden
    the state.

    Args:
      event: The request with its transfer block and Map Run output.

    Returns:
      The request with the gate's count, the results key and the updated outcome list.

    Raises:
      TerminalError: ``transfer_results_unreadable``, ``plan_unreadable`` or ``plan_superseded``.
      TransientError: On a retryable S3 fault.
    """
    operation = event.get("operation")
    loaded = plan.load(event.get("planKey"), event)
    cleared = {
        record["itemKey"]
        for record in (event.get("outcomes") or [])
        if isinstance(record, dict) and record.get("outcome") == outcomes.CLEARED
    }
    planned = {item["itemKey"]: item["objectCount"] for item in loaded["items"]}
    lines = _planned_lines(event)

    expected = _expected(event)
    counts = _failed_counts(event, expected, 0 if operation == "delete" else len(cleared))

    decided, deletable, item_counts = [], [], []
    for item_key in (key for key in planned if key in cleared):
        failed = counts.get(item_key, 0)
        short = operation != "delete" and lines.get(item_key) != planned[item_key]
        item_counts.append(
            {"itemKey": item_key, "objects": planned[item_key], "failed": failed}
        )
        if operation == "delete":
            deletable.append(item_key)
            continue
        if failed or short:
            label = next(i["label"] for i in loaded["items"] if i["itemKey"] == item_key)
            decided.append(
                outcomes.outcome(item_key, label, outcomes.COPY_FAILED, COPY_FAILED)
            )
            continue
        deletable.append(item_key)

    results_key = plan.transfer_results_key(event, (event.get("execution") or {}).get("name"))
    plan.write_results(
        results_key, {"deletable": deletable, "items": item_counts, "operation": operation}
    )

    logger.info(
        "transfer attributed for %s: %d of %d cleared item(s) may have their source removed",
        operation,
        len(deletable),
        len(cleared),
    )
    observability.info(
        "transfer results attributed",
        actor=(event.get("actor") or {}).get("username"),
        operation=operation,
        items=len(cleared),
        deletable=len(deletable),
        failed_objects=sum(counts.values()),
    )
    return {
        **event,
        "deletableCount": len(deletable),
        "transferResultsKey": results_key,
        "outcomes": outcomes.carry_forward(event.get("outcomes"), decided),
    }
