"""Cognito ID-token verification — the control plane's security boundary.

verified_username derives the actor from a verified Cognito ID token
(issuer/audience/expiry/signature checked offline against the pool JWKS) — never from
a body-asserted username. Any failure is a terminal unauthorized: never retried, no
side effects.
"""

import jwt

from . import config, clients
from .errors import TerminalError


def verified_username(id_token: str) -> str:
    """Verify a Cognito ID token and return the trusted ``cognito:username``."""
    if not id_token:
        raise TerminalError("unauthorized", "missing idToken")
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
