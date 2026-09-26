"""finalise-outcomes — the state where a gate verdict becomes a statement about the user's data.

**IT EXISTS BECAUSE NO OTHER VERB CAN DO THIS.** ``delete-source`` does not run on a ``copy`` — the
graph proves there is no path — so without a dedicated step every successful item on a copy run
would arrive at the terminal still labelled ``cleared``. To the producer that words the
notification, ``cleared`` and "moved successfully" are the same record, and the difference is the
whole per-item model.

So this verb closes the vocabulary: every item that committed becomes ``moved`` / ``copied`` /
``deleted`` by operation, and every item that copied but kept its source becomes something the user
must be told about.

**A DUPLICATE IS NOT A FAILURE AND IT IS NOT A SUCCESS.** An item whose objects copied and whose
source survived leaves the user holding the data in two places — a state no earlier code in this
repo describes. It is reported under its own outcome, with the reason naming which of the two ways
it happened: the source changed under the operation, or the deletion itself did not go through.

**AND A ``delete`` THAT DID NOT DELETE IS NOT A DUPLICATE.** Nothing was copied, so "you now have it
twice" is a false sentence and ``copy_failed`` names a copy that never happened. It gets its own
outcome, which is the same "one state, one code" rule that made ``source_changed`` a REASON rather
than an outcome.

**The terminal carries everything the next specs need and nothing they would have to look up.** The
complete outcome list, the operation, both spaces as ``(kind, name)``, the destination prefix, each
item's ``targetName`` and ``kind``, and the per-item counts — read back from the transfer-results
document rather than carried on the state, because the counts are one of the three unbounded terms
that could not ride. The source space in particular is NOT derivable from an absolute key, and a
rename's ``targetName`` has no other source, so a re-submit built from this terminal would be
unbuildable without them.

The service name is the control plane, not the function, so one operation's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  _DUPLICATE_REASONS: The reasons a copied item's source can survive that a duplicate outcome
    reports as they are. Every failed deletion on an operation that copies is a duplicate; a
    reason outside this set is reported as the deletion's own failure, ``source_delete_failed``.
"""

import logging

from cpcommon import observability
from focommon import delete, notify, outcomes, plan

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-ops")

_DUPLICATE_REASONS = (delete.SOURCE_CHANGED, delete.SOURCE_DELETE_FAILED, delete.DELETE_REFUSED)


def _deletion_records(event) -> dict:
    """Reads what the deletion did, per item, from the document it wrote.

    Absent when the deletion never ran — a ``copy``, or a run where nothing was confirmed — which
    is not an error: those items committed and there was nothing to remove.

    Args:
      event: The request, carrying the transfer-results document's key when one was written.

    Returns:
      Item key to its deletion record, empty when no deletion ran.

    Raises:
      TerminalError: ``plan_unreadable`` when the document is named but unreadable.
      TransientError: On a retryable S3 fault.
    """
    key = event.get("transferResultsKey")
    if not key:
        return {}
    results = plan.load_results(key)
    return {
        record["itemKey"]: record
        for record in (results.get("deletions") or [])
        if isinstance(record, dict) and isinstance(record.get("itemKey"), str)
    }


def _counts(event) -> list:
    """Reads the per-item object counts back out of the transfer-results document.

    Read here rather than carried, because at the selection cap these are tens of kilobytes on a
    state that is already close to Step Functions' limit — and the overflow would land after the
    data had already moved.

    Args:
      event: The request.

    Returns:
      The per-item counts, empty when no transfer ran.

    Raises:
      TerminalError: ``plan_unreadable`` when the document is named but unreadable.
      TransientError: On a retryable S3 fault.
    """
    key = event.get("transferResultsKey")
    if not key:
        return []
    return plan.load_results(key).get("items") or []


def _terminal(record: dict, operation: str, deletion: dict | None) -> dict:
    """Turns one still-``cleared`` record into the terminal that describes what happened to it.

    Args:
      record: The item's outcome record as it arrived.
      operation: The operation, which decides the success word.
      deletion: What the deletion reported for this item, or None when none ran.

    Returns:
      The terminal record.

    Raises:
      None.
    """
    item_key, label = record["itemKey"], record["label"]
    failed = (deletion or {}).get("failed") or 0
    reason = (deletion or {}).get("reason") or ""

    if not failed:
        return outcomes.outcome(item_key, label, outcomes.TERMINAL_SUCCESS[operation])
    if operation == "delete":
        return outcomes.outcome(
            item_key, label, outcomes.DELETE_FAILED, reason or delete.SOURCE_DELETE_FAILED
        )
    return outcomes.outcome(
        item_key,
        label,
        outcomes.DUPLICATE,
        reason if reason in _DUPLICATE_REASONS else delete.SOURCE_DELETE_FAILED,
    )


@observability.traced("finalise-outcomes")
@notify.notifies_on_failure("finalise-outcomes")
def handler(event, context) -> dict:
    """Step Functions entry point: assigns every terminal and shapes the run's summary.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out, so
    if it were outermost the span would close as successful on an invocation that actually failed
    and notified.

    Args:
      event: The request, carrying the outcome list and whatever the transfer and deletion recorded.
      context: The Lambda context, unused.

    Returns:
      The request with every gate verdict replaced by a terminal, plus the summary block.

    Raises:
      TerminalError: ``plan_unreadable`` when the transfer-results document is named but unreadable.
      TransientError: On a retryable S3 fault.
    """
    return _finalise_outcomes(event)


def _finalise_outcomes(event) -> dict:
    """Replaces every gate verdict with a terminal and assembles the summary.

    A run in which EVERY item was skipped or refused reaches here like any other and returns the
    ordinary terminal — "nothing could be done" is a result, not a failure of the request.

    Args:
      event: The request with its outcome list.

    Returns:
      The request with the finalised outcome list and the summary.

    Raises:
      TerminalError: ``plan_unreadable``.
      TransientError: On a retryable S3 fault.
    """
    operation = event.get("operation")
    deletions = _deletion_records(event)
    arrived = [r for r in (event.get("outcomes") or []) if isinstance(r, dict)]

    final = [
        _terminal(record, operation, deletions.get(record["itemKey"]))
        if record.get("outcome") in outcomes.GATE_VERDICTS
        else record
        for record in arrived
    ]

    source, destination = event.get("source") or {}, event.get("destination") or {}
    summary = {
        "operation": operation,
        "source": {"kind": source.get("kind"), "name": source.get("name")},
        "destination": {
            "kind": destination.get("kind"),
            "name": destination.get("name"),
            "prefix": destination.get("prefix"),
        },
        "items": [
            {
                "itemKey": item.get("key"),
                "kind": item.get("kind"),
                "targetName": item.get("targetName"),
            }
            for item in (source.get("items") or [])
        ],
        "counts": _counts(event),
    }

    tally = {}
    for record in final:
        tally[record["outcome"]] = tally.get(record["outcome"], 0) + 1
    logger.info("finalised %d item(s) for %s: %s", len(final), operation, tally)
    observability.info(
        "outcomes finalised",
        actor=(event.get("actor") or {}).get("username"),
        operation=operation,
        items=len(final),
        **{f"outcome_{name}": count for name, count in tally.items()},
    )
    return {**event, "outcomes": final, "summary": summary}
