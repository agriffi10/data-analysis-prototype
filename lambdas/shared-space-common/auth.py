"""Action authorization for the shared-space control plane.

The security boundary, and after the trust flip it is the WHOLE of this module's job.

Establishing *who is asking* moved to the API, which verifies the bearer at the edge and stamps
the result into the message; ``cpcommon.actor`` reads it. What never moved, and must not, is
deciding *what they may do* — this authorizer, gating each action against the registry as a pure
function. The two are easy to conflate and dropping the second would remove the product's
isolation while every legitimate user's experience stayed identical.

So this module lost its verification adapter and kept everything domain-shaped: the exception
type, since this plane's Standard Step Function catches its own; the exact message strings; and
the authorizer itself, whose signature never changed — it always took a plain username, and only
where that string comes from is different.

``membership`` is imported for its one normaliser and nothing else. A predicate that compared
targets in a form the verb does not apply would refuse the wrong ones and let the right ones
through silently, and a second copy of the rule here is exactly how those two would drift.

Attributes:
  MEMBER_REFUSAL_CODES: Every code ``member_refusal`` can return.
  REFUSAL_MESSAGE_KEYS: Every key ``_refusal`` may RENDER, which is a superset: it also holds
    the collapsed wording the requester-facing path substitutes, which is never a return value.
    A test holds this set equal to the message table's keys, so a code with no sentence cannot
    ship.
  _COLLAPSED_TO_REQUESTER: The wording key the four request-level MEMBER refusals share when a
    requester asked. Their codes stay distinct — the run record still says which fired — and
    only the sentence collapses, because four discriminating sentences delivered into the inbox
    of whoever asked, for any space name they care to try, is the shared-space directory this
    project already declined to publish. **``transfer_refusal`` below composes without it and is
    still an oracle of exactly that shape**: pre-existing, deliberately not inherited into two
    more actions here, and deliberately not fixed here either — it is a named follow-up in the
    register, and ``_refusal`` already takes the argument the narrowing would need.
"""

import membership
import messages

import config

MEMBER_REFUSAL_CODES = frozenset(
    {
        "MemberSpaceUnknown",
        "MemberSpaceEmptied",
        "MemberSpaceNotActive",
        "MemberNotOwner",
        "MemberTargetsMissing",
        "MemberRemoveOwner",
    }
)

_COLLAPSED_TO_REQUESTER = "MemberRequestRefused"

REFUSAL_MESSAGE_KEYS = (
    frozenset(
        {
            "TransferSpaceUnknown",
            "TransferTargetMissing",
            "TransferNotOwner",
            "TransferTargetNotMember",
            "TransferTargetIsOwner",
            "TransferSpaceNotActive",
            "TransferSpaceEmptied",
            "TransferOriginUntrusted",
            "TransferOriginNotConfigured",
            "TransferOriginBothCredentials",
            "TransferOriginActionNotAllowed",
            "TransferOriginUnknown",
        }
    )
    | MEMBER_REFUSAL_CODES
    | {_COLLAPSED_TO_REQUESTER}
)


class AuthorizationError(Exception):
    """An untrusted or unauthorized request. Terminal, never retried, with no side effects."""


def authorize(action, space, actor, registry):
    """Authorizes an actor for one action on one space. Pure — no AWS calls.

    Creating is always allowed. Forgetting is a self-scoped clear, allowed even when the space
    has no registry record, such as a collision phantom or an orphaned projection; the forget
    verb itself enforces the safety matrix and refuses an active space the actor belongs to.
    Acknowledging membership is owner-exempt, since the owner is always active, and otherwise
    member-only — the same membership gate as leaving.

    **Three actions return here and are decided elsewhere** — ``transfer_ownership`` by
    ``transfer_refusal``, and the two in ``config.MEMBER_ACTIONS`` by ``member_refusal`` — each
    of which returns rather than raises. That is not a gap. Every refusal this function makes is
    a raise, and a raise in the validator is caught by a state whose input was the raw queue
    batch — so it seeds a null actor and a null space, and the notifier treats a null actor as no
    trustworthy recipient and stays silent. Those refusals have to name the space and the member
    they are about, so they travel as a value instead.

    **The branches are explicit and the function ends in a raise**, and after the member actions
    moved out the second of those stopped being cosmetic. This function used to end by falling
    off the bottom, which means allowed — harmless only while every action in ``VALID_ACTIONS``
    was caught by a branch above. Two actions are now deliberately allowed here and gated
    elsewhere, so losing the ``member_refusal`` call would be an open door rather than a refusal,
    and an action that reaches the bottom is refused instead.

    Args:
      action: The requested action.
      space: The space name, used in the failure messages.
      actor: The verified username.
      registry: The loaded registry record, or None for a create or a missing space.

    Returns:
      None, when the action is allowed.

    Raises:
      AuthorizationError: On an unknown action, an action this function has no branch for, a
        missing space, an owner-only action attempted by a non-owner, an owner trying to leave
        their own space, or a non-member attempting a member-only action.
    """
    if action not in config.VALID_ACTIONS:
        raise AuthorizationError(f"unknown action: {action!r}")
    if action == "create":
        return
    if action == "forget":
        return
    if action == "transfer_ownership":
        return
    if action in config.MEMBER_ACTIONS:
        return
    if registry is None:
        raise AuthorizationError(f"space {space!r} does not exist")
    owner = registry.get("owner")
    members = registry.get("members", [])
    if action in config.OWNER_ONLY_ACTIONS:
        if actor != owner:
            raise AuthorizationError(f"{action} on {space!r} is owner-only")
        return
    if action == "leave":
        if actor == owner:
            raise AuthorizationError("owner cannot leave their own space (delete it instead)")
        if actor not in members:
            raise AuthorizationError(f"{actor!r} is not a member of {space!r}")
        return
    if action == "acknowledge_membership":
        if actor == owner:
            raise AuthorizationError("owner does not acknowledge membership")
        if actor not in members:
            raise AuthorizationError(f"{actor!r} is not a member of {space!r}")
        return
    raise AuthorizationError(f"unhandled action: {action!r}")


def transfer_refusal(requester, space, target, registry):
    """Decides whether one ownership transfer may proceed. Pure — no AWS calls.

    Returns rather than raises, for the reason ``authorize``'s docstring gives. The order of the
    checks is load-bearing rather than stylistic: an emptied space has a blank roster, so a
    membership check reached first would refuse it with "that person is not a member". Both
    sentences are true and only one of them tells the user what actually happened.

    **A requester of ``None`` means an operator**, and is what makes the owner check skippable
    for exactly that case without a second flag. Written as a flag the check would pass for an
    operator anyway — the acting identity recorded for one is the space's own owner, so it would
    compare equal — and the skip could then be deleted with every test still green. ``None``
    compares equal to no owner, so removing the guard makes every operator transfer refuse.

    A target whose join status is ``pending`` is accepted. Pending records that they have not
    signed in since being added, not their entitlement — access was granted at add time — and
    refusing would make a space untransferable for a reason its owner cannot fix.

    Args:
      requester: The verified username asking, or None for an operator-origin request.
      space: The space name.
      target: The member named to take the space.
      registry: The loaded registry record, or None when the space is unknown.

    Returns:
      A ``(code, message)`` pair, or None when the transfer may proceed.

    Raises:
      None.
    """
    if registry is None:
        return _refusal("TransferSpaceUnknown", space)
    if not registry.get("owner") or registry.get("emptiedAt"):
        return _refusal("TransferSpaceEmptied", space)
    if registry.get("status") != "active":
        return _refusal("TransferSpaceNotActive", space)
    owner = registry.get("owner")
    if requester is not None and requester != owner:
        return _refusal("TransferNotOwner", space)
    if not isinstance(target, str) or not target:
        return _refusal("TransferTargetMissing", space)
    if target == owner:
        return _refusal("TransferTargetIsOwner", space, target)
    if target not in registry.get("members", []):
        return _refusal("TransferTargetNotMember", space, target)
    return None


def member_refusal(requester, space, action, targets, registry):
    """Decides one add_members or remove_members request. Pure — no AWS calls.

    The order of the checks is load-bearing rather than stylistic, for the reason
    ``transfer_refusal`` gives: an emptied space has a blank roster, so a membership question
    reached first refuses it with "that person is not a member" of a space that no longer has
    members. Both sentences are true and only one says what happened.

    **A requester of ``None`` means an operator**, and is what skips the owner check for exactly
    that case. It must not be written against the context's ``actor``: the validator records an
    operator request's actor as the space's OWN CURRENT OWNER, so an owner check written against
    that field passes for an operator without the skip, and the skip could then be deleted with
    every test still green.

    **The four request-level refusals collapse to one sentence when a requester asked**, and keep
    their distinct codes so the run still records which fired. Four discriminating sentences,
    delivered into the inbox of whoever asked for any space name they care to try, is an
    existence oracle over every shared space — the disclosure this project declined when it
    refused to publish a shared-space directory. An operator's refusal keeps the detail, because
    the space's owner is the person it reaches and is entitled to it. This narrows the MEMBER
    path only; ``transfer_refusal`` still discloses the same four facts and is a recorded
    follow-up rather than something fixed in passing here.

    ``targets`` is checked as the LIST the wire carries and again in the form the verb will
    normalise it to. The API's contract does refuse a browser's ``members`` that is not a list of
    strings, so what this covers is the other producer: **the reader builds its own body and
    nothing validates that one**, and even from a browser a ``payload`` carrying no ``members``
    key at all arrives here. A list that normalises to nothing — ``["  "]`` reaches the predicate
    from either side — would otherwise let the verb report success having done nothing.

    A request-level condition refuses the whole request; so does the one per-name condition, a
    removal naming the owner, because partly serving an operator is worse than telling them.

    Args:
      requester: The verified username asking, or None for an operator-origin request.
      space: The space name.
      action: The requested action, which decides whether the owner may be named as a target.
      targets: The member names the request carries, as the wire carries them.
      registry: The loaded registry record, or None when the space is unknown.

    Returns:
      A ``(code, message)`` pair, or None when the change may proceed.

    Raises:
      None.
    """
    collapsed = _COLLAPSED_TO_REQUESTER if requester is not None else None
    if registry is None:
        return _refusal("MemberSpaceUnknown", space, wording=collapsed)
    if not isinstance(registry.get("owner"), str) or not registry.get("owner"):
        return _refusal("MemberSpaceEmptied", space, wording=collapsed)
    if registry.get("emptiedAt"):
        return _refusal("MemberSpaceEmptied", space, wording=collapsed)
    if registry.get("status") != "active":
        return _refusal("MemberSpaceNotActive", space, wording=collapsed)
    owner = registry["owner"]
    if requester is not None and requester != owner:
        return _refusal("MemberNotOwner", space, wording=collapsed)
    if not isinstance(targets, list):
        return _refusal("MemberTargetsMissing", space)
    named = membership.normalize_members(targets, "")
    if action == "remove_members" and owner.strip().lower() in named:
        return _refusal("MemberRemoveOwner", space, owner)
    if not named:
        return _refusal("MemberTargetsMissing", space)
    return None


def operator_refusal(origin, action, space, has_identity, sender_id):
    """Decides whether a message declaring an operator origin may be trusted. Pure.

    The queue's other producer. A UI request reaches the plane through the API, which verifies a
    bearer and stamps an identity block; an operator has no bearer to offer, so the only
    attributable fact their message carries is the ``SenderId`` SQS stamps on it — a message
    SYSTEM attribute a ``SendMessage`` cannot set. No SQS condition key reaches a message body,
    so this comparison is the boundary and there is nothing else it could be.

    The order is copied from the notifications boundary and carries the same reasoning, inverted:
    that one refuses a sender it recognises, this one accepts only a sender it recognises. **The
    unset configuration is tested before the sender**, so a deployment that never wired the role
    id reports itself in every case rather than describing a broken message. The empty role-id
    half is refused separately, so an absent sender can never compare equal to an unset variable.
    The comparison is equality on that half rather than a prefix test, which would also match a
    different role whose unique id merely starts the same way, and never against a role name or
    ARN, neither of which ``SenderId`` carries.

    Args:
      origin: The message's declared origin. None means an ordinary UI request and is accepted
        here without further checks, because the identity block is what authenticates that one.
      action: The requested action.
      space: The space named, so the refusal can say which one. It reaches the space's OWNER —
        the named victim of a forgery — and a sentence that names no space tells them nothing
        they can act on.
      has_identity: Whether the message also carries an identity block.
      sender_id: The ``SenderId`` SQS stamped on the record, empty when it carried none.

    Returns:
      A ``(code, message)`` pair, or None when the message may proceed.

    Raises:
      None.
    """
    if origin is None:
        return None
    if origin != config.OPERATOR_ORIGIN:
        return _refusal("TransferOriginUnknown", space)
    if has_identity:
        return _refusal("TransferOriginBothCredentials", space)
    if action not in config.OPERATOR_ACTIONS:
        return _refusal("TransferOriginActionNotAllowed", space)
    configured = config.TRANSFER_READER_ROLE_ID
    if not configured:
        return _refusal("TransferOriginNotConfigured", space)
    role_id = (sender_id or "").split(":", 1)[0]
    if not role_id or role_id != configured:
        return _refusal("TransferOriginUntrusted", space)
    return None


def _refusal(code, space, target="", wording=None):
    """Pairs a reason code with the sentence a user reads for it.

    ``wording`` renders a DIFFERENT registered key's sentence while still returning ``code``.
    That split is the whole of how four member refusals reach a requester as one sentence that
    distinguishes nothing while the execution record keeps saying which of them fired — the
    refused seed carries the code, the notification carries the sentence.

    Both keys are checked against ``REFUSAL_MESSAGE_KEYS`` rather than left to the resolver,
    which degrades an unregistered key to a generic clause about a TRANSFER. Silently: a member
    refusal rendered through it would tell the user their workspace could not be transferred,
    which is not what they asked for and not what happened. The raise is loud in the wrong place
    — it lands in the validator, whose catch nulls the actor, so nobody is notified at all — and
    that is acceptable only because it cannot reach production: a test holds this set equal to
    the message table's keys, so an unregistered key fails the build.

    Args:
      code: The refusal's reason code, and what is returned.
      space: The space name.
      target: The named member, where the refusal has one.
      wording: A registered key to render INSTEAD of ``code``, or None to render ``code``.

    Returns:
      A ``(code, message)`` pair.

    Raises:
      ValueError: When either key is not registered in ``REFUSAL_MESSAGE_KEYS``.
    """
    for key in (code, wording or code):
        if key not in REFUSAL_MESSAGE_KEYS:
            raise ValueError(f"unregistered refusal key: {key!r}")
    return code, messages.refusal_message(wording or code, space, target)
