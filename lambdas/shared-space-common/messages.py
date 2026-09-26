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
sentence a user can act on in place of the generic clause — "that space has been deleted"
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
  _REFUSALS: Reason code to the sentence a REFUSED request is reported with. ``CreateNameUnusable``
    is the one entry that ends in a RULE rather than in a fact about this request, which is why it
    is the only one carrying wording from outside this module: it borrows
    ``cpcommon.config.CATALOG_IDENTIFIER_RULE`` rather than re-spelling the rule, because the
    browser's create dialog shows that same string and the two refusing one name with two
    descriptions of it is how a user concludes the two disagree. Separate from the
    table above because these name the target, which the failure path cannot: the notifier's
    input carries an action and a space and nothing else, so a refusal that has to say WHICH
    member is not a member must arrive with its sentence already composed. **One table, not one
    per action** — a second table would satisfy a key-set equality test while every member
    refusal told the user their TRANSFER had failed, because that is what this table's fallback
    says. ``MemberRequestRefused`` is the odd entry: it is a wording no code returns, rendered in
    place of the four request-level member refusals when a requester rather than an operator
    asked, so that four true sentences do not become an oracle for whether a space exists.
  _UNKNOWN_ACTION: What an unrecognised or absent action reads as. It is reachable: a failure
    before the validator has bound the context has no action at all, and an envelope from a
    producer newer than this layer can carry one this table has never heard of. Naming nothing
    beats naming the wrong thing.
"""

from cpcommon import messages as _cpmessages
from cpcommon.config import CATALOG_IDENTIFIER_RULE

__all__ = ["failure_message", "refusal_message", "transfer_notifications"]

_ACTION_PHRASES = {
    "create": "create shared space",
    "add_members": "add members to the shared space",
    "remove_members": "remove members from the shared space",
    "leave": "leave the shared space",
    "delete": "delete the shared space",
    "forget": "dismiss the shared space",
    "acknowledge_membership": "confirm your membership of the shared space",
    "transfer_ownership": "transfer the shared space",
}

_UNKNOWN_ACTION = "complete that shared space request"

_DOMAIN_REASONS = {
    "SpaceHasNoOwner": "that space has been deleted",
    "SpaceAlreadyEmptied": "that space has been deleted",
    "SpaceNeverActive": "that space hasn't finished being set up",
    "RegistryRecordMissing": "we couldn't find that space",
    "MembersRemainAfterEmpty": "some members' access could not be removed, so please try again",
    "RegistryRecordResurrected": "someone changed that space while it was being removed, so please try again",
    "OwnerChanged": "that space changed hands while your request was being processed",
    "TransferTargetNoLongerMember": (
        "the person you named is no longer a member of that space, so add them to it again "
        "before transferring it"
    ),
}

_REFUSALS = {
    "CreateNameUnusable": (
        'We couldn\'t create a shared space called "{space}". ' + CATALOG_IDENTIFIER_RULE
    ),
    "TransferSpaceUnknown": 'We couldn\'t find a shared space called "{space}".',
    "TransferTargetMissing": 'That request to transfer "{space}" named nobody to transfer it to.',
    "TransferNotOwner": 'Only the owner of "{space}" can transfer it.',
    "TransferTargetNotMember": (
        '{target} is not a member of "{space}", so it cannot be transferred to them. '
        "Add them to the space first."
    ),
    "TransferTargetIsOwner": '{target} already owns "{space}", so there is nothing to transfer.',
    "TransferSpaceNotActive": 'The shared space "{space}" is still being set up, so it cannot be transferred yet.',
    "TransferSpaceEmptied": 'The shared space "{space}" has been deleted, so it cannot be transferred.',
    "TransferOriginUntrusted": 'That request against "{space}" did not come from a trusted sender, so it was refused.',
    "TransferOriginNotConfigured": (
        'That request against "{space}" could not be checked, so it was refused. '
        "Please contact the Administrator."
    ),
    "TransferOriginBothCredentials": (
        'That request against "{space}" carried two conflicting identities, so it was refused.'
    ),
    "TransferOriginActionNotAllowed": (
        'That request against "{space}" is not one an operator may make, so it was refused.'
    ),
    "TransferOriginUnknown": 'That request against "{space}" declared an origin this service does not accept.',
    "MemberSpaceUnknown": 'We couldn\'t find a shared space called "{space}".',
    "MemberSpaceEmptied": (
        'The shared space "{space}" has been deleted, so its members cannot be changed.'
    ),
    "MemberSpaceNotActive": (
        'The shared space "{space}" is still being set up, so its members cannot be changed yet.'
    ),
    "MemberNotOwner": 'Only the owner of "{space}" can change who belongs to it.',
    "MemberTargetsMissing": 'That request against "{space}" named nobody to add or remove.',
    "MemberRemoveOwner": (
        '{target} owns "{space}", so they cannot be removed from it. '
        "Transfer the space to someone else first."
    ),
    "MemberRequestRefused": (
        'We couldn\'t change who belongs to the shared space "{space}".'
    ),
}

_resolver = _cpmessages.register(_DOMAIN_REASONS)


def refusal_message(code: str, space: str = "", target: str = "") -> str:
    """Composes the sentence a refused shared-space request is reported with.

    Separate from ``failure_message`` because a refusal and a fault answer different questions. A
    fault says which action could not be completed and offers a generic clause; a refusal has to
    name the thing that was wrong, and for a transfer that is usually the TARGET — "that person
    is not a member" is useless without saying which person, and the failure path cannot say it
    because the notifier's input carries the action and the space and nothing else.

    An unregistered code degrades to the generic transfer sentence rather than rendering the code
    itself: a reason code is operator text and this string is read by a user.

    Args:
      code: The refusal's reason code.
      space: The space name. Coerced to empty rather than interpolated as given: a message from a
        producer this service does not control can omit it, and a Python ``None`` rendered into a
        sentence a user reads is worse than a blank pair of quotes.
      target: The named member, where the refusal has one. Coerced for the same reason.

    Returns:
      The full sentence.

    Raises:
      None.
    """
    space = space or ""
    target = target or ""
    template = _REFUSALS.get(code)
    if template is None:
        return f'We couldn\'t transfer the shared space "{space}".'
    return template.format(space=space, target=target)


def transfer_notifications(space: str, outgoing: str, incoming: str) -> tuple[str, str]:
    """The pair of sentences a completed transfer sends, outgoing owner first.

    Both are literals here rather than f-strings at the verb, so the two halves of one event are
    worded together and a later edit cannot leave them disagreeing about what happened. Only the
    two people whose role changed are told, so neither sentence is written to be readable by a
    bystander.

    Args:
      space: The space name.
      outgoing: The owner handing the space on.
      incoming: The member taking it.

    Returns:
      A ``(to_outgoing, to_incoming)`` pair.

    Raises:
      None.
    """
    return (
        f'You transferred the shared space "{space}" to {incoming}. You are still a member of it.',
        f'{outgoing} transferred the shared space "{space}" to you. You are now its owner.',
    )


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
