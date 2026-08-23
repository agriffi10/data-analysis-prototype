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

**AND A BODY MAY NOT ASSERT THAT A COPY HAPPENED.** The two reasons a source survives —
``source_changed`` and ``source_delete_failed`` — arise on a ``move``, where the data now exists
twice, AND on a ``delete``, where nothing was copied at all. A body saying "you now have it in both
places" is a FALSE SENTENCE under the delete prefix, and it reinstates precisely the confusion the
separate ``delete_failed`` outcome exists to prevent. That clause belongs to the ``duplicate``
OUTCOME, which is per-item wording the notification spec owns; these bodies say only that the
original is still there.

**No raw AWS text is ever interpolated into any of these**: the detail on the exception is for the
logs and the Step Functions record, and the sentence the user reads is composed here.

**AND THE OUTCOME WORDING BELOW REUSES THOSE BODIES RATHER THAN RESTATING THEM.** Six of the
per-item outcomes carry a reason this table already words, and a second table for the item form
would be one code with two sentences — the twin this fleet spent a whole spec removing, arriving
inside one module. So an item's clause IS the body, taken through the resolver, and only the outcomes with no
body of their own are written out.

**The outcome table is NOT registered as a resolver, and that is a decision rather than an
oversight.** ``Resolver.__init__`` ends by marking every key it was given a globally valid reason
code, so registering these would make ``TerminalError("duplicate")`` pass raise-time validation —
and ``outcomes.py``'s rule is that no member of the per-item vocabulary may ever be a whole-request
failure reason. A success sentence also cannot open with "Couldn't move that: ", but that is the
lesser argument.

Attributes:
  _BODIES: Reason code to the clause following the prefix. The cap bodies that can name a number
    carry a marker rather than the number, so the sentence is filled from ``config`` and cannot
    drift from the constant that enforces it.
  copy_resolver: The domain resolver under copy wording.
  move_resolver: The same table under move wording.
  delete_resolver: The same table under delete wording.
  _OUTCOME_CLAUSES: The per-item clause for the outcomes whose reason code has no body — the
    three terminal successes and the no-op. Everything else resolves through the table above.
  _OUTCOME_ADDITIONS: The sentence an outcome adds AFTER its body. Two exist, and both say the
    thing the body deliberately does not: that a duplicate leaves the data in two places (a body
    may not assert a copy happened — see above), and that re-submitting with overwrite cannot be
    undone.
  _SUCCESS_VERBS: The past-tense verb each operation's summary opens with.
"""

from cpcommon import messages as _cpmessages

from . import config, outcomes, paths

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
    "overlapping_items": (
        "one of the folders you selected already contains another one. Please select them one at "
        "a time, or select just the folder that holds them."
    ),
    "too_many_objects": (
        "those folders hold more than {maxObjects} files between them. Please work on fewer "
        "folders at a time."
    ),
    "selection_too_large_to_expand": (
        "those folders hold too much data to do in one go. Please work on fewer folders at a time."
    ),
    "object_too_large": (
        "one of those files is larger than this can handle in one go. Please move or copy it on "
        "its own."
    ),
    "source_missing": "one of those files is no longer there. Please refresh and try again.",
    "source_empty": "there was nothing inside it.",
    "destination_occupied": (
        "something is already in the way there. Please move what is there, or choose a different "
        "destination."
    ),
    "destination_occupied_late": (
        "something was put in the way there while this was being prepared. Please look at the "
        "destination, then try again."
    ),
    "copy_failed": "some of the files could not be copied.",
    "transfer_results_unreadable": (
        "the files were copied but the record of what happened could not be read back, so nothing "
        "was removed. Please look at the destination before trying again."
    ),
    "source_changed": (
        "it was changed while this was running, so the original was left where it is. Please look "
        "at it before trying again."
    ),
    "source_delete_failed": (
        "the original could not be removed, so it is still where it was. Please look at it before "
        "trying again."
    ),
    "delete_refused": (
        "part of it is managed for you and cannot be removed, so it was left alone."
    ),
    "plan_unreadable": "the working list for that could not be read back.",
    "plan_superseded": (
        "another request for that space was already in flight. Nothing was changed. Please try "
        "again."
    ),
    "request_id_reused": (
        "that looks like a repeat of a request already in flight. Nothing was changed. Please "
        "refresh and try again."
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
    return {
        "maxItems": str(config.FILE_OPS_MAX_ITEMS),
        "maxObjects": f"{config.FILE_OPS_MAX_OBJECTS:,}",
    }


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


_OUTCOME_CLAUSES = {
    outcomes.MOVED: "it was moved.",
    outcomes.COPIED: "it was copied.",
    outcomes.DELETED: "it was deleted.",
    outcomes.NOOP: "it is already there under that name, so nothing changed.",
}

_OUTCOME_ADDITIONS = {
    outcomes.CONFLICT: (
        "Sending it again with overwrite turned on replaces what is there, and that cannot be "
        "undone."
    ),
    outcomes.DUPLICATE: (
        "This data is now in both places, and only you can decide which copy to keep."
    ),
}

_SUCCESS_VERBS = {"copy": "Copied", "move": "Moved", "delete": "Deleted"}


def item_clause(operation: object, record: dict) -> str:
    """Composes what one item's line says, after its name.

    An outcome that carries a reason the table already words RESOLVES THROUGH THAT TABLE rather
    than through a second one — the same code cannot come to have two sentences. Only the
    outcomes with no body of their own are written out, and two of them append the sentence their
    body is forbidden from carrying.

    Args:
      operation: The request's operation, which selects the wording.
      record: One outcome record, carrying its outcome and any reason.

    Returns:
      The clause, always a whole sentence or two.

    Raises:
      None.
    """
    outcome = str(record.get("outcome") or "")
    if outcome in _OUTCOME_CLAUSES:
        base = _OUTCOME_CLAUSES[outcome]
    else:
        base = resolver_for(operation).body(str(record.get("reason") or outcome), **_markers())
    addition = _OUTCOME_ADDITIONS.get(outcome)
    return f"{base} {addition}" if addition else base


def _plural(count: int, thing: str = "item") -> str:
    """Renders a count with its noun, so no sentence reads "1 items".

    Args:
      count: How many.
      thing: The singular noun.

    Returns:
      The phrase.

    Raises:
      None.
    """
    return f"{count} {thing}" if count == 1 else f"{count} {thing}s"


def outcome_summary(
    operation: object, records: list, folder: str = "", named: int = 3
) -> str:
    """Composes THE ONE SENTENCE a finished run produces, whatever mix of outcomes it holds.

    One message per run rather than one per item: a selection at the cap would otherwise flood an
    inbox that is capped at 200 rows and read whole on every poll. So the counts carry the run and
    a BOUNDED sample carries the detail, with an explicit tail saying how many were not named — a
    sample a reader could mistake for the whole list is worse than a count alone.

    **A mixed run names what SUCCEEDED as well as what did not.** "2 of 5" answers the question a
    user actually has, where a message listing only refusals reads as though nothing worked.

    **AND THE OPENING IS NEUTRAL RATHER THAN A DENIAL, because the residue is not all failure.**
    Partitioning on "the operation's success outcome, or not" is the obvious split and it makes the
    sentence contradict itself on the two outcomes that matter most: a ``duplicate`` DID reach the
    destination — the link even points there — so "Nothing was moved" is false and is followed
    immediately by a clause saying the data is now in both places; and a ``noop`` is a success that
    did nothing, which a denial reports as a failure. "N need your attention" is true of every
    member of the residue, which is the only thing they have in common.

    Args:
      operation: The request's operation.
      records: Every item's terminal outcome record.
      folder: The destination folder's own name, as a person would say it; empty for a delete,
        which has none.
      named: How many refused items the sentence names before it says "and N more".

    Returns:
      The whole sentence.

    Raises:
      None.
    """
    verb = _SUCCESS_VERBS.get(operation) if isinstance(operation, str) else None
    verb = verb or _SUCCESS_VERBS["copy"]
    success = outcomes.TERMINAL_SUCCESS.get(operation) if isinstance(operation, str) else None

    done = [r for r in records if r.get("outcome") == success]
    rest = [r for r in records if r.get("outcome") != success]
    where = f' to "{paths.shorten_for_display(folder)}"' if folder else ""

    if not rest:
        return f"{verb} {_plural(len(done))}{where}."
    needs = "needs" if len(rest) == 1 else "need"
    if not done:
        opening = f"{_plural(len(rest))} {needs} your attention:"
    else:
        opening = (
            f"{verb} {len(done)} of {_plural(len(records))}{where}. "
            f"{len(rest)} {needs} your attention:"
        )

    lines = [
        f'"{paths.shorten_for_display(str(r.get("label") or ""))}" - {item_clause(operation, r)}'
        for r in rest[:named]
    ]
    remaining = len(rest) - len(lines)
    tail = f" And {_plural(remaining, 'other')} not listed here." if remaining > 0 else ""
    return f"{opening} {' '.join(lines)}{tail}"
