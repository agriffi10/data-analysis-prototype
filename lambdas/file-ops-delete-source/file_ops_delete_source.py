"""delete-source — the only verb in this plane that removes a user's own files.

It runs on the committing arm of the gate and is unreachable from the other. What it deletes is
exactly the PLAN's keys, for exactly the items the collector confirmed, and it re-reads both from S3
because neither could ride the state.

**A PLAN RE-READ IS NOT A PREFIX LISTING, AND THAT DISTINCTION IS THE WHOLE RULE.** This plane's
lock serialises its own executions and nothing else — not the browser's uploads, not create-folder,
not the six other control planes, all of which write the same prefixes. So an object written into a
source folder between the expansion and the commit was never copied, and a prefix-listing delete
would remove it silently and unrecoverably, versioning off. Deleting the plan's keys leaves that
object behind as an orphan, which is visible and recoverable where the alternative is neither.

**THE SUBSET ASSERTION IS THE COMPENSATING GUARD, AND IT SITS AT THE BOTO BOUNDARY.** The commit
gate can only assert a whole-run property — Step Functions has no per-item ``Choice`` over a list —
so "an item that did not fully copy is not deleted" is protected by a collector unit test and by
this assertion, at two layers. It is checked against the keys actually handed to ``DeleteObjects``,
not against the filter's own output: re-checking a filter with the filter proves nothing.

**A ``delete`` operation's deletions are UNCONDITIONAL, deliberately.** A ``move``'s conditional
delete protects bytes that were just copied; a ``delete`` has no copy, and an object modified since
the expansion is still one the user asked to remove. An object ADDED since is not in the plan and
survives — the same orphan rule.

The service name is the control plane, not the function, so one operation's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import observability
from cpcommon.errors import TerminalError
from cpcommon.paths import normalize_root
from focommon import delete, notify, plan

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-ops")


def _assert_subset(deleting: set, deletable: set) -> None:
    """Confirms nothing outside the confirmed set is about to be deleted.

    Called immediately before each item's keys are handed to ``DeleteObjects``, so that deleting
    the skip above turns into a raised refusal rather than a deletion — which is what a mutation
    test of that line asserts.

    Args:
      deleting: The item keys whose objects are about to be handed to S3.
      deletable: The item keys the collector confirmed.

    Returns:
      None.

    Raises:
      TerminalError: ``forbidden`` when anything is about to be deleted that was not confirmed.
        Whole-request and BEFORE the first call: an item outside the confirmed set is one whose
        objects may not have copied, and deleting it is the unrecoverable case this plane exists to
        avoid.
    """
    stray = deleting - deletable
    if stray:
        raise TerminalError(
            "forbidden",
            f"{len(stray)} item(s) were about to be deleted without being confirmed as copied",
        )


@observability.traced("delete-source")
@notify.notifies_on_failure("delete-source")
def handler(event, context) -> dict:
    """Step Functions entry point: removes the sources of every confirmed item.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out, so
    if it were outermost the span would close as successful on an invocation that actually failed
    and notified.

    Args:
      event: The request, carrying the plan key and the transfer-results document's key.
      context: The Lambda context, unused.

    Returns:
      The request unchanged but for the deletion's own record, which travels by pointer.

    Raises:
      TerminalError: ``plan_unreadable`` or ``plan_superseded`` when either document is not this
        run's, or ``forbidden`` from the subset assertion.
      TransientError: On a retryable S3 fault, so the state's Retry re-runs the verb — safe,
        because an already-absent key is reported as deleted rather than as a failure.
    """
    return _delete_source(event)


def _delete_source(event) -> dict:
    """Deletes the plan's keys for every confirmed item, one item at a time.

    Per item rather than across the selection, so a refusal or a precondition mismatch costs its own
    item and no other — and so ``Errors[].Key`` attributes back with no join. An item key in the
    confirmed set that names no plan item deletes NOTHING and is recorded rather than falling
    through silently.

    Args:
      event: The request with its two document keys.

    Returns:
      The request with ``deletedCount`` and the results document's key; the per-item records were
      written back into that document rather than onto the state.

    Raises:
      TerminalError: ``plan_unreadable``, ``plan_superseded``, ``forbidden``, or a per-item refusal
        escalated by the deletion module.
      TransientError: On a retryable S3 fault.
    """
    loaded = plan.load(event.get("planKey"), event)
    results_key = event.get("transferResultsKey")
    results = plan.load_results(results_key)

    deletable = set(results["deletable"])
    source = loaded["source"]
    root = normalize_root(source["root"])
    by_key = {item["itemKey"]: item for item in loaded["items"]}
    conditional = event.get("operation") == "move"

    records, deleted_total = [], 0
    for item_key, item in by_key.items():
        if item_key not in deletable:
            continue
        keys = [obj["srcKey"] for obj in item["objects"] if obj.get("srcKey")]
        etags = {obj["srcKey"]: obj.get("etag") or "" for obj in item["objects"]}
        # The guard sits HERE, immediately before the keys reach S3, rather than over the filter
        # above — a check placed after the filter would re-check the filter with itself.
        _assert_subset({item_key}, deletable)
        try:
            removed = delete.delete_item_keys(
                source["bucket"], keys, etags, root, conditional=conditional
            )
        except TerminalError as err:
            logger.info("item %s could not be deleted: %s", item_key, err)
            records.append(
                {"itemKey": item_key, "deleted": 0, "failed": len(keys), "reason": err.reason}
            )
            continue
        deleted_total += removed["deleted"]
        records.append({"itemKey": item_key, **removed})

    for missing in sorted(deletable - set(by_key)):
        logger.warning("confirmed item %s names no plan item; nothing was deleted for it", missing)
        records.append(
            {"itemKey": missing, "deleted": 0, "failed": 0, "reason": delete.SOURCE_DELETE_FAILED}
        )

    plan.write_results(results_key, {**results, "deletions": records})

    logger.info("deleted %d object(s) across %d item(s)", deleted_total, len(records))
    observability.info(
        "source deleted",
        actor=(event.get("actor") or {}).get("username"),
        operation=event.get("operation"),
        source_bucket=source["bucket"],
        items=len(records),
        objects=deleted_total,
        failed=sum(record["failed"] for record in records),
    )
    return {**event, "deletedCount": deleted_total}
