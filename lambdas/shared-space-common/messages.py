"""User-facing failure text for shared-space outcomes.

This plane got a resolver last. The other three each carry one; this one composed its wording
inline at each verb instead, which was adequate for as long as every failure was raised inside
a verb — the verb knew what it had been asked to do, so it could say so. What is not is an
execution that dies before or outside any verb's Python: a cold-start import error, a state
timeout, a task that cannot be invoked at all. The only code that runs then is a notifier
holding an action name and a raw Step Functions error, with no verb to borrow a sentence from.

The reason was deliberately not a lookup table for as long as every code reaching that path was
a raw engine name that may not be shown to a user, so what varied was the action rather than the
reason. **The table has entries now**, and they arrived exactly as that note anticipated: a
shared-space code registered later renders through the same path. What each one buys is a
sentence a user can act on in place of the generic clause — "that workspace has been deleted"
answers a member's question, where "please try again or contact the Administrator" invites them
to retry something that will never succeed.

The keys are **class names, verbatim and CamelCase**, and that is not a style slip. The shared
decoder only splits a reason code out of a Step Functions cause for a ``TerminalError``; for
every other exception it returns the engine's own ``Error`` field, which is the raised class's
name. So a key written in this file's neighbouring snake_case would match nothing and render the
generic clause — silently, which is the failure mode registering them exists to prevent.

The two refusals that mean "deleted" share one sentence while keeping separate codes: a caller
distinguishes them, a user does not need to.

The wording matches what this plane already sends from its own verbs, because a user cannot
tell which code emitted the message in their inbox and a second phrasing for the same event
would read as a second kind of problem. Kept ASCII — no smart quotes.

Attributes:
  _DOMAIN_REASONS: Reason code to the clause a user reads, keyed by the exception class name the
    engine reports. See above for why the casing is load-bearing.
  _ACTION_PHRASES: Action to the clause following "We couldn't ", with the space name appended
    in quotes. The action values are the Step Function's own, not a parallel vocabulary: they
    are the same strings the routing state branches on and the validator puts on the context,
    so an action added to the machine without a phrase here is visibly missing rather than
    silently mistranslated. Every phrase ends where the quoted name begins, so none needs a
    marker. The create phrase reads without an article on purpose, copied from the verb that
    already emits it — matching what users already receive beats an internal tidiness they will
    never see.
  _UNKNOWN_ACTION: What an unrecognised or absent action reads as. It is reachable: a failure
    before the validator has bound the context has no action at all, and an envelope from a
    producer newer than this layer can carry one this table has never heard of. Naming nothing
    beats naming the wrong thing.
"""

from cpcommon import messages as _cpmessages

__all__ = ["failure_message"]

_ACTION_PHRASES = {
    "create": "create shared workspace",
    "add_members": "add members to the shared workspace",
    "remove_members": "remove members from the shared workspace",
    "leave": "leave the shared workspace",
    "delete": "delete the shared workspace",
    "forget": "dismiss the shared workspace",
    "acknowledge_membership": "confirm your membership of the shared workspace",
}

_UNKNOWN_ACTION = "complete that shared workspace request"

_DOMAIN_REASONS = {
    "SpaceHasNoOwner": "that workspace has been deleted",
    "SpaceAlreadyEmptied": "that workspace has been deleted",
    "SpaceNeverActive": "that workspace hasn't finished being set up",
    "RegistryRecordMissing": "we couldn't find that workspace",
    "MembersRemainAfterEmpty": "some members' access could not be removed, so please try again",
    "RegistryRecordResurrected": "someone changed that workspace while it was being removed, so please try again",
}

_resolver = _cpmessages.register(_DOMAIN_REASONS)


def failure_message(action: str = "", space: str = "", reason: str = "") -> str:
    """Composes the actor-facing text for a shared-space request that failed.

    A missing space degrades to the un-named phrasing rather than rendering an empty pair of
    quotes, because the one failure with no space name is also the one where inventing detail
    would be least defensible. The unknown-action phrase takes no name either, whether or not
    one was supplied: only the table's phrases are written to have a quoted name appended, and
    pinning one to the fallback reads as broken English at exactly the moment the message is
    already vaguest.

    Args:
      action: The requested action.
      space: The space name, when one is known.
      reason: A code from the shared decoder. Passed through to the resolver, which answers with
        this domain's sentence for a registered code and falls back to the generic clause for
        anything else — which is still most of what reaches here, since a raw engine name has no
        wording and must not acquire one. It is never interpolated raw.

    Returns:
      The full sentence.

    Raises:
      None.
    """
    phrase = _ACTION_PHRASES.get(action)
    if phrase is None:
        return f"We couldn't {_UNKNOWN_ACTION}: {_resolver.body(reason)}"
    if space:
        phrase = f'{phrase} "{space}"'
    return f"We couldn't {phrase}: {_resolver.body(reason)}"
