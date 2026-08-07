"""Token verification and action authorization for the shared-space control plane.

The security boundary. The trusted actor is derived from a verified Cognito ID token, never
from a body-asserted username, and the authorizer is a pure function gating each action against
the registry. Both run in the validate verb; the verb Lambdas trust its decision and never
re-verify.

The JWKS verification itself lives once, in ``cpcommon.auth`` — this module kept its own copy
until the layers were consolidated, so a claim-validation fix had to be made twice. What stays
here is everything domain-shaped: the exception type, since this plane's Standard Step Function
catches its own; the exact message strings; and the whole authorizer.
"""

import config
from cpcommon import auth as cpauth
from cpcommon.errors import AuthError


class AuthorizationError(Exception):
    """An untrusted or unauthorized request. Terminal, never retried, with no side effects."""


def verified_username(id_token: str) -> str:
    """Verifies a Cognito ID token and returns the trusted username claim.

    A thin adapter over the shared verifier: identical verification, this control plane's
    exception type. The message strings are unchanged and pinned by test — the Catch keys off
    the type, but an operator reads the message, and nothing pinned these before, so a silent
    reword would have passed CI.

    Args:
      id_token: The raw JWT.

    Returns:
      The verified ``cognito:username``.

    Raises:
      AuthorizationError: On any verification failure.
    """
    try:
        return cpauth.verify_id_token(id_token)["cognito:username"]
    except AuthError as exc:
        raise AuthorizationError(str(exc)) from exc


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
