"""collect-transfer-results — the commit gate's verdict, and the only place it is decided.

The whole spec turns on one rule: **the source is deleted only when every single object has been
confirmed copied.** This verb is where "every single object" is established. It reads the Map
Run's exported results, counts what actually landed, reconciles that against the plan, and returns
a BOOLEAN — every object copied, or not. The ASL Choice after it has one arm that reaches
delete-source and one that does not.

**Both halves of the export are read, and that is the thing about it that surprises.** Step
Functions files a child execution by its STATUS, not by what its payload says, and the batch
copier deliberately succeeds while carrying per-item failures. A collector reading only
``FAILED_n.json`` would report universal success over an incomplete archive — and here that
reported success is a deletion.

**Three ways to be short, and all three are the same verdict.** A reported item failure; an export
that accounts for fewer items than the manifest listed; a manifest that does not match the plan it
was built from. The last two are wiring faults rather than copy faults, and they take the rollback
branch rather than raising, because the outcome that matters is identical: the archive copy is
partial, so it is removed and the source is left exactly where it was.

**What it deliberately does NOT do is attribute.** File-send's collector turns item failures back
into per-recipient outcomes; an archive has one destination, so there is nobody to attribute to
and the counts are the whole answer. That is also why the copy verb's empty ``recipient`` fields
are correct rather than a gap.

**It counts one KIND of failure apart from the rest, and that count changes no verdict.** An item
the copy declined to overwrite is short exactly as a failed copy is short, so ``complete`` is
false either way and the restore gate routes to the arm that deletes nothing. What the separate
count buys is downstream: the receipt and the notification can say a file was left alone rather
than that it could not be copied. The field rides on BOTH arms and is zero on the archive's,
because only the restore's manifest asks for a conditional write — a field present on one arm and
absent on the other is the shape a reader has to branch on.

The service name is the control plane, not the function, so one archive's invocations and its Map
fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import notify
from cpcommon import observability
from cpcommon.errors import TerminalError
from cpcommon.transfer import results as results_mod

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")

COPY_FAILED = "copy_failed"
DESTINATION_OCCUPIED = "destination_occupied_during_copy"
RESULTS_UNREADABLE = "transfer_results_unreadable"


def _expected_items(event) -> int:
    """Reads how many items the transfer was supposed to move, refusing every unusable shape.

    **The manifest's count is checked against the PLAN's**, which is a check file-send cannot
    make: there a manifest line is one ``(recipient, object)`` pair, so the two counts differ by
    design. Here they are the same number written twice, and a disagreement means the manifest
    was built from something other than the plan this run expanded — the one shape where every
    downstream count would agree with itself and be wrong.

    Args:
      event: The request, carrying the ``transfer`` block and the plan's object count.

    Returns:
      The item count the export must account for.

    Raises:
      TerminalError: ``transfer_results_unreadable`` when the transfer block is absent or
        malformed, reports no items, or disagrees with the plan. Reached only after the Map has
        run — the zero case is refused before it, at the Choice, because an archive of nothing is
        a refusal and never a success.
    """
    transfer = event.get("transfer")
    expected = transfer.get("itemCount") if isinstance(transfer, dict) else None
    if not isinstance(expected, int) or isinstance(expected, bool) or expected <= 0:
        raise TerminalError(
            RESULTS_UNREADABLE,
            "the transfer ran but reported no item count, so nothing can be said about what was "
            "copied",
        )
    planned = event.get("objectCount")
    if expected != planned:
        raise TerminalError(
            RESULTS_UNREADABLE,
            f"the transfer manifest holds {expected} items but the copy plan recorded "
            f"{planned!r} objects",
        )
    return expected


@observability.traced("collect-transfer-results")
@notify.notifies_on_failure("collect")
def handler(event, context) -> dict:
    """Step Functions entry point: decides whether every object was copied.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The request, carrying the transfer block and the Map state's output.
      context: The Lambda context, unused.

    Returns:
      The request with a ``transferOutcome`` block — how many objects copied, how many did not,
      and the boolean the commit gate branches on.

    Raises:
      TerminalError: ``transfer_results_unreadable`` when the export cannot be read at all, or
        when the transfer's own counts are unusable. The source is untouched on this path, which
        is the property that matters; the partial archive copy is left to the bucket's own
        lifecycle rather than rolled back, because a collector that cannot read the export cannot
        say what there is to roll back.
      TransientError: On a retryable S3 fault reading the export.
    """
    return _collect_transfer_results(event)


def _collect_transfer_results(event) -> dict:
    """Reads the export, counts the failures and returns the verdict.

    Args:
      event: The request with its transfer block and Map Run output.

    Returns:
      The request with its ``transferOutcome``.

    Raises:
      TerminalError: ``transfer_results_unreadable``.
      TransientError: On a retryable S3 fault.
    """
    expected = _expected_items(event)
    bucket, key = results_mod.results_location(event, unreadable_reason=RESULTS_UNREADABLE)

    outcome = results_mod.read_failed_items(
        bucket,
        key,
        batch_failure_reason=COPY_FAILED,
        unreadable_reason=RESULTS_UNREADABLE,
        echo_fields=(),
    )
    failed = len(outcome["failures"])
    occupied = sum(1 for item in outcome["failures"] if item.get("reason") == DESTINATION_OCCUPIED)
    unaccounted = expected - outcome["items"]
    copied = outcome["items"] - failed
    complete = failed == 0 and unaccounted == 0

    logger.info(
        "transfer verdict: %d copied, %d failed (%d occupied), %d unaccounted of %d planned",
        copied,
        failed,
        occupied,
        unaccounted,
        expected,
    )
    observability.info(
        "transfer results collected",
        objects=copied,
        failed=failed,
        occupied=occupied,
        unaccounted=unaccounted,
        expected=expected,
        complete=complete,
    )
    return {
        **event,
        "transferOutcome": {
            "copied": copied,
            "failed": failed + max(unaccounted, 0),
            "expected": expected,
            "occupied": occupied,
            "complete": complete,
        },
    }
