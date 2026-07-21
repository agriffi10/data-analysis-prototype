"""Cognito ID-token verification — every control plane's security boundary (SPEC-107/125).

One JWKS-verification path for the whole repo. It used to be three: table-builder's,
table-share's, and shared-space's, each with its own copy of the claim checks. A fix to
any of them had to be made in every one, and would eventually have been made in one.

The layering exists because the callers disagree about exceptions, not about verification:

- ``verify_id_token`` does the work and raises ``cpcommon.errors.AuthError`` — the seam.
- ``verified_username`` maps that to ``TerminalError("unauthorized", …)`` for the
  table-builder / table-share / data-quality verbs.
- ``shared-space-common/auth.py`` maps it to its own ``AuthorizationError`` (SPEC-125),
  keeping the Standard Step Function's Catch behaviour exactly as it was.

Issuer, audience, signature, expiry and ``token_use`` are all checked offline against the
pool JWKS. ``verify_id_token_ignoring_expiry`` is the ONE relaxation, and it is a separate
named function rather than a flag — see its docstring.
"""

import jwt

from . import clients, config
from .errors import AuthError, TerminalError


def _verify(id_token: str, missing_token_detail: str, *, verify_exp: bool) -> dict:
    """Shared verification body. PRIVATE — the ``verify_exp`` flag never leaves this module.

    Every relaxation is exposed as its own named public function, so no caller can turn
    expiry off by passing one extra argument to the function every authorization path calls
    (SPEC-126 FR-002).
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
            # `require` is unchanged even when expiry is not ENFORCED: a token with no `exp`
            # at all is malformed, and accepting one would be a different relaxation than
            # the one asked for.
            options={"require": ["exp", "iss", "aud"], "verify_exp": verify_exp},
        )
    except Exception as exc:  # noqa: BLE001 - any verify failure = untrusted
        raise AuthError(f"token verification failed: {exc}") from exc

    if claims.get("token_use") != "id":
        raise AuthError("not an ID token")
    if not claims.get("cognito:username"):
        raise AuthError("token missing cognito:username")
    return claims


def verify_id_token(id_token: str, *, missing_token_detail: str = "missing idToken") -> dict:
    """Verify a Cognito ID token and return its claims. Raises ``AuthError`` on any failure.

    Issuer, audience, signature AND expiry are all enforced, ``token_use`` must be ``id``,
    and ``cognito:username`` must be present — so a caller can read that claim without
    re-checking it.

    ``missing_token_detail`` is the message raised when no token is supplied — each domain
    keeps its own wording ("missing idToken", "missing actor token").
    """
    return _verify(id_token, missing_token_detail, verify_exp=True)


def verify_id_token_ignoring_expiry(id_token: str, *, missing_token_detail: str = "missing idToken") -> dict:
    """Same verification, MINUS the expiry check. For the DLQ drain only (SPEC-126 FR-002).

    Signature, issuer and audience are still enforced, so the token still PROVES who sent
    the request; only ``exp`` is not enforced.

    WHY THIS EXISTS. A dead-lettered message is old by construction — three failed receives,
    then an unbounded wait in a 14-day queue — while a Cognito ID token lives one hour. A
    drain that enforced expiry would therefore drop exactly the late failures it exists to
    surface, and the user would hear nothing, which is the bug SPEC-126 is fixing.

    WHY IT IS SAFE HERE AND NOWHERE ELSE. That path GRANTS NOTHING. It reads no user data,
    writes to no user's space, and authorizes no action: it selects the recipient of a
    "your request couldn't be started" notification. An authentically signed token still
    names its subject long after it stops being usable as a credential.

    DO NOT reach for this from a verb. If a path can act on the user's behalf, it needs
    ``verify_id_token`` / ``verified_username``.
    """
    return _verify(id_token, missing_token_detail, verify_exp=False)


def verified_username(id_token: str, *, missing_token_detail: str = "missing idToken") -> str:
    """Verify a Cognito ID token and return the trusted ``cognito:username``.

    The ``TerminalError`` entry point — table-builder, table-share and data-quality. Every
    verification failure becomes ``TerminalError("unauthorized", …)`` with the detail text
    those verbs have always raised.
    """
    try:
        return verify_id_token(id_token, missing_token_detail=missing_token_detail)["cognito:username"]
    except AuthError as exc:
        raise TerminalError("unauthorized", str(exc)) from exc


def verified_username_ignoring_expiry(id_token: str, *, missing_token_detail: str = "missing idToken") -> str:
    """``verified_username`` without the expiry check — the DLQ drain's entry point (SPEC-126).

    See ``verify_id_token_ignoring_expiry`` for why the relaxation is safe on that path and
    nowhere else.
    """
    try:
        return verify_id_token_ignoring_expiry(id_token, missing_token_detail=missing_token_detail)[
            "cognito:username"
        ]
    except AuthError as exc:
        raise TerminalError("unauthorized", str(exc)) from exc
