"""Token verification and action authorization for the shared-space control plane.

The security boundary: ``verified_username`` derives the trusted actor from a verified
Cognito ID token (issuer/audience/expiry/signature against the pool JWKS) — never from
a body-asserted username. ``authorize`` is a pure function gating each action against
the registry. Both run in the validate-authorize Lambda; the verb Lambdas trust its
decision and never re-verify.

SPEC-125: the JWKS VERIFICATION itself now lives once, in ``cpcommon.auth`` — this module
kept its own copy of it until then, so a claim-validation fix had to be made twice. What
stays here is everything domain-shaped: the exception TYPE (this control plane's Standard
Step Function Catches ``AuthorizationError``, not ``TerminalError``), the exact message
strings, and all of ``authorize``.
"""

import config
from cpcommon import auth as cpauth
from cpcommon.errors import AuthError


class AuthorizationError(Exception):
    """An untrusted or unauthorized request; terminal (never retried), no side effects."""


def verified_username(id_token: str) -> str:
    """Verify a Cognito ID token and return the trusted ``cognito:username``.

    A thin adapter over ``cpcommon.auth.verify_id_token``: identical verification, this
    control plane's exception type. The message strings are unchanged and pinned by test —
    the SFN Catch keys off the type, but an operator reads the message, and nothing pinned
    these before, so a silent reword would have passed CI.
    """
    try:
        return cpauth.verify_id_token(id_token)["cognito:username"]
    except AuthError as exc:
        raise AuthorizationError(str(exc)) from exc


def authorize(action, space, actor, registry):
    """Authorize ``actor`` for ``action`` on ``space``. Pure; raises on violation.

    ``registry`` is the loaded registry record, or None for create or a missing space.
    """
    if action not in config.VALID_ACTIONS:
        raise AuthorizationError(f"unknown action: {action!r}")
    if action == "create":
        return
    if action == "forget":
        # Self-scoped clear: allowed even when the space has no registry record (a
        # collision phantom or orphaned projection). The forget verb itself enforces
        # the safety matrix, refusing an active space the actor belongs to.
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
        # A member confirming they've picked up the space (SPEC-073). Owner-exempt (the
        # owner is always active) and member-only — same membership gate as leave.
        if actor == owner:
            raise AuthorizationError("owner does not acknowledge membership")
        if actor not in members:
            raise AuthorizationError(f"{actor!r} is not a member of {space!r}")
        return
