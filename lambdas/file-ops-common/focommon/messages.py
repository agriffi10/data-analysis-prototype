"""User-facing notification text for file-operations outcomes.

One place maps each stable reason code to friendly text, so every verb and its tests agree on the
wording. Kept ASCII — no smart quotes.

This module is the table and its wording; the resolution itself is ``cpcommon.messages``, which
also marks these codes valid so they pass ``TerminalError``'s raise-time validation.

**ONE BODY TABLE, THREE PREFIXES.** Copy, move and delete share every reason — a protected folder
refuses all three, a lock waits for all three — but a user who pressed Delete must not read that a
copy failed. Three tables would let one reason drift into three sentences; one resolver would word
a delete refusal as a copy failure. So the bodies are written once, as clauses that complete any of
the three prefixes, and the caller picks the resolver by operation.

Writing bodies that complete three different prefixes is a real constraint on the wording, not a
formatting detail: a clause naming the operation ("...so nothing was copied") reads wrong under two
of the three prefixes, so the bodies say what is true of the ITEM instead.

**No raw AWS text is ever interpolated into any of these**: the detail on the exception is for the
logs and the Step Functions record, and the sentence the user reads is composed here.

Attributes:
  _BODIES: Reason code to the clause following the prefix. The cap bodies that can name a number
    carry a marker rather than the number, so the sentence is filled from ``config`` and cannot
    drift from the constant that enforces it.
  copy_resolver: The domain resolver under copy wording.
  move_resolver: The same table under move wording.
  delete_resolver: The same table under delete wording.
"""

from cpcommon import messages as _cpmessages

from . import config

_BODIES = {
    "no_items": "nothing was selected.",
    "invalid_items": "the list of files and folders is malformed.",
    "too_many_items": (
        "you can work on at most {maxItems} files or folders at a time. Please select fewer."
    ),
    "selection_too_large": (
        "that selection is too large to submit in one go. Please select fewer files or folders."
    ),
    "invalid_operation": "that is not something this can do.",
    "space_root_not_an_item": (
        "a whole space can't be worked on in one go. Please pick the folders and files inside it."
    ),
    "invalid_destination": "no destination was given, or it is malformed.",
    "unexpected_destination": "a destination was given for something that does not take one.",
    "invalid_conflict": "the request did not say what to do about files that already exist.",
    "invalid_submitted_at": "the request carried a submission time that cannot be right.",
    "invalid_target_name": (
        "one of those names cannot be used. A name cannot be empty, contain a slash, or start or "
        "end with a space."
    ),
    "colliding_item_names": (
        'two of the things you selected would both end up called "{itemName}" in the same place. '
        "Please do them one at a time."
    ),
    "destination_inside_source": (
        "one of the folders you selected would end up inside itself. Please pick a destination "
        "outside it."
    ),
    "destination_folder_locked": (
        "that folder is managed for you, so things cannot be put into it."
    ),
    "destination_archive_read_only": (
        "the archive folder is read-only - it holds your archive receipts."
    ),
    "source_folder_undeletable": "that folder is managed for you and cannot be moved or deleted.",
    "results_folder_not_deletable": (
        "query results are managed for you and cannot be moved or deleted."
    ),
    "archive_read_only": (
        "the archive folder is read-only, so what is inside it cannot be moved or deleted."
    ),
    "settings_folder_not_a_source": (
        "that folder is managed for you. It cannot be copied, moved or deleted."
    ),
    "marker_not_deletable": (
        "that file is there to protect a folder. It cannot be copied, moved or deleted - a copy "
        "of it could never be removed either."
    ),
    "operation_timed_out": (
        "it took too long and was stopped part-way, so some of it may have happened and some may "
        "not. Please look at the folder before trying again, and give it a few minutes - that "
        "space stays busy for a short while afterwards."
    ),
    "lock_wait_exhausted": (
        "something else was already working in that space and had not finished. Nothing was "
        "changed. Please try again in a few minutes."
    ),
}


def _markers() -> dict:
    """Returns the fill values every body's markers are resolved from.

    Kept beside the table so a cap named in a sentence cannot drift from the constant that enforces
    it — the number a user reads and the number the request is refused against are the same object.

    Args:
      None.

    Returns:
      The marker fills, as strings — the resolver substitutes by ``str.replace``, so an int is a
      ``TypeError`` at the one moment a sentence is being composed to report a failure.

    Raises:
      None.
    """
    return {"maxItems": str(config.FILE_OPS_MAX_ITEMS)}


copy_resolver = _cpmessages.register(
    _BODIES,
    prefix="Couldn't copy that: ",
    access_denied="You don't have access to copy those files.",
    fallback="something went wrong.",
    blank_unfilled=True,
)

move_resolver = _cpmessages.register(
    _BODIES,
    prefix="Couldn't move that: ",
    access_denied="You don't have access to move those files.",
    fallback="something went wrong.",
    blank_unfilled=True,
)

delete_resolver = _cpmessages.register(
    _BODIES,
    prefix="Couldn't delete that: ",
    access_denied="You don't have access to delete those files.",
    fallback="something went wrong.",
    blank_unfilled=True,
)

_RESOLVERS = {"copy": copy_resolver, "move": move_resolver, "delete": delete_resolver}


def resolver_for(operation: object) -> _cpmessages.Resolver:
    """Returns the resolver whose wording matches the operation the user asked for.

    Falls back to the copy resolver for an unrecognised operation rather than raising. This is
    reached only on a request malformed enough that the operation itself was refused, and the
    alternative — raising while composing the sentence that reports a refusal — replaces a bad
    message with no message at all.

    Args:
      operation: The request's operation, which may be anything on a malformed request.

    Returns:
      The matching resolver.

    Raises:
      None.
    """
    return _RESOLVERS.get(operation, copy_resolver) if isinstance(operation, str) else copy_resolver


def failure_message(operation: object, reason: str, tokens: dict | None = None) -> str:
    """Composes the whole sentence an actor reads for a failed request.

    **The exception's DETAIL is not a source here, and that separation is deliberate.** A detail
    can quote a folder name the actor supplied and exists for the logs and the Step Functions
    record; it is operator text, and rendering it would put raw internals in front of a user. The
    ``tokens`` mapping is the opposite channel — values a raise site provides precisely because a
    body names a marker for them.

    Args:
      operation: The request's operation, which selects the wording.
      reason: The stable reason code.
      tokens: Marker fills from the raise site, for the bodies that name one.

    Returns:
      The user-facing sentence.

    Raises:
      None.
    """
    return resolver_for(operation).message(reason, **_markers(), **(tokens or {}))
