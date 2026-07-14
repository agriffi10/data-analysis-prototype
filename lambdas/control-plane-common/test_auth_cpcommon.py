"""Fixture-based tests for cpcommon.auth (SPEC-107 FR-002).

Exercises the real offline ID-token verification against a locally-generated RSA
keypair (the JWKS client is stubbed to return the public key), pinning the accept/reject
outcome for each token shape. The expected outcomes were captured from the pre-refactor
tbcommon/tscommon auth modules; this PR deletes those, so the outcomes are pinned here.

Also pins BOTH domains' "no token" detail strings — the one behavioural difference the
extraction parameterized (FR-002): "missing idToken" for table-builder,
"missing actor token" for table-share.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import jwt  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from cpcommon import auth, clients, config  # noqa: E402
from cpcommon.errors import TerminalError  # noqa: E402

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
_PUBLIC = _KEY.public_key()

ISSUER = f"https://cognito-idp.{config.REGION}.amazonaws.com/{config.USER_POOL_ID}"


class _FakeSigningKey:
    key = _PUBLIC


class _FakeJwks:
    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey()


def _install():
    clients._jwks = _FakeJwks()


def _token(**over):
    claims = {
        "cognito:username": "alice",
        "token_use": "id",
        "aud": config.APP_CLIENT_ID,
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
    }
    claims.update(over)
    return jwt.encode(claims, _PRIVATE_PEM, algorithm="RS256")


def _expect_unauthorized(token):
    _install()
    try:
        auth.verified_username(token)
    except TerminalError as exc:
        assert exc.reason == "unauthorized"
        return
    raise AssertionError("expected TerminalError('unauthorized')")


def test_valid_id_token_returns_the_username():
    _install()
    assert auth.verified_username(_token()) == "alice"


def test_expired_token_is_unauthorized():
    _expect_unauthorized(_token(exp=int(time.time()) - 60))


def test_wrong_audience_is_unauthorized():
    _expect_unauthorized(_token(aud="some-other-client"))


def test_wrong_issuer_is_unauthorized():
    _expect_unauthorized(_token(iss="https://evil.example.com/pool"))


def test_access_token_not_id_token_is_unauthorized():
    _expect_unauthorized(_token(token_use="access"))


def test_missing_cognito_username_is_unauthorized():
    _install()
    tok = _token()
    del_claims = jwt.decode(tok, _PUBLIC, algorithms=["RS256"], audience=config.APP_CLIENT_ID, issuer=ISSUER)
    del_claims.pop("cognito:username")
    tok2 = jwt.encode(del_claims, _PRIVATE_PEM, algorithm="RS256")
    _expect_unauthorized(tok2)


def test_malformed_token_is_unauthorized():
    _expect_unauthorized("not-a-jwt")


def test_missing_token_detail_defaults_to_table_builder_wording():
    _install()
    try:
        auth.verified_username("")
    except TerminalError as exc:
        assert exc.reason == "unauthorized"
        assert exc.detail == "missing idToken"
        return
    raise AssertionError("expected TerminalError")


def test_missing_token_detail_is_parameterized_for_table_share():
    _install()
    try:
        auth.verified_username("", missing_token_detail="missing actor token")
    except TerminalError as exc:
        assert exc.reason == "unauthorized"
        assert exc.detail == "missing actor token"
        return
    raise AssertionError("expected TerminalError")


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
