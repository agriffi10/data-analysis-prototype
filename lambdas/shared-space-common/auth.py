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
