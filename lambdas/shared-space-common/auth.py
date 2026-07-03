"""Token verification and action authorization for the shared-space control plane.

The security boundary: ``verified_username`` derives the trusted actor from a verified
Cognito ID token (issuer/audience/expiry/signature against the pool JWKS) — never from
a body-asserted username. ``authorize`` is a pure function gating each action against
the registry. Both run in the validate-authorize Lambda; the verb Lambdas trust its
decision and never re-verify.
"""

import jwt

import config
import clients


class AuthorizationError(Exception):
    """An untrusted or unauthorized request; terminal (never retried), no side effects."""


def verified_username(id_token: str) -> str:
    """Verify a Cognito ID token and return the trusted ``cognito:username``."""
    if not id_token:
        raise AuthorizationError("missing idToken")
    issuer = f"https://cognito-idp.{config.REGION}.amazonaws.com/{config.USER_POOL_ID}"
    jwks_url = f"{issuer}/.well-known/jwks.json"
    try:
        signing_key = clients.jwks(jwks_url).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=config.APP_CLIENT_ID,
            issuer=issuer,
            options={"require": ["exp", "iss", "aud"]},
        )
    except Exception as exc:  # noqa: BLE001 - any verify failure = untrusted
        raise AuthorizationError(f"token verification failed: {exc}") from exc

    if claims.get("token_use") != "id":
        raise AuthorizationError("not an ID token")
    username = claims.get("cognito:username")
    if not username:
        raise AuthorizationError("token missing cognito:username")
    return username


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
