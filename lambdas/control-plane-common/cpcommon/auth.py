"""Token verification — the API's one security boundary, and the repo's only one.

One JWKS-verification path for the whole repo. It used to be three, each with its own copy of
the claim checks, so a fix to any of them had to be made in every one and would eventually have
been made in one. ``notifications-writer`` was a fourth, and not by oversight — this module
reaches ``config``, which required six environment variables at import, and that function sets
three of them; the blocker was the cause of the duplication, and removing it (``config`` resolves
on first access) removed the copy.

**The checks are now driven by a ``VerifierConfig`` rather than by a Cognito-shaped constant**,
because the target environment may issue tokens from a provider that is not Cognito at all — and
if it does, swapping providers must be a configuration change rather than a rewrite of every
authorization path in the product. Issuer, audience, JWKS URI, the username claim and the
required-claims map are all parameters. Nothing below names a provider; the Cognito values live
in ``_cognito_config`` alone, which is what the existing entry points pass.

**There is one caller left, and it is the API.** The layering above ``verify_token`` existed so
each control plane could restate a verification failure in the wording it had always raised;
the planes stopped verifying when the API became the only principal that may write their queues,
and every entry point that served them — the Cognito configuration, the two ``*_ignoring_expiry``
relaxations, the hard-coded username-claim name — went with them. What is left is the seam and
nothing else, which is why this module now names no provider at all: the claim to read is a
field on ``VerifierConfig``, and a sweep fails if any shipped module writes a provider's own
claim name as a literal again.

**A reason code is not a message.** ``verify_token`` raises a fixed literal, never an
interpolated provider string, and chains the provider exception as ``__cause__``. An
internet-facing caller reads the code and never touches the cause; the control planes rebuild
their historical wording from the cause, whose exposure is a queue body that is already redacted.
That split is what lets the API refuse to leak a provider message while the planes keep
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
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

import jwt
from jwt.exceptions import PyJWKClientConnectionError

from . import clients
from .errors import AuthError

REASON_MISSING_TOKEN = "missing_token"
REASON_VERIFICATION_FAILED = "verification_failed"
REASON_REQUIRED_CLAIM = "required_claim_mismatch"
REASON_MISSING_USERNAME = "missing_username_claim"
REASON_JWKS_UNAVAILABLE = "jwks_unavailable"

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


def _verify_claims(token: str, cfg: VerifierConfig) -> Principal:
    """Verifies a token against a provider configuration and returns the caller it names.

    Private, and expiry is now UNCONDITIONAL: there is no parameter that turns it off, because
    there is no caller that wants one. The relaxation used to exist for the dead-letter drain and
    the timeout doors, which read an actor out of a message that was old by construction — none
    of them reads a token any more, so the flag went with the functions that exposed it. A
    verifier with no way to skip expiry is one no future caller can talk into skipping it.

    ``algorithms`` is a pinned list rather than anything read from the token: a verifier that
    trusts the header's ``alg`` accepts both an unsigned token and one signed ``HS256`` with the
    public key as the secret, and is indistinguishable from a correct one on every genuine token.

    Args:
      token: The raw JWT.
      cfg: The provider parameters to verify against.

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
                "verify_exp": True,
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

    Expiry is always enforced, and nothing anywhere can turn it off. There is no longer even a
    private flag: the one caller that wanted a relaxation read tokens out of dead-lettered
    messages, and no message carries a token now.

    Args:
      token: The raw JWT.
      cfg: The provider parameters to verify against.

    Returns:
      The verified caller.

    Raises:
      AuthError: With a fixed literal reason code, on any verification failure.
      VerifierUnavailable: If the JWKS endpoint could not be reached.
    """
    return _verify_claims(token, cfg)
