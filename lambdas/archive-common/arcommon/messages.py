"""User-facing notification text for archive and restore outcomes.

One place maps each stable terminal reason code to friendly text, so every verb and its tests
agree on the wording. Kept ASCII — no smart quotes.

This module is the table and its wording; the resolution itself is ``cpcommon.messages``
(SPEC-156 FR-002), which also marks these codes valid so they pass ``TerminalError``'s
raise-time validation. ``unexpected_error`` is deliberately absent — it resolves through the
base table and renders the same sentence everywhere.

**No raw AWS text is ever interpolated into any of these** (SPEC-106): the detail on the
exception is for the logs and the Step Functions record, and the sentence the user reads is
composed here.

Attributes:
  _BODIES: Reason code to the clause following the "Couldn't archive ..." prefix. The cap body
    that CAN name a number carries a marker rather than the number, so the sentence is filled
    from ``config`` by ``failure_message`` and cannot drift from the constant that enforces it.
    ``{itemName}`` is filled from the RAISE SITE instead — it is the user's own file name, not a
    number this module can know — and ``test_every_marker_in_every_body_can_be_filled_by_
    somebody`` holds every marker to having a supplier, because ``blank_unfilled=True`` renders
    an unsupplied one as a GAP, which reads as a typo rather than as a bug. The SPEC-169 outcome
    bodies fill ``{copied}``, ``{total}``, ``{failed}``, ``{residue}`` and ``{requestId}`` the
    same way, for the same reason: they are counts of one run, not properties of this plane.

    **Every body downstream of the copy says what happened to the SOURCE**, and that is the one
    editorial rule here. Archiving is the only operation in this portal that deletes a user's
    data, so the question a failure has to answer first is whether the user still has their
    files — "nothing was deleted and your files are exactly where they were" is the commit gate
    speaking, and the two bodies that cannot say it (``source_delete_incomplete``,
    ``receipt_write_failed``) say instead that nothing has been lost.

    There is no ``unknown_space`` body: a shared space that does not exist fails
    ``authorize_source`` as ``forbidden``, deliberately, because "no such space" and "you are
    not a member" must not be distinguishable to a caller — the difference is an existence
    oracle over other people's spaces.

    **One prefix serves both modes**, and the wording is chosen so it can: "Couldn't archive
    that" reads correctly for a failed archive, and a restore failure is worded inside its own
    body. Two resolvers would mean two prefixes to keep in step for one queue of messages.
  resolver: The domain-scoped resolver, carrying this plane's prefix, access-denied clause and
    fallback.
"""

from cpcommon import messages as _cpmessages

from . import config

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
        "that folder is managed by the portal and can't be archived. "
        "Please select your own files or folders instead."
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
    "request_id_reused": (
        "that archive has already been started once, so nothing was archived. "
        "Please try again from the file browser."
    ),
    "undeletable_folder": (
        'what you selected contains a folder named "{folderName}", which the portal manages and '
        "can't remove from your space, so nothing was archived. Please rename it or select "
        "something else."
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
        "only {copied} of {total} files could be copied, so nothing was deleted and your files "
        "are exactly where they were. Please try again."
    ),
    "archive_rollback_incomplete": (
        "only {copied} of {total} files could be copied, so nothing was deleted and your files "
        "are exactly where they were. Please try again. {residue} half-copied file(s) could not "
        "be cleaned up; they are not in your space and will expire on their own."
    ),
    "source_delete_incomplete": (
        "your files were archived, but {failed} of {total} could not be removed from your space. "
        "Nothing has been lost - they are safe in both places. Please contact an administrator."
    ),
    "receipt_write_failed": (
        "your files were archived, but the receipt could not be written. Nothing has been lost. "
        "Please contact an administrator and quote request {requestId}."
    ),
    "archive_timed_out": (
        "that archive ran for too long and was stopped. Nothing was deleted and your files are "
        "exactly where they were. Please try again with a smaller selection."
    ),
}


resolver = _cpmessages.register(
    _BODIES,
    prefix="Couldn't archive that: ",
    access_denied="You don't have access to archive those files.",
    fallback="something went wrong.",
    blank_unfilled=True,
)


def failure_message(reason: str, *, tokens: dict | None = None) -> str:
    """Composes the actor-facing failure text for a terminal reason and its context.

    This layer's job is the trusted context; the resolver composes the sentence. That context is
    passed LAST so it wins over the payload — a raise site's token must not misstate a cap.

    Args:
      reason: The terminal reason code. An unknown one falls back to a generic clause rather
        than leaking the code.
      tokens: Optional marker values from the raise site, carried on the terminal error.

    Returns:
      The sentence.

    Raises:
      None.
    """
    return resolver.message(
        reason,
        **{
            **(tokens or {}),
            "maxItems": str(config.ARCHIVE_MAX_ITEMS),
            "maxObjects": str(config.ARCHIVE_MAX_OBJECTS),
        },
    )
