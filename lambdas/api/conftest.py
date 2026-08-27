"""Puts this function's own directory on ``sys.path`` so ``handler`` can import ``router``.

The deploy script copies every ``.py`` in the function directory flat into the package root, so
``from router import route`` resolves at runtime without help. Under pytest the function directory
is not on the path — ``lambdas/conftest.py`` adds the shared LAYER roots and deliberately nothing
else — so the import that works in Lambda fails in the suite.

Placed here rather than widening the shared conftest: that file's scope is the layers, and putting
every verb directory on one path would let two functions' modules shadow each other.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# ── Real tokens, one faked boundary ───────────────────────────────────────────
# The suite verifies genuine RS256 tokens through the real verifier; the only thing stubbed is
# the JWKS endpoint, which is the service boundary. Stubbing `principal.resolve` instead would
# be quicker and would make every test below pass against a router that never verifies
# anything — which is the one property this whole package exists to have.

import time

import jwt
import pytest
from cpcommon import clients
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_testpool"
AUDIENCE = "test-app-client"
USERNAME_CLAIM = "cognito:username"


class _SigningKey:
    key = _KEY.public_key()


class _Jwks:
    """A JWKS endpoint that always holds the one key this suite signs with."""

    def get_signing_key_from_jwt(self, token):
        return _SigningKey()


@pytest.fixture(autouse=True)
def _offline_jwks():
    """Point the verifier at an in-memory key set for every test in this package."""
    clients.jwks = lambda url: _Jwks()


def token(username="alice", **over):
    """Mints a genuine ID token for the configured provider.

    Args:
      username: The username claim to carry.
      **over: Claims to add or replace. Passing ``None`` removes a claim.

    Returns:
      The encoded JWT.
    """
    claims = {
        USERNAME_CLAIM: username,
        "token_use": "id",
        "aud": AUDIENCE,
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
    }
    claims.update(over)
    return jwt.encode(
        {name: value for name, value in claims.items() if value is not None},
        _PRIVATE_PEM,
        algorithm="RS256",
    )


def bearer(username="alice", **over):
    """The headers an authenticated request carries."""
    return {"authorization": f"Bearer {token(username, **over)}"}
