"""SPEC-125 FR-003: the shared-space auth adapter over `cpcommon.auth.verify_id_token`.

Nothing pinned these message strings before this spec — `verified_username` had no test at
all, so folding it onto `cpcommon` could have silently reworded every failure an operator
reads and CI would have stayed green. That is the risk the whole file exists to remove; the
exception TYPE matters to the Step Function's Catch, and the TEXT matters to whoever is
reading the execution afterwards.

Exercises the real verification against a locally-generated RSA keypair (JWKS client
stubbed), not a patched `verified_username` — a mock here would pin nothing.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import auth
import jwt
from cpcommon import clients, config
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)

ISSUER = f"https://cognito-idp.{config.REGION}.amazonaws.com/{config.USER_POOL_ID}"


class _FakeSigningKey:
    key = _KEY.public_key()


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


def _message_for(token):
    _install()
    try:
        auth.verified_username(token)
    except auth.AuthorizationError as exc:
        return str(exc)
    raise AssertionError("expected AuthorizationError")


def test_a_valid_token_returns_the_trusted_username():
    _install()
    assert auth.verified_username(_token()) == "alice"


def test_the_message_strings_are_exactly_what_this_control_plane_raised_before():
    assert _message_for("") == "missing idToken"
    assert _message_for(_token(token_use="access")) == "not an ID token"
    # The verification-failure message wraps the underlying reason; the prefix is the pinned
    # part, since the PyJWT detail after it is not ours to promise.
    assert _message_for("not-a-jwt").startswith("token verification failed: ")


def test_a_missing_cognito_username_claim_is_rejected_by_its_own_message():
    tok = jwt.encode(
        {"token_use": "id", "aud": config.APP_CLIENT_ID, "iss": ISSUER, "exp": int(time.time()) + 3600},
        _PRIVATE_PEM,
        algorithm="RS256",
    )
    assert _message_for(tok) == "token missing cognito:username"


def test_expired_wrong_audience_and_wrong_issuer_all_fail_as_verification_failures():
    for token in (
        _token(exp=int(time.time()) - 60),
        _token(aud="some-other-client"),
        _token(iss="https://evil.example.com/pool"),
    ):
        assert _message_for(token).startswith("token verification failed: ")


def test_the_exception_type_is_the_domain_one_the_step_function_catches():
    # NOT cpcommon's AuthError and NOT TerminalError: the shared-space Standard Step
    # Function Catches AuthorizationError by name, and it has no transient-retry concept.
    _install()
    try:
        auth.verified_username("")
    except auth.AuthorizationError:
        pass
    else:
        raise AssertionError("expected AuthorizationError")


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
