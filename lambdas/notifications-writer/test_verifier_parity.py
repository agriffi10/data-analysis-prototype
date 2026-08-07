"""SPEC-156 FR-004: the adopted verification path, pinned at this function's seam.

**This started as a parity test and was reduced.** Before ``notifications_writer``'s local
JWKS verifier was deleted, the same nine token shapes were run through BOTH it and
``cpcommon.auth`` and asserted to produce an identical ``(outcome, message)`` pair — valid,
expired, wrong audience, wrong issuer, access token, missing username, foreign signature,
malformed and empty. All nine agreed. What survives here is the shared path plus the one
thing that could not match and had to be mapped: the exception type.

That mapping is the whole risk of the adoption. ``cpcommon.auth`` raises ``AuthError``; this
handler's SQS contract — raise, retry, dead-letter, never a partial write — is expressed in
``AuthorizationError``, and a rejection that escaped as ``AuthError`` would still fail the
invocation but would no longer be the failure this module documents.
"""

import os
import pathlib
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

import jwt
import notifications_writer as w
import pytest
from cpcommon import clients, config
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_PEM = _OTHER.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)

ISSUER = f"https://cognito-idp.{config.REGION}.amazonaws.com/{config.USER_POOL_ID}"


class _FakeJwks:
    def get_signing_key_from_jwt(self, token):
        return type("_K", (), {"key": _KEY.public_key()})()


def _install():
    clients.jwks = lambda url: _FakeJwks()


def _token(pem=_PRIVATE_PEM, **over):
    claims = {
        "cognito:username": "alice",
        "token_use": "id",
        "aud": config.APP_CLIENT_ID,
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
    }
    claims.update(over)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, pem, algorithm="RS256")


REJECTED = {
    "expired": lambda: _token(exp=int(time.time()) - 60),
    "wrong-audience": lambda: _token(aud="some-other-client"),
    "wrong-issuer": lambda: _token(iss="https://evil.example.com/pool"),
    "access-token": lambda: _token(token_use="access"),
    "no-username": lambda: _token(**{"cognito:username": None}),
    "foreign-signature": lambda: _token(pem=_OTHER_PEM),
    "malformed": lambda: "not-a-jwt",
    "empty": lambda: "",
}


def test_a_valid_token_yields_its_username():
    _install()
    assert w.verified_username(_token()) == "alice"


@pytest.mark.parametrize("case", sorted(REJECTED))
def test_every_rejection_reaches_the_caller_as_an_authorization_error(case):
    _install()
    with pytest.raises(w.AuthorizationError):
        w.verified_username(REJECTED[case]())


def test_the_rejection_wording_is_the_layer_s_own():
    """Unchanged from the deleted local verifier, which is what the parity run established."""
    _install()
    with pytest.raises(w.AuthorizationError, match="missing idToken"):
        w.verified_username("")
    with pytest.raises(w.AuthorizationError, match="not an ID token"):
        w.verified_username(_token(token_use="access"))
    with pytest.raises(w.AuthorizationError, match="token verification failed"):
        w.verified_username("not-a-jwt")


def test_the_local_verifier_is_gone():
    """The duplication this FR removed must not grow back by a copy-paste.

    ``cpcommon/auth.py`` claims to be the fleet's one verification path; for nine months it
    was not, and this function was the second one.
    """
    source = pathlib.Path(__file__).with_name("notifications_writer.py").read_text()
    for gone in ("PyJWKClient", "jwt.decode", "_JWKS_URL", "_ISSUER", 'boto3.client("s3")'):
        assert gone not in source, f"{gone} is back in notifications_writer.py"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
