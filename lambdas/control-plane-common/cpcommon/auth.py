"""Cognito ID-token verification — every control plane's security boundary (SPEC-107).

``verified_username`` derives the actor from a verified Cognito ID token
(issuer/audience/expiry/signature checked offline against the pool JWKS) — never from a
body-asserted username. Any failure is a terminal ``unauthorized``: never retried, no
side effects.

The only difference between the old tbcommon/tscommon copies was the "no token" detail
string ("missing idToken" vs "missing actor token"); it is a parameter here so each
domain keeps its exact wording (SPEC-107 FR-002).
"""

import jwt

from . import clients, config
from .errors import TerminalError


def verified_username(id_token: str, *, missing_token_detail: str = "missing idToken") -> str:
    """Verify a Cognito ID token and return the trusted ``cognito:username``.

    ``missing_token_detail`` is the ``TerminalError`` detail raised when no token is
    supplied — the caller's domain wording ("missing idToken" for table-builder,
    "missing actor token" for table-share).
    """
    if not id_token:
        raise TerminalError("unauthorized", missing_token_detail)
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
        raise TerminalError("unauthorized", f"token verification failed: {exc}") from exc

    if claims.get("token_use") != "id":
        raise TerminalError("unauthorized", "not an ID token")
    username = claims.get("cognito:username")
    if not username:
        raise TerminalError("unauthorized", "token missing cognito:username")
    return username
