"""delete-source — the only verb in this portal that deletes a user's data.

It runs on one branch of the commit gate and is unreachable from the other: by the time it is
invoked, every object in the plan has been confirmed present in the vault and the integrity record
has been written. What it deletes is exactly the plan — the same list the manifest was built from
— so an object that was never copied is also never deleted.

**And only when EVERY original still carries the tag the plan recorded — or none is deleted.**
The gate confirms a copy was made, not that the original has stood still since: a file written
over while the Map ran is newer than its archived copy, and deleting it would leave the user the
older version and nothing else. Every original is headed before anything is deleted, and one that
changed refuses the whole deletion and removes the vault copy, so the user is told nothing was
archived and their files are where they were. Keeping only the changed ones was the first shape
and was rejected: it deleted the rest into a vault the user could not find, because the receipt
that names an archive is written only after this state succeeds.

**No original is deleted unless the vault holds every planned object at that moment**, counted by
the restore's own fail-closed ``archive_is_intact``; a short count refuses as a change does.

**The verdict is RECORDED before it is acted on, and every later attempt follows the record.** A
batch that throttles raises only after every other batch ran, so by the time the state's Retry
re-runs this verb its first attempt has already partly acted — and re-deciding lets the two paths
undo each other. A refusal that follows a partial deletion removes the vault copy of what was
already deleted; a deletion that follows a partial refusal deletes originals whose copy is half
gone. So the first attempt writes its verdict create-only beside the claim (``arcommon.plan``'s
decision record), and a Retry, a lost response or a redrive finishes whatever that verdict began:
a refusal finishes removing the vault copy, and a deletion never touches it — an original that
changed since the verdict is kept, and the run fails as a partial deletion with the copy intact.

**``DeleteObjects`` returns HTTP 200 with a per-item ``Errors`` array**, and a response inspected
only by its status code is a defect this repo has already had once. Here that defect
would report a completed archive over a source that is still half there, and the user would be
told their files had moved when some of them had not. ``arcommon.delete`` reads the array, attempts
every batch before reporting, and returns counts rather than keys.

**A partial deletion is a terminal failure and the archive copy is KEPT.** The user's data then
exists in two places, which is recoverable by hand; the alternative — removing the archive after a
partial source deletion — is not recoverable at all.

**The total that failure names is counted in files from the keys this verb deletes**, with a
folder placeholder counted only when it is one of the things that could not be removed. It is
derived here rather than read off the state, so the sentence depends on nothing an older verb
might have written without it.

The service name is the control plane, not the function, so one archive's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from arcommon import counts, delete, notify, plan, restore
from cpcommon import observability
from cpcommon.errors import TerminalError, TransientError
from cpcommon.paths import normalize_root

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")


@observability.traced("delete-source")
@notify.notifies_on_failure("delete-source")
def handler(event, context) -> dict:
    """Step Functions entry point: deletes the archived originals from the user's space.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The request, carrying the copy plan's key and the authorized source.
      context: The Lambda context, unused.

    Returns:
      The request with how many objects were deleted.

    Raises:
      TerminalError: ``plan_unreadable`` or ``plan_superseded`` when the plan cannot be read
        back or is not this run's — the second is what stops a run deleting a DIFFERENT
        selection after another execution overwrote the plan under a reused request id —
        ``source_changed_during_archive`` when any original changed since the plan, before
        anything is deleted, ``archive_copy_unconfirmed`` when the vault no longer holds every
        planned object, ``source_delete_incomplete`` when any object survived a deletion that
        was attempted, or ``forbidden`` /
        ``protected_marker`` from the pre-delete assertion, which fails the run BEFORE issuing
        a delete the bucket policy would refuse mid-batch.
      TransientError: On a retryable S3 fault, so the state's Retry re-runs the verb — safe,
        because an already-absent key is not an error and a re-driven execution completes.
    """
    return _delete_source(event)


def _delete_source(event) -> dict:
    """Rebuilds the source keys from the plan, then decides — or follows the decision — and acts.

    The keys are rebuilt from the plan's relative keys and the source root rather than stored
    absolute, which keeps the plan half the size it would otherwise be at the object cap — and
    means the root a key is deleted under is the same root the archive destination was built
    from. The whole list is checked as deletable before any original is headed, so a plan that
    names a protected key refuses exactly as it did before the heads existed.

    **The vault copy is removed on a changed original**, by the rollback's own listing, because
    the source is then untouched and a copy nobody holds a receipt for is one nobody can restore.
    A removal that only partly lands leaves residue the bucket's expiry reclaims, and does not
    change what the user is told: their files are where they were either way.

    Args:
      event: The request with its copy plan key.

    Returns:
      The request with ``deletedCount``.

    Raises:
      TerminalError: ``plan_unreadable``, ``plan_superseded``, ``source_changed_during_archive``,
        ``archive_copy_unconfirmed``, ``source_delete_incomplete``, ``forbidden`` or
        ``protected_marker``.
      TransientError: On a retryable S3 fault.
    """
    loaded = plan.load(event.get("copyPlanKey"), event)
    source = loaded["source"]
    root = normalize_root(source["root"])
    planned = {f"{root}{entry['relKey']}": entry.get("etag") for entry in loaded["objects"]}
    keys = list(planned)

    delete.assert_deletable(keys, root)
    record = plan.read_source_decision(event)
    written, decided_changed = False, set()
    if record is None:
        record, written, decided_changed = _decide(event, loaded, planned)
    if record["decision"] == "refuse":
        _refuse_changed(event, loaded["archive"], record["changed"], len(keys))
    if record["decision"] == "unconfirmed":
        _refuse_unconfirmed(event, loaded["archive"], len(keys))

    kept = decided_changed if written else delete.changed_keys(source["bucket"], planned)
    removed = delete.delete_keys(source["bucket"], [key for key in keys if key not in kept], root)
    failed = removed["failed"] + len(kept)

    logger.info(
        "deleted %d of %d source object(s), kept %d changed since the verdict",
        removed["deleted"],
        len(keys),
        len(kept),
    )
    observability.info(
        "source deleted",
        actor=(event.get("actor") or {}).get("username"),
        source_bucket=source["bucket"],
        source_root=root,
        objects=removed["deleted"],
        failed=removed["failed"],
        changed=len(kept),
    )

    if failed:
        folders_short = removed["failedFolders"] + len(kept) - counts.count_files(kept)
        _, total = counts.shown(
            counts.count_files(keys),
            files_short=failed - folders_short,
            folders_short=folders_short,
        )
        raise TerminalError(
            "source_delete_incomplete",
            f"{failed} of {len(keys)} source object(s) could not be deleted, {len(kept)} of them "
            "because they changed after the verdict to delete; the archive copy was kept",
            tokens={"failed": str(failed), "total": str(total)},
        )
    return {**event, "deletedCount": removed["deleted"]}


def _decide(event, loaded: dict, planned: dict) -> tuple[dict, bool, set]:
    """Heads every original, counts the vault, and records the verdict before anything acts on it.

    **An original already gone forbids removing the vault**, because the vault may then hold its
    only copy — an earlier deployment's delete-source, which headed nothing and recorded nothing,
    can have deleted it before a Retry landed here, and a user can delete one mid-archive. So with
    anything absent the verdict is a deletion that keeps whatever changed, never a refusal; and if
    the vault cannot be counted whole either, nothing is decided at all — nothing is touched, the
    fault is retryable, and the state's Catch ends the run with the originals and the copy as they
    were.

    Args:
      event: The request, carrying the stamped execution the record names.
      loaded: The copy plan.
      planned: Absolute source key to the ETag the plan recorded.

    Returns:
      ``(record, written, changed)`` — ``plan.record_source_decision``'s pair, this attempt's
      verdict or an earlier one's, and the originals this attempt found changed, which a deletion
      it recorded itself keeps without heading them again.

    Raises:
      TransientError: On a retryable S3 fault heading, counting or recording, and when originals
        are already gone and the vault cannot be counted whole.
      TerminalError: ``malformed_event`` from the decision key.
    """
    changed, absent = delete.head_originals(loaded["source"]["bucket"], planned)
    intact = restore.archive_is_intact(
        loaded["archive"]["bucket"], loaded["archive"]["root"], len(planned)
    )
    if absent and not intact:
        raise TransientError(
            f"{len(absent)} original(s) are already gone and the vault cannot be counted whole, "
            "so nothing was decided or touched"
        )
    if absent:
        decision = "delete"
    elif changed:
        decision = "refuse"
    elif not intact:
        decision = "unconfirmed"
    else:
        decision = "delete"
    record, written = plan.record_source_decision(event, decision, len(changed))
    return record, written, changed


def _refuse_changed(event, archive: dict, changed: int, planned: int) -> None:
    """Removes the vault copy and refuses the deletion, because an original changed since the plan.

    Args:
      event: The request, for the actor the record names.
      archive: The plan's archive location, whose prefix is removed.
      changed: How many originals the recorded verdict found no longer carrying the plan's tag.
      planned: How many originals the plan named.

    Returns:
      Never.

    Raises:
      TerminalError: ``source_changed_during_archive``, always, naming how many changed. Also
        ``forbidden`` or ``protected_marker`` from the vault removal's pre-check.
      TransientError: When a vault delete batch failed retryably, so the Retry re-runs the verb
        — which reads the recorded refusal and removes whatever of the copy is left.
      ClientError: Propagated raw from the vault listing.
    """
    removed = delete.delete_prefix(archive["bucket"], archive["root"])
    logger.warning(
        "%d of %d original(s) changed since the plan; deleted none and removed %d of %d "
        "archived object(s)",
        changed,
        planned,
        removed["deleted"],
        removed["listed"],
    )
    observability.warning(
        "archive refused because originals changed",
        actor=(event.get("actor") or {}).get("username"),
        changed=changed,
        planned=planned,
        vault_removed=removed["deleted"],
        vault_residue=removed["failed"],
    )
    raise TerminalError(
        "source_changed_during_archive",
        f"{changed} of {planned} original(s) changed since the plan, so none was deleted "
        f"and the archive copy was removed ({removed['failed']} object(s) could not be)",
        tokens={"changed": str(changed)},
    )


def _refuse_unconfirmed(event, archive: dict, planned: int) -> None:
    """Removes what is left of the vault copy and refuses, because it no longer holds the archive.

    Reached when the vault counts short with no original changed — most plausibly a Retry of this
    verb after a refusal that had begun removing the copy. Finishing the removal leaves the user
    exactly where a refusal leaves them, and deleting no original is the whole point.

    Args:
      event: The request, for the actor the record names.
      archive: The plan's archive location, whose prefix is removed.
      planned: How many originals the plan named.

    Returns:
      Never.

    Raises:
      TerminalError: ``archive_copy_unconfirmed``, always. Also ``forbidden`` or
        ``protected_marker`` from the vault removal's pre-check.
      TransientError: When a vault delete batch failed retryably.
      ClientError: Propagated raw from the vault listing.
    """
    removed = delete.delete_prefix(archive["bucket"], archive["root"])
    logger.warning(
        "the vault no longer holds all %d planned object(s); deleted no original and removed %d "
        "of %d archived object(s)",
        planned,
        removed["deleted"],
        removed["listed"],
    )
    observability.warning(
        "archive refused because the vault copy is incomplete",
        actor=(event.get("actor") or {}).get("username"),
        planned=planned,
        vault_removed=removed["deleted"],
        vault_residue=removed["failed"],
    )
    raise TerminalError(
        "archive_copy_unconfirmed",
        f"the vault no longer holds all {planned} planned object(s), so no original was deleted",
    )

