"""User-facing failure text for shared-space outcomes (SPEC-152).

WHY THIS PLANE GOT A RESOLVER LAST. The other three control planes each carry a
``failure_message``; this one composed its wording inline at each verb instead, and that
was adequate for as long as every failure was raised INSIDE a verb — the verb knew what
it had been asked to do, so it could say so. SPEC-152 added the failure that is not: an
execution that dies before or outside any verb's Python (a cold-start import error, a
``States.Timeout``, a task that cannot be invoked at all). The only code that runs then
is a notifier holding an action name and a raw Step Functions error, with no verb to
borrow a sentence from.

THE REASON IS DELIBERATELY NOT A LOOKUP TABLE. Every code that can reach that path is a
raw engine name — ``States.Timeout``, ``Runtime.ImportModuleError``, ``Lambda.Unknown``,
``TransientError`` — and SPEC-106 FR-008 forbids showing any of them to a user. So what
varies here is the ACTION, not the reason: the resolver names the operation the user
asked for and ends on cpcommon's shared generic clause. The domain table is empty
because there is genuinely nothing to put in it, not because it was left unfinished —
and going through ``cpcommon.messages.register`` rather than hard-coding the clause
means a shared-space reason code registered later renders through the same path, as do
the shared base codes (``unauthorized`` and friends) if a verb ever raises one.

THE WORDING MATCHES WHAT THIS PLANE ALREADY SENDS. ``create_space`` and ``delete_space``
notify their own failures as ``We couldn't <verb> the shared workspace "<name>": …``,
and a user cannot tell which code emitted the message in their inbox — so a second
phrasing for the same event would read as a second kind of problem. Kept ASCII (no smart
quotes), mirroring tbcommon/tscommon.messages.
"""

from cpcommon import messages as _cpmessages

__all__ = ["failure_message"]

#: action -> the clause after "We couldn't ", with the space name appended in quotes.
#:
#: The ACTION VALUES ARE THE STEP FUNCTION'S, not a parallel vocabulary: they are the
#: same strings the Route state branches on and the same ones the validator puts on the
#: context, so an action added to the machine without a phrase here is visibly missing
#: rather than silently mistranslated. Every phrase ends where the quoted space name
#: begins, so none of them needs a marker.
#
# `create` READS WITHOUT "the" ON PURPOSE, and the inconsistency with its neighbours is
# copied deliberately from the verbs: create_space emits 'We couldn't create shared
# workspace "x"' and delete_space emits 'We couldn't delete the shared workspace "x"'.
# A user cannot tell which code sent the message in their inbox, so matching what they
# already receive beats an internal tidiness they will never see.
_ACTION_PHRASES = {
    "create": "create shared workspace",
    "add_members": "add members to the shared workspace",
    "remove_members": "remove members from the shared workspace",
    "leave": "leave the shared workspace",
    "delete": "delete the shared workspace",
    "forget": "dismiss the shared workspace",
    "acknowledge_membership": "confirm your membership of the shared workspace",
}

#: What an unrecognised or absent action reads as. It is reachable: a failure BEFORE the
#: validator has bound the context has no action at all, and an envelope from a producer
#: newer than this layer can carry one this table has never heard of. Naming nothing
#: beats naming the wrong thing.
_UNKNOWN_ACTION = "complete that shared workspace request"

_resolver = _cpmessages.register({})


def failure_message(action: str = "", space: str = "", reason: str = "") -> str:
    """The actor-facing text for a shared-space request that failed.

    ``reason`` is a code from ``cpcommon.errors.failure_reason`` — passed through to the
    resolver, which falls back to the generic clause for anything it does not know (which
    today is everything that can reach this call site). It is never interpolated raw.

    A missing ``space`` degrades to the un-named phrasing rather than rendering an empty
    pair of quotes, because the one failure with no space name is also the one where
    inventing detail would be least defensible. The unknown-action phrase takes NO name
    either, whether or not one was supplied: only the table's phrases are written to have
    a quoted name appended, and pinning one to the fallback reads as broken English at
    exactly the moment the message is already vaguest.
    """
    phrase = _ACTION_PHRASES.get(action)
    if phrase is None:
        return f"We couldn't {_UNKNOWN_ACTION}: {_resolver.body(reason)}"
    if space:
        phrase = f'{phrase} "{space}"'
    return f"We couldn't {phrase}: {_resolver.body(reason)}"
