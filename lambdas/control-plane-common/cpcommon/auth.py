"""Cognito ID-token verification — every control plane's security boundary.

One JWKS-verification path for the whole repo. It used to be three, each with its own copy
of the claim checks, so a fix to any of them had to be made in every one and would
eventually have been made in one.

The claim was not true when it was written: ``notifications-writer`` was a fourth copy, and
not by oversight — this module reaches ``config``, which required six environment variables
at import, and that function sets two of them. The blocker was the cause of the duplication,
so SPEC-156 FR-004 removed the blocker (``config`` resolves on first access) and the copy
with it. A parity run over nine token shapes preceded the deletion.

The layering exists because the callers disagree about exceptions, not about verification:
``verify_id_token`` does the work and raises ``AuthError`` — the seam; ``verified_username``
maps that to ``TerminalError("unauthorized", …)`` for the table-builder, table-share and
data-quality verbs; ``shared-space-common/auth.py`` maps it to its own
``AuthorizationError``, keeping its Standard Step Function's Catch behaviour unchanged.

Issuer, audience, signature, expiry and ``token_use`` are all checked offline against the
pool JWKS.
"""

import jwt

from . import clients, config
from .errors import AuthError, TerminalError


def _verify(id_token: str, missing_token_detail: str, *, verify_exp: bool) -> dict:
    """Verifies a Cognito ID token against the pool JWKS and returns its claims.

    Private, and the ``verify_exp`` flag never leaves this module: every relaxation is
    exposed as its own named public function, so no caller can turn expiry off by passing
    one extra argument to the function every authorization path calls. ``require`` is
    unchanged even when expiry is not enforced — a token with no ``exp`` at all is
    malformed, and accepting one would be a different relaxation than the one asked for.

    Args:
      id_token: The raw JWT.
      missing_token_detail: Message to raise when no token was supplied.
      verify_exp: Whether to enforce the expiry claim.

    Returns:
      The decoded claims.

    Raises:
      AuthError: If the token is absent, fails any verification step, is not an ID token,
        or carries no ``cognito:username``.
    """
    if not id_token:
        raise AuthError(missing_token_detail)
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
            options={"require": ["exp", "iss", "aud"], "verify_exp": verify_exp},
        )
    except Exception as exc:
        raise AuthError(f"token verification failed: {exc}") from exc

    if claims.get("token_use") != "id":
        raise AuthError("not an ID token")
    if not claims.get("cognito:username"):
        raise AuthError("token missing cognito:username")
    return claims


def verify_id_token(id_token: str, *, missing_token_detail: str = "missing idToken") -> dict:
    """Verifies a Cognito ID token in full and returns its claims.

    Issuer, audience, signature and expiry are all enforced, ``token_use`` must be ``id``,
    and ``cognito:username`` must be present — so a caller can read that claim without
    re-checking it.

    Args:
      id_token: The raw JWT.
      missing_token_detail: Message raised when no token is supplied; each domain keeps its
        own wording.

    Returns:
      The verified claims.

    Raises:
      AuthError: On any verification failure.
    """
    return _verify(id_token, missing_token_detail, verify_exp=True)


def verify_id_token_ignoring_expiry(id_token: str, *, missing_token_detail: str = "missing idToken") -> dict:
    """Verifies a Cognito ID token without enforcing expiry. For the DLQ drain only.

    Signature, issuer and audience are still enforced, so the token still proves who sent
    the request; only ``exp`` is not enforced. A dead-lettered message is old by
    construction — three failed receives, then an unbounded wait in a 14-day queue — while a
    Cognito ID token lives one hour, so a drain that enforced expiry would drop exactly the
    late failures it exists to surface.

    It is safe here because that path grants nothing: it reads no user data, writes to no
    user's space and authorizes no action, only selecting the recipient of a "your request
    couldn't be started" notification. Do not reach for this from a verb — if a path can act
    on the user's behalf it needs ``verify_id_token`` or ``verified_username``.

    Args:
      id_token: The raw JWT.
      missing_token_detail: Message raised when no token is supplied.

    Returns:
      The verified claims.

    Raises:
      AuthError: On any verification failure other than expiry.
    """
    return _verify(id_token, missing_token_detail, verify_exp=False)


def verified_username(id_token: str, *, missing_token_detail: str = "missing idToken") -> str:
    """Verifies a Cognito ID token and returns the trusted username claim.

    The ``TerminalError`` entry point for the table-builder, table-share and data-quality
    verbs. Every verification failure becomes ``unauthorized`` with the detail text those
    verbs have always raised.

    Args:
      id_token: The raw JWT.
      missing_token_detail: Message raised when no token is supplied.

    Returns:
      The verified ``cognito:username``.

    Raises:
      TerminalError: With reason ``unauthorized`` on any verification failure.
    """
    try:
        return verify_id_token(id_token, missing_token_detail=missing_token_detail)["cognito:username"]
    except AuthError as exc:
        raise TerminalError("unauthorized", str(exc)) from exc


def verified_username_ignoring_expiry(id_token: str, *, missing_token_detail: str = "missing idToken") -> str:
    """Returns the trusted username claim without enforcing expiry — the DLQ drain's door.

    See ``verify_id_token_ignoring_expiry`` for why the relaxation is safe on that path and
    nowhere else.

    Args:
      id_token: The raw JWT.
      missing_token_detail: Message raised when no token is supplied.

    Returns:
      The verified ``cognito:username``.

    Raises:
      TerminalError: With reason ``unauthorized`` on any verification failure other than
        expiry.
    """
    try:
        return verify_id_token_ignoring_expiry(id_token, missing_token_detail=missing_token_detail)[
            "cognito:username"
        ]
    except AuthError as exc:
        raise TerminalError("unauthorized", str(exc)) from exc
