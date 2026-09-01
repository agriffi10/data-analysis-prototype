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
"""

import messages

import config


class AuthorizationError(Exception):
    """An untrusted or unauthorized request. Terminal, never retried, with no side effects."""


def authorize(action, space, actor, registry):
    """Authorizes an actor for one action on one space. Pure — no AWS calls.

    Creating is always allowed. Forgetting is a self-scoped clear, allowed even when the space
    has no registry record, such as a collision phantom or an orphaned projection; the forget
    verb itself enforces the safety matrix and refuses an active space the actor belongs to.
    Acknowledging membership is owner-exempt, since the owner is always active, and otherwise
    member-only — the same membership gate as leaving.

    **Transferring returns here and is decided by ``transfer_refusal``**, which returns rather
    than raises. That is not a gap. Every refusal this function makes is a raise, and a raise in
    the validator is caught by a state whose input was the raw queue batch — so it seeds a null
    actor and a null space, and the notifier treats a null actor as no trustworthy recipient and
    stays silent. A transfer's refusals have to name the space and the member they are about, so
    they travel as a value. The branch is explicit rather than left to fall through the bottom of
    this function, because falling through reads as an oversight and is one action away from
    being one.

    Args:
      action: The requested action.
      space: The space name, used in the failure messages.
      actor: The verified username.
      registry: The loaded registry record, or None for a create or a missing space.

    Returns:
      None, when the action is allowed.

    Raises:
      AuthorizationError: On an unknown action, a missing space, an owner-only action attempted
        by a non-owner, an owner trying to leave their own space, or a non-member attempting a
        member-only action.
    """
    if action not in config.VALID_ACTIONS:
        raise AuthorizationError(f"unknown action: {action!r}")
    if action == "create":
        return
    if action == "forget":
        return
    if action == "transfer_ownership":
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


def _refusal(code, space, target=""):
    """Pairs a reason code with the sentence a user reads for it.

    Args:
      code: The refusal's reason code.
      space: The space name.
      target: The named member, where the refusal has one.

    Returns:
      A ``(code, message)`` pair.

    Raises:
      None.
    """
    return code, messages.refusal_message(code, space, target)
