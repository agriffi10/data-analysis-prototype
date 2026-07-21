"""Cognito ID-token verification — every control plane's security boundary (SPEC-107).

``verified_username`` derives the actor from a verified Cognito ID token
(issuer/audience/expiry/signature checked offline against the pool JWKS) — never from a
body-asserted username. Any failure is a terminal ``unauthorized``: never retried, no
side effects.

The only difference between the old tbcommon/tscommon copies was the "no token" detail
string ("missing idToken" vs "missing actor token"); it is a parameter here so each
domain keeps its exact wording (SPEC-107 FR-002).

``verified_username_ignoring_expiry`` (SPEC-126) is the ONE relaxation, and it is a
separate public function rather than a flag — see its docstring.
"""

import jwt

from . import clients, config
from .errors import TerminalError


def _verified_username(id_token: str, missing_token_detail: str, *, verify_exp: bool) -> str:
    """Shared verification body. PRIVATE — the ``verify_exp`` flag never leaves this module.

    Every relaxation is exposed as its own named public function above, so no caller can
    turn expiry off by passing one extra argument to the function every authorization path
    calls (SPEC-126 FR-002).
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
            # `require` is unchanged even when expiry is not ENFORCED: a token with no `exp`
            # at all is malformed, and accepting one would be a different relaxation than
            # the one asked for.
            options={"require": ["exp", "iss", "aud"], "verify_exp": verify_exp},
        )
    except Exception as exc:  # noqa: BLE001 - any verify failure = untrusted
        raise TerminalError("unauthorized", f"token verification failed: {exc}") from exc

    if claims.get("token_use") != "id":
        raise TerminalError("unauthorized", "not an ID token")
    username = claims.get("cognito:username")
    if not username:
        raise TerminalError("unauthorized", "token missing cognito:username")
    return username


def verified_username(id_token: str, *, missing_token_detail: str = "missing idToken") -> str:
    """Verify a Cognito ID token and return the trusted ``cognito:username``.

    Issuer, audience, signature AND expiry are all enforced. This is the function every
    authorization path calls.

    ``missing_token_detail`` is the ``TerminalError`` detail raised when no token is
    supplied — the caller's domain wording ("missing idToken" for table-builder,
    "missing actor token" for table-share).
    """
    return _verified_username(id_token, missing_token_detail, verify_exp=True)


def verified_username_ignoring_expiry(
    id_token: str, *, missing_token_detail: str = "missing idToken"
) -> str:
    """Same verification, MINUS the expiry check. For the DLQ drain only (SPEC-126 FR-002).

    Signature, issuer and audience are still enforced, so the token still PROVES who sent
    the request; only ``exp`` is not enforced.

    WHY THIS EXISTS. A dead-lettered message is old by construction — three failed receives,
    then an unbounded wait in a 14-day queue — while a Cognito ID token lives one hour. A
    drain that enforced expiry would therefore drop exactly the late failures it exists to
    surface, and the user would hear nothing, which is the bug SPEC-126 is fixing.

    WHY IT IS SAFE HERE AND NOWHERE ELSE. This path GRANTS NOTHING. It reads no user data,
    writes to no user's space, and authorizes no action: it selects the recipient of a
    "your request couldn't be started" notification. An authentically signed token still
    names its subject long after it stops being usable as a credential.

    DO NOT reach for this from a verb. If a path can act on the user's behalf, it needs
    ``verified_username``.
    """
    return _verified_username(id_token, missing_token_detail, verify_exp=False)
