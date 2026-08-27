"""ID-token verification — every control plane's and the API's one security boundary.

One JWKS-verification path for the whole repo. It used to be three, each with its own copy
of the claim checks, so a fix to any of them had to be made in every one and would
eventually have been made in one.

The claim was not true when it was written: ``notifications-writer`` was a fourth copy, and
not by oversight — this module reaches ``config``, which required six environment variables
at import, and that function sets three of them. The blocker was the cause of the duplication,
so that blocker is gone (``config`` resolves on first access) and the copy
with it. A parity run over nine token shapes preceded the deletion.

**The checks are now driven by a ``VerifierConfig`` rather than by a Cognito-shaped constant**,
because the target environment may issue tokens from a provider that is not Cognito at all — and
if it does, swapping providers must be a configuration change rather than a rewrite of every
authorization path in the product. Issuer, audience, JWKS URI, the username claim and the
required-claims map are all parameters. Nothing below names a provider; the Cognito values live
in ``_cognito_config`` alone, which is what the existing entry points pass.

The layering exists because the callers disagree about exceptions, not about verification:
``verify_token`` does the work and raises ``AuthError`` — the seam; ``verify_id_token`` and
``verified_username`` restate that as the wording each control plane has always raised;
``shared-space-common/auth.py`` maps it to its own ``AuthorizationError``, keeping its Standard
Step Function's Catch behaviour unchanged.

**A reason code is not a message.** ``verify_token`` raises a fixed literal, never an
interpolated provider string, and chains the provider exception as ``__cause__``. An
internet-facing caller reads the code and never touches the cause; the control planes rebuild
their historical wording from the cause, whose exposure is a queue body that is already redacted.
That split is what lets the API refuse to leak a provider message while the seven planes keep
byte-identical text.

**A key-retrieval fault is not an authentication failure.** ``PyJWKClientConnectionError``
subclasses ``PyJWKClientError``, so a single broad handler turns a provider outage into "your
token is bad" — which, at an API, tells every user to sign in again for something no user can
fix. It is raised as ``VerifierUnavailable`` instead, which is deliberately NOT an ``AuthError``
so that no ordering accident in a caller's ``except`` chain can recapture it.

Issuer, audience, signature, expiry and the required claims are all checked offline against the
provider's JWKS.

Attributes:
  REASON_MISSING_TOKEN: No token was supplied at all.
  REASON_VERIFICATION_FAILED: Signature, issuer, audience, expiry, or the token's own shape.
  REASON_REQUIRED_CLAIM: A claim the configuration requires is absent or holds another value.
  REASON_MISSING_USERNAME: The configured username claim is absent or empty.
  REASON_JWKS_UNAVAILABLE: The JWKS endpoint could not be reached. Not an auth failure.
  COGNITO_USERNAME_CLAIM: The claim Cognito carries a username in. The one provider-specific
    literal in this module, and it is confined to ``_cognito_config``.
  COGNITO_REQUIRED_CLAIMS: What a Cognito ID token must assert to be one.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

import jwt
from jwt.exceptions import PyJWKClientConnectionError

from . import clients, config
from .errors import AuthError, TerminalError

REASON_MISSING_TOKEN = "missing_token"
REASON_VERIFICATION_FAILED = "verification_failed"
REASON_REQUIRED_CLAIM = "required_claim_mismatch"
REASON_MISSING_USERNAME = "missing_username_claim"
REASON_JWKS_UNAVAILABLE = "jwks_unavailable"

COGNITO_USERNAME_CLAIM = "cognito:username"
COGNITO_REQUIRED_CLAIMS = MappingProxyType({"token_use": "id"})


class VerifierUnavailable(Exception):
    """The signing key could not be retrieved, so the token's validity is unknown.

    Deliberately not an ``AuthError`` and deliberately not declared in ``errors``: a caller that
    maps ``AuthError`` to "unauthenticated" must not capture this by inheritance, because the
    honest answer to "is this token good?" here is "the provider did not answer", which is a
    server-side fault and not the caller's. An API answering 401 to it would tell every user to
    sign in again for an outage signing in cannot fix.
    """


@dataclass(frozen=True)
class VerifierConfig:
    """Everything the verifier needs that differs between providers.

    Attributes:
      issuer: The exact ``iss`` a token must carry.
      audience: The exact ``aud`` a token must carry — the client the token was issued to.
      jwks_uri: Where the signing keys are published. **Configured, never concatenated from
        the issuer**: Cognito happens to publish at ``{issuer}/.well-known/jwks.json`` and
        other providers do not, so deriving it would reintroduce the provider assumption this
        type exists to remove.
      username_claim: Which claim carries the username this product keys everything on.
      required_claims: Claim name to the exact value it must hold. May be empty.
    """

    issuer: str
    audience: str
    jwks_uri: str
    username_claim: str
    required_claims: Mapping[str, str]


@dataclass(frozen=True)
class Principal:
    """The verified caller. Constructed only by a successful verification.

    Attributes:
      username: The value of the configured username claim, verified rather than asserted.
      claims: The verified claim set, whole.
    """

    username: str
    claims: Mapping[str, object]


def _verify_claims(token: str, cfg: VerifierConfig, *, verify_exp: bool) -> Principal:
    """Verifies a token against a provider configuration and returns the caller it names.

    Private, and the ``verify_exp`` flag never leaves this module: every relaxation is
    exposed as its own named public function, so no caller can turn expiry off by passing
    one extra argument to the function every authorization path calls. ``require`` is
    unchanged even when expiry is not enforced — a token with no ``exp`` at all is
    malformed, and accepting one would be a different relaxation than the one asked for.

    ``algorithms`` is a pinned list rather than anything read from the token: a verifier that
    trusts the header's ``alg`` accepts both an unsigned token and one signed ``HS256`` with the
    public key as the secret, and is indistinguishable from a correct one on every genuine token.

    Args:
      token: The raw JWT.
      cfg: The provider parameters to verify against.
      verify_exp: Whether to enforce the expiry claim.

    Returns:
      The verified caller.

    Raises:
      AuthError: With a fixed literal reason code, if the token is absent, fails any
        verification step, does not carry a required claim, or carries no username.
      VerifierUnavailable: If the JWKS endpoint could not be reached, so validity is unknown.
    """
    if not token:
        raise AuthError(REASON_MISSING_TOKEN)
    try:
        signing_key = clients.jwks(cfg.jwks_uri).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=cfg.audience,
            issuer=cfg.issuer,
            options={
                "require": ["exp", "iss", "aud"],
                "verify_exp": verify_exp,
                "verify_nbf": True,
            },
        )
    except PyJWKClientConnectionError as exc:
        raise VerifierUnavailable(REASON_JWKS_UNAVAILABLE) from exc
    except Exception as exc:
        raise AuthError(REASON_VERIFICATION_FAILED) from exc

    for claim, expected in cfg.required_claims.items():
        if claims.get(claim) != expected:
            raise AuthError(REASON_REQUIRED_CLAIM)
    username = claims.get(cfg.username_claim)
    if not username:
        raise AuthError(REASON_MISSING_USERNAME)
    return Principal(username=cast("str", username), claims=MappingProxyType(claims))


def verify_token(token: str, cfg: VerifierConfig) -> Principal:
    """Verifies a token in full and returns the caller it names. The provider-agnostic door.

    Expiry is always enforced, and there is no argument that turns it off — the relaxation the
    DLQ drain needs is a separate named function, so a synchronous caller cannot reach it by
    passing one extra parameter. A synchronous request is never late by construction.

    Args:
      token: The raw JWT.
      cfg: The provider parameters to verify against.

    Returns:
      The verified caller.

    Raises:
      AuthError: With a fixed literal reason code, on any verification failure.
      VerifierUnavailable: If the JWKS endpoint could not be reached.
    """
    return _verify_claims(token, cfg, verify_exp=True)


def _cognito_config() -> VerifierConfig:
    """Builds the verifier configuration for this deployment's Cognito user pool.

    Read at call time rather than at import: ``config`` resolves lazily so a function that sets
    only some of the fleet's variables can still import this module, and a constant here would
    undo that.

    Args:
      None.

    Returns:
      The Cognito parameters.

    Raises:
      RuntimeError: If a required environment variable is unset or empty.
    """
    issuer = f"https://cognito-idp.{config.REGION}.amazonaws.com/{config.USER_POOL_ID}"
    return VerifierConfig(
        issuer=issuer,
        audience=config.APP_CLIENT_ID,
        jwks_uri=f"{issuer}/.well-known/jwks.json",
        username_claim=COGNITO_USERNAME_CLAIM,
        required_claims=COGNITO_REQUIRED_CLAIMS,
    )


def _cognito_detail(exc: AuthError, missing_token_detail: str) -> str:
    """Restates a reason code as the sentence the control planes have always raised.

    The wording is load-bearing rather than cosmetic: it becomes a ``TerminalError`` detail, which
    reaches a Step Functions Cause and a per-recipient outcome array, and three suites pin it.
    Rebuilding it from ``__cause__`` is what lets ``verify_token`` raise a bare code — the two
    requirements would otherwise contradict each other.

    Args:
      exc: The ``AuthError`` carrying the reason code, and the provider exception as its cause.
      missing_token_detail: The domain's own wording for a request that carried no token.

    Returns:
      The detail sentence for that failure.

    Raises:
      None.
    """
    reason = str(exc)
    if reason == REASON_MISSING_TOKEN:
        return missing_token_detail
    if reason == REASON_REQUIRED_CLAIM:
        return "not an ID token"
    if reason == REASON_MISSING_USERNAME:
        return f"token missing {COGNITO_USERNAME_CLAIM}"
    return f"token verification failed: {exc.__cause__}"


def _verify(id_token: str, missing_token_detail: str, *, verify_exp: bool) -> dict:
    """Verifies a Cognito ID token and returns its claims, with this fleet's historical wording.

    Args:
      id_token: The raw JWT.
      missing_token_detail: Message to raise when no token was supplied.
      verify_exp: Whether to enforce the expiry claim.

    Returns:
      The decoded claims.

    Raises:
      AuthError: If the token is absent, fails any verification step, is not an ID token,
        or carries no ``cognito:username``.
      VerifierUnavailable: If the JWKS endpoint could not be reached.
    """
    try:
        principal = _verify_claims(id_token, _cognito_config(), verify_exp=verify_exp)
    except AuthError as exc:
        raise AuthError(_cognito_detail(exc, missing_token_detail)) from exc.__cause__
    return dict(principal.claims)


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
      VerifierUnavailable: If the JWKS endpoint could not be reached.
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
    on the user's behalf it needs ``verify_id_token`` or ``verified_username`` — and do not
    reach for it from a synchronous request, which is never late by construction.

    Args:
      id_token: The raw JWT.
      missing_token_detail: Message raised when no token is supplied.

    Returns:
      The verified claims.

    Raises:
      AuthError: On any verification failure other than expiry.
      VerifierUnavailable: If the JWKS endpoint could not be reached.
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
      VerifierUnavailable: If the JWKS endpoint could not be reached.
    """
    try:
        claims = verify_id_token(id_token, missing_token_detail=missing_token_detail)
        return cast("str", claims[COGNITO_USERNAME_CLAIM])
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
      VerifierUnavailable: If the JWKS endpoint could not be reached.
    """
    try:
        claims = verify_id_token_ignoring_expiry(id_token, missing_token_detail=missing_token_detail)
        return cast("str", claims[COGNITO_USERNAME_CLAIM])
    except AuthError as exc:
        raise TerminalError("unauthorized", str(exc)) from exc
