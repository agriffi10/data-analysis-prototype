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

import jwt
from cpcommon import auth, clients, config
from cpcommon.errors import TerminalError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

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
    # Stub the ACCESSOR, not the cache: `_jwks` is a per-URL dict now
    # (SPEC-151 FR-009), and what these tests actually want to fake is the client.
    clients.jwks = lambda url: _FakeJwks()


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


# ── verified_username_ignoring_expiry (SPEC-126 FR-002) ──────────────────────
# The DLQ drain's relaxation. Only `exp` is unenforced; every other check must still hold,
# and the ENFORCING entry point must be unchanged — which is the pairing these tests exist
# to hold in place.


def _expect_unauthorized_ignoring_expiry(token):
    _install()
    try:
        auth.verified_username_ignoring_expiry(token)
    except TerminalError as exc:
        assert exc.reason == "unauthorized"
        return
    raise AssertionError("expected TerminalError('unauthorized')")


def test_expired_but_validly_signed_token_still_names_its_subject():
    # A dead-lettered message is OLD BY CONSTRUCTION (three failed receives, then a wait in
    # a 14-day queue) while an ID token lives an hour, so enforcing exp here would drop
    # exactly the late failures SPEC-126 exists to surface.
    _install()
    assert auth.verified_username_ignoring_expiry(_token(exp=int(time.time()) - 86400)) == "alice"


def test_ignoring_expiry_still_rejects_a_bad_signature():
    # The relaxation is exp AND NOTHING ELSE: a token this pool didn't sign proves nothing.
    _install()
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {
            "cognito:username": "mallory",
            "token_use": "id",
            "aud": config.APP_CLIENT_ID,
            "iss": ISSUER,
            "exp": int(time.time()) + 3600,
        },
        other.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        algorithm="RS256",
    )
    _expect_unauthorized_ignoring_expiry(forged)


def test_ignoring_expiry_still_rejects_wrong_audience_issuer_and_non_id_tokens():
    _expect_unauthorized_ignoring_expiry(_token(aud="some-other-client"))
    _expect_unauthorized_ignoring_expiry(_token(iss="https://evil.example.com/pool"))
    _expect_unauthorized_ignoring_expiry(_token(token_use="access"))


def test_ignoring_expiry_still_requires_an_exp_claim_to_be_present():
    # Not enforcing `exp` is not the same as accepting a token that has none — that would be
    # a second, unasked-for relaxation.
    _install()
    claims = {
        "cognito:username": "alice",
        "token_use": "id",
        "aud": config.APP_CLIENT_ID,
        "iss": ISSUER,
    }
    _expect_unauthorized_ignoring_expiry(jwt.encode(claims, _PRIVATE_PEM, algorithm="RS256"))


def test_the_enforcing_entry_point_still_enforces_expiry():
    # The whole risk of adding a relaxed path is that it leaks into the enforcing one.
    _expect_unauthorized(_token(exp=int(time.time()) - 60))


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


# ── SPEC-151 FR-009: the JWKS cache is keyed by URL ─────────────────────────


def test_jwks_caches_one_client_per_url():
    """It used to cache the FIRST client and ignore the argument thereafter, so a second
    pool's URL was served the first pool's client — verifying tokens against the wrong
    JWKS. Latent with one pool; exactly the shape that would present as an inexplicable
    signature failure during the Identity Center transition."""
    clients._jwks = {}
    made = []

    class _Client:
        def __init__(self, url):
            made.append(url)
            self.url = url

    import sys
    import types as _types

    stub = _types.ModuleType("jwt")
    stub.PyJWKClient = _Client
    saved = sys.modules.get("jwt")
    sys.modules["jwt"] = stub
    try:
        a1 = clients.jwks("https://pool-a/.well-known/jwks.json")
        b1 = clients.jwks("https://pool-b/.well-known/jwks.json")
        a2 = clients.jwks("https://pool-a/.well-known/jwks.json")
    finally:
        if saved is not None:
            sys.modules["jwt"] = saved
        else:
            del sys.modules["jwt"]
        clients._jwks = {}

    assert a1.url == "https://pool-a/.well-known/jwks.json"
    assert b1.url == "https://pool-b/.well-known/jwks.json"
    assert a1 is a2  # still cached per URL — the single-pool case is unchanged
    assert made == [
        "https://pool-a/.well-known/jwks.json",
        "https://pool-b/.well-known/jwks.json",
    ]
