"""User-facing notification text for archive and restore outcomes.

One place maps each stable terminal reason code to friendly text, so every verb and its tests
agree on the wording. Kept ASCII — no smart quotes.

This module is the table and its wording; the resolution itself is ``cpcommon.messages``
, which also marks these codes valid so they pass ``TerminalError``'s
raise-time validation. ``unexpected_error`` is deliberately absent — it resolves through the
base table and renders the same sentence everywhere.

**No raw AWS text is ever interpolated into any of these**: the detail on the
exception is for the logs and the Step Functions record, and the sentence the user reads is
composed here.

Attributes:
  _BODIES: Reason code to the clause following the "Couldn't archive ..." prefix. The cap body
    that CAN name a number carries a marker rather than the number, so the sentence is filled
    from ``config`` by ``failure_message`` and cannot drift from the constant that enforces it.
    ``{itemName}`` is filled from the RAISE SITE instead — it is the user's own file name, not a
    number this module can know — and ``test_every_marker_in_every_body_can_be_filled_by_
    somebody`` holds every marker to having a supplier, because ``blank_unfilled=True`` renders
    an unsupplied one as a GAP, which reads as a typo rather than as a bug. The archive outcome
    bodies fill ``{copied}``, ``{total}``, ``{failed}``, ``{residue}`` and ``{requestId}`` the
    same way, for the same reason: they are counts of one run, not properties of this plane.

    **Every body downstream of the copy says what happened to the SOURCE**, and that is the one
    editorial rule here. Archiving is the only operation in this portal that deletes a user's
    data, so the question a failure has to answer first is whether the user still has their
    files — "nothing was deleted and your files are exactly where they were" is the commit gate
    speaking, and the two bodies that cannot say it (``source_delete_incomplete``,
    ``receipt_write_failed``) say instead that nothing has been lost.

    There is no ``request_id_reused`` body, because that refusal is told to nobody. It is the
    shared layer's code, one of ``cpcommon.messages.SILENT_REASONS``: the prefix it finds occupied
    belongs to the run that first held the id, and that run's own "Archived" message is the one
    the user should read, so a second message saying nothing was archived could only contradict
    it.

    There is no ``unknown_space`` body: a shared space that does not exist fails
    ``authorize_source`` as ``forbidden``, deliberately, because "no such space" and "you are
    not a member" must not be distinguishable to a caller — the difference is an existence
    oracle over other people's spaces.

    **TWO RULES BIND EVERY BODY A RESTORE CAN RENDER, and a test holds the whole table to them.**
    A second restore of one archive can run beside the first, and it sweeps the vault when it
    finishes — so a sentence that is merely misleading on one run can cost the only copy on two.
    (1) No sentence tells the user to destroy anything: the remediation is "move or rename", and
    a user who wants a file gone does not need this app to suggest it. (2) No sentence states the
    archive's present condition as fact, because a sibling can sweep the vault after the message
    is sent; the one permitted form is time-scoped — "was still complete when this restore
    stopped" — and it is earned by ``restore.archive_is_intact`` counting the prefix, never
    assumed. The population is this table less ``ARCHIVE_ONLY``, so a code added later is held to
    both rules by default. **Per-sentence fixes were tried first and each review round found
    another sentence**, which is why this is a rule over a population rather than a list.

    **``restore_incomplete`` still has to say three things**, and the third is the one an author
    would leave out. A partial restore cannot be rolled back the way a partial archive can: the
    user's space now holds some of their data, and removing it to make the operation atomic would
    destroy the very thing the restore was for. So the archive is deliberately kept, the id stays
    valid — and **re-requesting will hit the destination guard against the files that DID land**.
    Without that sentence the obvious next action produces a refusal that reads like a new bug, on
    a run that already went wrong.

    **``restore_incomplete_occupied`` is its sibling for the run that met a file in the way**, and
    "of the rest" in it is deliberate: items can also fail for other reasons, so ``{occupied}`` is
    at most ``{total} - {restored}`` and the sentence stays true without explaining the
    difference. **``restore_archive_cleared`` is what both of them become when the count does not
    add up** — it is the fail-closed outcome, and it says only what the count proves.

    **``destination_occupied_during_copy`` is a PER-ITEM reason, not a refusal**, the sibling of
    ``copy_failed``: nothing raises it for a whole request, and its body is written for the one
    file it would describe.

    ``restore_archive_incomplete`` is the manifest-disagreement refusal, and it does NOT
    reuse the ``archive_incomplete`` name the rule proposed: that code was already registered by the archive's own body for a copy that fell
    short, whose body promises "nothing was deleted and your files
    are exactly where they were", and the ASL seeds the literal in ``RollbackReturnedSeed``. One
    code cannot carry both sentences, and the shorter name belongs to the arm that shipped first.

  ARCHIVE_ONLY: The codes only an ARCHIVE can produce, and so the ones the two restore rules
    above do not hold to. It is an explicit set rather than a derived one because "which arm can
    reach this code" is a fact about the verbs, not about the wording — and it is stated as the
    EXCLUSION so that a code added to the table later is checked by default, which is the safe
    direction to be wrong in. Three groups, each unreachable for the same reason:
    the selection refusals, which need a selection a restore request does not carry; the
    expansion and cap refusals, which need a source expansion a restore never runs; and the
    archive's own copy, commit-gate and source-deletion outcomes, none of which exist on an arm
    that deletes nothing. **Four codes both arms reach are deliberately absent from it**:
    ``plan_unreadable``, ``plan_superseded``, ``transfer_results_unreadable`` and
    ``protected_marker``, the last because the vault sweep goes through the same deletion guard
    the archive does. ``copy_failed`` is absent too — one copy verb serves both arms.

  resolver: The domain-scoped resolver for an ARCHIVE, carrying that mode's prefix,
    access-denied clause and fallback.
  restore_resolver: The same body table under RESTORE wording. **The two modes share one table
    and differ only in the sentence's opening**, because the failure codes are disjoint —
    ``destination_occupied`` cannot happen to an archive and ``too_many_items`` cannot happen to
    a restore — while the codes both modes CAN reach (``forbidden``, ``malformed_event``,
    ``invalid_request``) are exactly the ones a single prefix would get wrong. A user who
    clicked Restore and reads "Couldn't archive that" is being told about an operation they did
    not ask for, which is the same class of defect the refusal wording exists to avoid.

    **It also carries the SUFFIX, and that is the only place the safety sentence lives.** Every
    message this resolver renders ends with it — each body, the access-denied clause, and the
    generic fallback a killed verb produces — so a code reachable after a copy-back has begun
    needs no list to carry it and cannot be forgotten. The archive resolver passes none, so an
    archive's wording is unchanged.
"""

from cpcommon import messages as _cpmessages

from . import config, receipt

_BODIES = {
    "invalid_request": "that request was malformed and could not be run.",
    "no_items": "nothing was selected.",
    "invalid_items": "the list of files was malformed.",
    "too_many_items": (
        "you can archive at most {maxItems} files or folders at a time. Please select fewer."
    ),
    "selection_too_large": (
        "that selection is too large to archive in one go. Please select fewer files or folders."
    ),
    "reserved_folder": (
        "that folder is managed by Data Quarry and can't be archived. "
        "Please select your own files or folders instead."
    ),
    "reserved_object_name": (
        'the file "{itemName}" at the top of your space has the same name as the record this '
        "archive writes, so nothing was archived. Please rename it and try again."
    ),
    "protected_marker": (
        'the file "{itemName}" can\'t be removed from your space, so nothing was archived. '
        "Please select something else."
    ),
    "source_missing": (
        "one of the selected files is no longer there, so nothing was archived. "
        "Please refresh the folder and try again."
    ),
    "nothing_to_archive": "there were no files in what you selected, so there was nothing to do.",
    "too_many_objects": (
        "that selection holds more than {maxObjects} files. Please archive a smaller folder."
    ),
    "source_too_large": (
        "that selection is larger than one archive can hold. Please archive a smaller folder."
    ),
    "object_too_large": (
        "one of those files is too large to archive. Please contact an administrator."
    ),
    "undeletable_folder": (
        'what you selected contains a folder named "{folderName}", which Data Quarry manages and '
        "can't remove from your space, so nothing was archived. Please select the files and "
        "folders around it instead."
    ),
    "plan_unreadable": (
        "the list of files to archive could not be read back, so nothing was archived."
    ),
    "plan_superseded": (
        "another archive replaced this one's list of files, so nothing was deleted and your files "
        "are exactly where they were. Please try again."
    ),
    "manifest_write_failed": (
        "the archive record could not be written, so nothing was deleted and your files are "
        "exactly where they were."
    ),
    "transfer_results_unreadable": (
        "we could not confirm that every file had been copied, so nothing was deleted and your "
        "files are exactly where they were. Please try again."
    ),
    "copy_failed": (
        "those files could not be copied, so nothing was deleted and your files are exactly "
        "where they were. Please try again."
    ),
    "archive_incomplete": (
        "only {copied} of {total} file(s) could be copied, so nothing was deleted and your "
        "files are exactly where they were. Please try again."
    ),
    "archive_rollback_incomplete": (
        "only {copied} of {total} file(s) could be copied, so nothing was deleted and your "
        "files are exactly where they were. Please try again. {residue} half-copied file(s) "
        "could not be cleaned up; they are not in your space and will expire on their own."
    ),
    "source_delete_incomplete": (
        "your files were archived, but {failed} of {total} could not be removed from your space. "
        "Nothing has been lost - they are safe in both places. Please contact an administrator."
    ),
    "receipt_write_failed": (
        "your files were archived, but the receipt could not be written. Nothing has been lost. "
        "Your archive id is {requestId} - keep it, because restoring these files needs it and "
        "there is no receipt to find it in."
    ),
    "archive_timed_out": (
        "that archive ran for too long and was stopped. Nothing was deleted and your files are "
        "exactly where they were. Please try again with a smaller selection."
    ),
    "restore_timed_out": (
        "that restore ran for too long and was stopped, and some files may already be back in "
        "your space. Please contact an administrator before requesting this restore again."
    ),
    "archive_not_found": (
        'no archive with the id "{archiveId}" was found in "{spaceName}". Please check the id '
        'against the receipt under "system_settings/archive" in that space and try again.'
    ),
    "restore_archive_incomplete": (
        "that archive holds {found} file(s) but its record says {expected}, so it should not be "
        "restored. Nothing was changed in your space. Please contact an administrator."
    ),
    "nothing_to_restore": (
        "that archive holds no files, so there was nothing to restore. Nothing was changed in "
        "your space."
    ),
    "restore_never_requested": (
        "the archived files were not all retrieved from long-term storage, so this restore "
        "copied nothing into your space. Please try again."
    ),
    "restore_incomplete": (
        "{restored} of {total} file(s) were restored to your space before the restore stopped, "
        "so it did not finish. The archive was still complete when this restore stopped, so it "
        "can be requested again once the paths are clear - requesting it will report the files "
        "that came back, so move or rename them first."
    ),
    "restore_incomplete_occupied": (
        "{restored} of {total} file(s) were restored to your space. {occupied} of the rest were "
        "not, because a file appeared at the same path while the restore was copying - nothing "
        "was overwritten. The archive was still complete when this restore stopped, so it can be "
        "requested again once the paths are clear: move or rename the files now in the way, "
        "including the ones this restore put back."
    ),
    "restore_archive_cleared": (
        "{restored} of {total} file(s) came back before this restore stopped, and the archive "
        "could not be confirmed as still complete - another restore of it may have finished "
        "first, in which case the rest are back too. Please contact an administrator before "
        "requesting this restore again."
    ),
    "destination_occupied_during_copy": (
        "a file appeared at that path while the restore was copying, so it was not restored and "
        "nothing was overwritten."
    ),
    "destination_occupied": (
        "these files already exist where they would be restored to, so nothing was restored: "
        "{sample}. There may be more. Please move or rename them and then request the "
        "restore again."
    ),
    "destination_occupied_after_retrieval": (
        "these files appeared where they would be restored to while the restore was being "
        "prepared, so nothing was restored: {sample}. There may be more. Please move or rename "
        "them and then request the restore again - the files have already been retrieved "
        "from long-term storage and will stay ready for a few days, so trying again soon will "
        "not mean another long wait."
    ),
    "archive_object_unreadable": (
        "one of the archived files could not be read back, so nothing was restored. Nothing was "
        "changed in your space. Please contact an administrator."
    ),
}


resolver = _cpmessages.register(
    _BODIES,
    prefix="Couldn't archive that: ",
    access_denied="You don't have access to archive those files.",
    fallback="something went wrong.",
    blank_unfilled=True,
)

ARCHIVE_ONLY = frozenset(
    {
        "no_items",
        "invalid_items",
        "too_many_items",
        "selection_too_large",
        "reserved_folder",
        "reserved_object_name",
        "source_missing",
        "nothing_to_archive",
        "too_many_objects",
        "source_too_large",
        "object_too_large",
        "undeletable_folder",
        "manifest_write_failed",
        "archive_incomplete",
        "archive_rollback_incomplete",
        "source_delete_incomplete",
        "receipt_write_failed",
        "archive_timed_out",
    }
)

RESTORE_SAFETY_SUFFIX = (
    " If any files from this archive are already back in your space, please don't delete or "
    "overwrite them - they may be the only copy."
)

restore_resolver = _cpmessages.register(
    _BODIES,
    prefix="Couldn't restore that: ",
    access_denied="You don't have access to restore those files.",
    fallback="something went wrong.",
    blank_unfilled=True,
    suffix=RESTORE_SAFETY_SUFFIX,
)


def archived_message(
    request_id: str, files: int, folders: int, total_bytes: int, shared_space: str | None = None
) -> str:
    """Composes the text for a completed ARCHIVE.

    **It names the archive id, and that is the whole reason this message cannot be generic.** The
    archived objects live in a bucket the browser has no relationship with, so the id is the
    user's only route back to them — the receipt carries it too, but the receipt is inside the
    folder the id names, and a user who never opens it has nowhere else to read it. It also says
    where the id goes: an id with no instruction beside it left a user holding it and not knowing
    what to do with it. A shared space's archive names that space, because Files opens the
    personal one and a restore only finds an archive in the space being browsed.

    The size renders through ``receipt.human_bytes``, so one archive reads the same in its receipt,
    in this message and in the file browser (the shared TB ceiling).

    Args:
      request_id: The run's id, which IS the archive's permanent identity.
      files: How many files were archived, folder placeholders left out.
      folders: How many folder placeholders were archived, which the sentence names only when
        there are no files.
      total_bytes: Their total size.
      shared_space: The shared space's name when the archive came from one, else None.

    Returns:
      The sentence.

    Raises:
      None.
    """
    phrase, one = _contents_phrase(files, folders)
    where = f"open the {shared_space} space in Files, choose" if shared_space else "choose"
    return (
        f"Archived {phrase} ({receipt.human_bytes(total_bytes)}). "
        f"{'It has' if one else 'They have'} been removed from your space. "
        f"Archive id: {request_id} - to restore {'it' if one else 'them'}, {where} "
        "Restore Archived Data" + ("" if shared_space else " in Files") + " and enter this id."
    )


def restore_started_message(files: int, folders: int) -> str:
    """Composes the text for a restore that has been REQUESTED and is now waiting.

    **The only "started" notification in this application, and it exists because the user is about
    to wait hours.** Every other plane finishes in seconds or minutes, so silence until the
    outcome is honest there; here silence for three to five hours is indistinguishable from a
    request that was dropped. It says the duration and that a second message will follow, so the
    reasonable next action is to stop waiting.

    Args:
      files: How many files are being retrieved, folder placeholders left out.
      folders: How many folder placeholders are being retrieved, named only when there are no
        files.

    Returns:
      The sentence.

    Raises:
      None.
    """
    phrase, _ = _contents_phrase(files, folders)
    return (
        f"Restoring {phrase} from long-term storage. "
        "This takes several hours - you'll get another notification when it finishes. "
        "Nothing has changed in your space yet."
    )


def restored_message(
    files: int, folders: int, total_bytes: int, *, archive_swept: bool = True
) -> str:
    """Composes the text for a completed RESTORE.

    **The last sentence is CONDITIONAL, and that is not a nicety.** the restore made a failed vault
    sweep a flag on a successful run rather than a failure of it — ``DeleteArchived``'s Catch
    reaches the same success terminal through ``CleanupIncomplete``. Said unconditionally, "the
    archive has been cleaned up" turns that flag into a positive claim about the one route where
    it is false, and the flag reaches nothing else a user can see. The alternative wording says
    only what is certainly true and does not invite the user to act, because there is nothing for
    them to do: the residue is billed at the 90-day minimum and swept by the bucket's expiry.

    Args:
      files: How many files were restored, folder placeholders left out.
      folders: How many folder placeholders were restored, named only when there are no files.
      total_bytes: Their total size.
      archive_swept: Whether the vault copy was actually removed.

    Returns:
      The sentence.

    Raises:
      None.
    """
    phrase, one = _contents_phrase(files, folders)
    restored = (
        f"Restored {phrase} ({receipt.human_bytes(total_bytes)}) to your "
        f"space, back where {'it came' if one else 'they came'} from."
    )
    return f"{restored} The archive has been cleaned up." if archive_swept else restored


def _contents_phrase(files: int, folders: int) -> tuple:
    """Renders what an archive holds as the phrase a sentence names, and whether it is singular.

    **Folders are named only when there is no file at all.** A placeholder is how an empty folder
    made with New folder exists, so a selection of nothing but those holds something the user
    can see and no file; saying "0 files" there reads as though nothing happened. Beside any file
    a placeholder is invisible — the folder shows because the file is in it — and naming it would
    describe something the user cannot find. The singular decides the pronoun each sentence
    carries after the phrase.

    Args:
      files: How many files, placeholders left out.
      folders: How many folder placeholders.

    Returns:
      ``(phrase, singular)`` — ``1 file``, ``N files``, or with no files ``1 empty folder`` or
      ``N empty folders``.

    Raises:
      None.
    """
    if files == 0 and folders > 0:
        return ("1 empty folder" if folders == 1 else f"{folders} empty folders"), folders == 1
    return ("1 file" if files == 1 else f"{files} files"), files == 1


def failure_message(reason: str, *, tokens: dict | None = None, mode: str | None = None) -> str:
    """Composes the actor-facing failure text for a terminal reason and its context.

    This layer's job is the trusted context; the resolver composes the sentence. That context is
    passed LAST so it wins over the payload — a raise site's token must not misstate a cap.

    Args:
      reason: The terminal reason code. An unknown one falls back to a generic clause rather
        than leaking the code.
      tokens: Optional marker values from the raise site, carried on the terminal error.
      mode: The request's mode, which selects the wording. **It defaults to the ARCHIVE mode
        rather than raising or guessing**: an unknown mode is a failure path that has already
        lost the request, and the archive sentence is the safe one to fall back to because a
        run that got far enough to have a mode has one on the state for the seed to read.

    Returns:
      The sentence.

    Raises:
      None.
    """
    chosen = restore_resolver if mode == "restore" else resolver
    return chosen.message(
        reason,
        **{
            **(tokens or {}),
            "maxItems": str(config.ARCHIVE_MAX_ITEMS),
            "maxObjects": str(config.ARCHIVE_MAX_OBJECTS),
        },
    )
