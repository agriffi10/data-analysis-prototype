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


@pytest.fixture(autouse=True)
def _identity_environment(monkeypatch):
    """The identity layer's three required values, and an empty credential cache.

    The cache survives an invocation by design, so it survives a TEST by design too — and a leak
    between tests would mask exactly the leak between requests the sequence tests exist to catch.
    """
    monkeypatch.setenv("PORTAL_ROLE_ARN", "arn:aws:iam::696000197480:role/dat-portal-user-role")
    monkeypatch.setenv("PRINCIPAL_TAG_KEY", "username")
    monkeypatch.setenv("MAX_SHARED_MEMBERSHIPS", "10")

    from apicommon import identity

    identity.reset_credential_cache()
    yield
    identity.reset_credential_cache()


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


# ── The seam for a route a test invents ───────────────────────────────────────
# A route is declared in the contract and served from the router's handler map, so registering
# one by hand means touching both — and ten test sites each inventing their own way to do that is
# ten chances to leave one half behind. This is the one way.

import contextlib


@contextlib.contextmanager
def declare_route(route, handler):
    """Declares one route and its handler for the duration of a block.

    Replaces the contract's route tuple rather than mutating it: the table is frozen, and the
    router resolves from it on every call, so a replacement is visible immediately and cannot be
    shadowed by an index built at import.

    Args:
      route: The ``contract.Route`` to declare.
      handler: The function serving it.

    Yields:
      The route, so a caller can name its id without restating it.

    Raises:
      None.
    """
    import router as router_module
    from apicommon import contract

    original_routes = contract.ROUTES
    original_handlers = dict(router_module.HANDLERS)
    contract.ROUTES = (*contract.ROUTES, route)
    router_module.HANDLERS[route.id] = handler
    try:
        yield route
    finally:
        contract.ROUTES = original_routes
        router_module.HANDLERS.clear()
        router_module.HANDLERS.update(original_handlers)


def directory_document(usernames=("alice", "bob_smith"), version=1, generated_at="2026-08-05T04:00:11Z"):
    """The stored directory document, as bytes.

    Args:
      usernames: The names the document carries.
      version: The document version.
      generated_at: The publication timestamp, or None to omit it.

    Returns:
      The document, JSON-encoded.

    Raises:
      None.
    """
    import json as _json

    document = {"version": version, "count": len(usernames), "usernames": list(usernames)}
    if generated_at is not None:
        document["generatedAt"] = generated_at
    return _json.dumps(document).encode()


class _StubBody:
    """The streaming body ``get_object`` returns."""

    def __init__(self, payload):
        """Holds the payload.

        Args:
          payload: The bytes to serve.

        Returns:
          None.

        Raises:
          None.
        """
        self._payload = payload

    def read(self):
        """Returns the payload.

        Args:
          None.

        Returns:
          The bytes.

        Raises:
          None.
        """
        return self._payload


class StubS3:
    """A user-plane S3 client serving one object, or raising one error.

    Attributes:
      calls: Every ``get_object`` keyword set it received, so a test can assert what was asked
        for and how often — which is the only way to tell a route that skipped AWS from one that
        reached it.
    """

    def __init__(self, payload=None, error=None):
        """Builds the stub.

        Args:
          payload: The bytes ``get_object`` returns.
          error: An exception ``get_object`` raises instead.

        Returns:
          None.

        Raises:
          None.
        """
        self._payload = payload
        self._error = error
        self.calls = []

    def get_object(self, **kwargs):
        """Serves the object, or raises.

        Args:
          **kwargs: The call's arguments, recorded.

        Returns:
          A response carrying the stub body.

        Raises:
          Exception: Whatever the stub was built with.
        """
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"Body": _StubBody(self._payload)}


@pytest.fixture
def stub_directory(monkeypatch):
    """Points the user plane at a stubbed S3 serving the directory document.

    Not autouse: a test about the identity layer itself wants the real door, and stubbing it
    everywhere would quietly remove the thing several suites exist to exercise.

    Args:
      monkeypatch: Pytest's patcher.

    Yields:
      A function taking the stub to install and returning it.

    Raises:
      None.
    """
    from apicommon import identity

    installed = {}

    def _install(stub):
        """Installs one stub as the user plane's client.

        Args:
          stub: The client to serve.

        Returns:
          The stub, for the caller to assert against.

        Raises:
          None.
        """
        installed["client"] = stub
        monkeypatch.setattr(identity, "user_client", lambda service, acting_as: stub)
        return stub

    _install(StubS3(payload=directory_document()))
    yield _install
