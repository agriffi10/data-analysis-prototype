"""Fixture-based tests for cpcommon.auth (SPEC-107 FR-002).

Exercises the real offline ID-token verification against a locally-generated RSA
keypair (the JWKS client is stubbed to return the public key), pinning the accept/reject
outcome for each token shape. The expected outcomes were captured from the pre-refactor
tbcommon/tscommon auth modules; this PR deletes those, so the outcomes are pinned here.

Also pins BOTH domains' "no token" detail strings — the one behavioural difference the
extraction parameterized (FR-002): "missing idToken" for table-builder,
"missing actor token" for table-share.
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import jwt
import pytest
from cpcommon import auth, clients, config
from cpcommon import jwks as cpcommon_jwks
from cpcommon.errors import AuthError, TerminalError
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

    # Patch the SEAM, not `sys.modules["jwt"]`. The factory builds a CooldownJWKClient now, so
    # a stub module exposing only PyJWKClient no longer satisfies the import — and stubbing the
    # class the factory actually names says what this test means without standing in for a
    # third-party package.
    saved = cpcommon_jwks.CooldownJWKClient
    cpcommon_jwks.CooldownJWKClient = _Client
    try:
        a1 = clients.jwks("https://pool-a/.well-known/jwks.json")
        b1 = clients.jwks("https://pool-b/.well-known/jwks.json")
        a2 = clients.jwks("https://pool-a/.well-known/jwks.json")
    finally:
        cpcommon_jwks.CooldownJWKClient = saved
        clients._jwks = {}

    assert a1.url == "https://pool-a/.well-known/jwks.json"
    assert b1.url == "https://pool-b/.well-known/jwks.json"
    assert a1 is a2  # still cached per URL — the single-pool case is unchanged
    assert made == [
        "https://pool-a/.well-known/jwks.json",
        "https://pool-b/.well-known/jwks.json",
    ]


# ── The parity run ────────────────────────────────────────────────────────────
# Forty cells: four entry points by ten token shapes, each pinning the exception TYPE and the
# exact text. The expectations were MEASURED against the pre-parameterisation module and are
# reproduced here verbatim; argued equivalence is not accepted, and the deduplication this
# repeats found a divergent row when it was run rather than reasoned about.
#
# The two *_ignoring_expiry columns are not decoration. They are the entry points that stopped
# routing through the shared public function when the verifier was parameterised — the public
# one cannot be told to skip expiry, deliberately — so they are exactly where a divergence
# would live. Their `expired` row PASSES, which is the assertion that proves the relaxation
# survived the refactor.
#
# THE UNKNOWN-KID FAKE IS KID-AWARE, and that is load-bearing. Every other JWKS fake in this
# repo returns the same key whatever the header says, under which an unknown-kid token verifies
# successfully — so that row, the only one exercising the code the cooldown client changed,
# would be pinned as "valid" and could never fail.

_UNKNOWN_KID = "rotated-away"


class _KidAwareJwks:
    """A JWKS fake that refuses a kid it does not hold, worded as PyJWT words it."""

    def get_signing_key_from_jwt(self, token):
        kid = jwt.get_unverified_header(token).get("kid")
        if kid not in (None, "known"):
            from jwt.exceptions import PyJWKClientError

            raise PyJWKClientError(f'Unable to find a signing key that matches: "{kid}"')
        return _FakeSigningKey()


def _install_kid_aware():
    clients.jwks = lambda url: _KidAwareJwks()


def _shapes():
    """The ten token shapes, built fresh so no expiry drifts across a slow run."""
    return {
        "valid": _token(),
        "expired": _token(exp=int(time.time()) - 60),
        "wrong_audience": _token(aud="some-other-client"),
        "wrong_issuer": _token(iss="https://evil.example.com/pool"),
        "bad_signature": jwt.encode(
            {
                "cognito:username": "alice",
                "token_use": "id",
                "aud": config.APP_CLIENT_ID,
                "iss": ISSUER,
                "exp": int(time.time()) + 3600,
            },
            _OTHER_PRIVATE_PEM,
            algorithm="RS256",
        ),
        "unknown_kid": jwt.encode(
            {
                "cognito:username": "alice",
                "token_use": "id",
                "aud": config.APP_CLIENT_ID,
                "iss": ISSUER,
                "exp": int(time.time()) + 3600,
            },
            _PRIVATE_PEM,
            algorithm="RS256",
            headers={"kid": _UNKNOWN_KID},
        ),
        "access_token": _token(token_use="access"),
        "missing_username": _token_without("cognito:username"),
        "not_a_jwt": "not-a-jwt",
        "empty": "",
    }


_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_PRIVATE_PEM = _OTHER_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)


def _token_without(claim):
    """Mints a token carrying every default claim but one."""
    claims = {
        "cognito:username": "alice",
        "token_use": "id",
        "aud": config.APP_CLIENT_ID,
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
    }
    claims.pop(claim)
    return jwt.encode(claims, _PRIVATE_PEM, algorithm="RS256")


#: shape -> (verify_id_token, verify_id_token_ignoring_expiry, verified_username,
#:           verified_username_ignoring_expiry). "OK" means it returned; "A:" an AuthError with
#: that exact str(); "T:" a TerminalError("unauthorized") with that exact detail.
PARITY = {
    "valid": ("OK", "OK", "OK", "OK"),
    "expired": (
        "A:token verification failed: Signature has expired",
        "OK",
        "T:token verification failed: Signature has expired",
        "OK",
    ),
    "wrong_audience": (
        "A:token verification failed: Audience doesn't match",
        "A:token verification failed: Audience doesn't match",
        "T:token verification failed: Audience doesn't match",
        "T:token verification failed: Audience doesn't match",
    ),
    "wrong_issuer": (
        "A:token verification failed: Invalid issuer",
        "A:token verification failed: Invalid issuer",
        "T:token verification failed: Invalid issuer",
        "T:token verification failed: Invalid issuer",
    ),
    "bad_signature": (
        "A:token verification failed: Signature verification failed",
        "A:token verification failed: Signature verification failed",
        "T:token verification failed: Signature verification failed",
        "T:token verification failed: Signature verification failed",
    ),
    "unknown_kid": (
        'A:token verification failed: Unable to find a signing key that matches: "rotated-away"',
        'A:token verification failed: Unable to find a signing key that matches: "rotated-away"',
        'T:token verification failed: Unable to find a signing key that matches: "rotated-away"',
        'T:token verification failed: Unable to find a signing key that matches: "rotated-away"',
    ),
    "access_token": (
        "A:not an ID token",
        "A:not an ID token",
        "T:not an ID token",
        "T:not an ID token",
    ),
    "missing_username": (
        "A:token missing cognito:username",
        "A:token missing cognito:username",
        "T:token missing cognito:username",
        "T:token missing cognito:username",
    ),
    "not_a_jwt": (
        "A:token verification failed: Not enough segments",
        "A:token verification failed: Not enough segments",
        "T:token verification failed: Not enough segments",
        "T:token verification failed: Not enough segments",
    ),
    "empty": (
        "A:missing idToken",
        "A:missing idToken",
        "T:missing idToken",
        "T:missing idToken",
    ),
}

_ENTRY_POINTS = (
    ("verify_id_token", lambda t: auth.verify_id_token(t)),
    ("verify_id_token_ignoring_expiry", lambda t: auth.verify_id_token_ignoring_expiry(t)),
    ("verified_username", lambda t: auth.verified_username(t)),
    ("verified_username_ignoring_expiry", lambda t: auth.verified_username_ignoring_expiry(t)),
)


def _observe(fn, token):
    """Runs one entry point and renders its outcome in the table's notation."""
    try:
        fn(token)
    except TerminalError as exc:
        assert exc.reason == "unauthorized"
        return f"T:{exc.detail}"
    except AuthError as exc:
        return f"A:{exc}"
    return "OK"


@pytest.mark.parametrize("shape", sorted(PARITY))
def test_the_four_entry_points_are_behaviourally_unchanged(shape):
    _install_kid_aware()
    token = _shapes()[shape]
    observed = tuple(_observe(fn, token) for _, fn in _ENTRY_POINTS)
    assert observed == PARITY[shape], (
        f"{shape}: the entry points diverged from the measured pre-parameterisation behaviour"
    )


def test_the_parity_table_covers_every_entry_point_and_shape():
    """Guard-the-guard: a table that lost a column or a row would pass every row it kept."""
    assert len(PARITY) == 10
    assert set(PARITY) == set(_shapes())
    assert all(len(row) == len(_ENTRY_POINTS) for row in PARITY.values())
    assert PARITY["expired"][1] == "OK" and PARITY["expired"][3] == "OK", (
        "the ignoring-expiry columns must PASS an expired token — that is what proves the "
        "relaxation survived, and pinning them as failures would hide its loss"
    )


# ── The checks, driven to failure one at a time ───────────────────────────────
# A verifier that applies them as a block cannot show which one it is actually applying, and a
# genuine token passes every one of them — so an implementation that skips a check works
# perfectly for every real user and is invisible until someone forges the claim it skipped.

_PUBLIC_PEM = _PUBLIC.public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
)

def _b64(obj):
    """Base64url-encodes a JWT segment, unpadded, the way a forger would."""
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


GENERIC_ISSUER = "https://provider.example/tenant"
GENERIC_AUDIENCE = "some-relying-party"


def _generic_cfg(required_claims=None):
    """A configuration that names no provider — the shape the target environment swaps into."""
    return auth.VerifierConfig(
        issuer=GENERIC_ISSUER,
        audience=GENERIC_AUDIENCE,
        jwks_uri="https://provider.example/keys",
        username_claim="preferred_username",
        required_claims={"token_use": "id"} if required_claims is None else required_claims,
    )


def _generic_token(key=None, algorithm="RS256", headers=None, **over):
    """Mints a token for the generic configuration."""
    claims = {
        "preferred_username": "alice",
        "token_use": "id",
        "aud": GENERIC_AUDIENCE,
        "iss": GENERIC_ISSUER,
        "exp": int(time.time()) + 3600,
    }
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key or _PRIVATE_PEM, algorithm=algorithm, headers=headers)


def _refused(token, cfg=None):
    """Asserts verify_token refuses, and returns the reason code it refused with."""
    _install()
    with pytest.raises(AuthError) as raised:
        auth.verify_token(token, cfg or _generic_cfg())
    return str(raised.value)


def test_the_generic_configuration_accepts_a_good_token():
    """The control: every drive below must differ from this by exactly one thing."""
    _install()
    principal = auth.verify_token(_generic_token(), _generic_cfg())
    assert principal.username == "alice"
    assert principal.claims["iss"] == GENERIC_ISSUER


@pytest.mark.parametrize("claim", ["exp", "iss", "aud"])
def test_each_required_claim_is_enforced_on_its_own(claim):
    assert _refused(_generic_token(**{claim: None})) == auth.REASON_VERIFICATION_FAILED


def test_expiry_is_enforced():
    assert _refused(_generic_token(exp=int(time.time()) - 60)) == auth.REASON_VERIFICATION_FAILED


def test_not_before_is_enforced():
    """PyJWT defaults this on, so the option is stated rather than inherited — and a default
    that is relied on silently is a default that can change under you."""
    assert _refused(_generic_token(nbf=int(time.time()) + 3600)) == auth.REASON_VERIFICATION_FAILED


def test_the_issuer_is_enforced():
    assert _refused(_generic_token(iss="https://elsewhere.example")) == auth.REASON_VERIFICATION_FAILED


def test_the_audience_is_enforced():
    assert _refused(_generic_token(aud="another-party")) == auth.REASON_VERIFICATION_FAILED


def test_the_signature_is_enforced():
    assert _refused(_generic_token(key=_OTHER_PRIVATE_PEM)) == auth.REASON_VERIFICATION_FAILED


def test_each_configured_required_claim_is_enforced_on_its_own():
    cfg = _generic_cfg({"token_use": "id", "scope": "portal"})
    assert _refused(_generic_token(token_use="access", scope="portal"), cfg) == auth.REASON_REQUIRED_CLAIM
    assert _refused(_generic_token(scope="other"), cfg) == auth.REASON_REQUIRED_CLAIM
    _install()
    assert auth.verify_token(_generic_token(scope="portal"), cfg).username == "alice"


def test_an_empty_required_claims_map_enforces_nothing_extra():
    """It may be empty — a provider that asserts no such claim is not thereby refused."""
    _install()
    token = _generic_token(token_use="whatever")
    assert auth.verify_token(token, _generic_cfg({})).username == "alice"


def test_the_configured_username_claim_must_be_present_and_non_empty():
    assert _refused(_generic_token(preferred_username=None)) == auth.REASON_MISSING_USERNAME
    assert _refused(_generic_token(preferred_username="")) == auth.REASON_MISSING_USERNAME


def test_an_absent_token_is_refused_before_anything_else():
    assert _refused("") == auth.REASON_MISSING_TOKEN


# ── Algorithm confusion ───────────────────────────────────────────────────────
# THE TWO FORGERY TESTS BELOW DO NOT MEASURE OUR PIN, and saying so is the point. Both were
# written as though they did, and widening `algorithms` to ["RS256", "HS256", "none"] left both
# GREEN: PyJWT refuses an unsigned token whenever a key is supplied, and refuses a PEM as an
# HMAC secret, on its own and whatever the caller's algorithm list says. They are worth keeping
# as outcome tests — the forgery must fail, and it does — but the assertion that reddens when
# THIS repo widens its own list is the argument spy below it. Measured, not assumed.


def test_an_unsigned_token_is_refused():
    header = _b64({"alg": "none", "typ": "JWT"})
    payload = _b64(
        {
            "preferred_username": "alice",
            "token_use": "id",
            "aud": GENERIC_AUDIENCE,
            "iss": GENERIC_ISSUER,
            "exp": int(time.time()) + 3600,
        }
    )
    assert _refused(f"{header}.{payload}.") == auth.REASON_VERIFICATION_FAILED


def test_a_token_symmetrically_signed_with_the_public_key_is_refused():
    """The classic forgery: the public key is public, so if HS256 is honoured anyone holding it
    can mint a token the verifier treats as signed by the provider."""
    # Assembled by hand rather than with `jwt.encode`, which refuses a PEM as an HMAC secret.
    # That refusal protects whoever is SIGNING; it is no help at all to whoever is verifying,
    # and an attacker is not using this library. Constructing it the way an attacker would is
    # the only way this assertion means anything.
    header = _b64({"alg": "HS256", "typ": "JWT"})
    payload = _b64(
        {
            "preferred_username": "alice",
            "token_use": "id",
            "aud": GENERIC_AUDIENCE,
            "iss": GENERIC_ISSUER,
            "exp": int(time.time()) + 3600,
        }
    )
    signing_input = f"{header}.{payload}".encode()
    signature = base64.urlsafe_b64encode(
        hmac.new(_PUBLIC_PEM, signing_input, hashlib.sha256).digest()
    ).rstrip(b"=")
    forged = f"{header}.{payload}.{signature.decode()}"
    assert _refused(forged) == auth.REASON_VERIFICATION_FAILED


# ── The reason code is not a message ──────────────────────────────────────────


def test_verify_token_raises_authorization_errors_and_never_a_control_plane_terminal():
    """That mapping is a control-plane concern; an API maps to HTTP instead."""
    _install()
    with pytest.raises(AuthError) as raised:
        auth.verify_token(_generic_token(aud="another-party"), _generic_cfg())
    assert not isinstance(raised.value, TerminalError)


def test_verify_tokens_own_text_carries_no_provider_message_and_no_token():
    """What an internet-facing caller may read. The provider's own words go on __cause__, which
    the control planes rebuild their wording from and an API never touches."""
    _install()
    token = _generic_token(iss="https://elsewhere.example")
    with pytest.raises(AuthError) as raised:
        auth.verify_token(token, _generic_cfg())

    text = str(raised.value)
    assert text == auth.REASON_VERIFICATION_FAILED
    assert "Invalid issuer" not in text
    assert "elsewhere.example" not in text
    for segment in token.split("."):
        assert segment not in text
    # Chained, not swallowed: both halves have to be true at once or the control planes lose
    # the sentence three suites pin.
    assert raised.value.__cause__ is not None
    assert "Invalid issuer" in str(raised.value.__cause__)


def test_the_algorithm_list_passed_to_the_decoder_is_exactly_rs256():
    """The assertion the two forgery tests above cannot make.

    Widening the list is invisible to them, because PyJWT independently refuses both forgeries
    whatever it is told to allow. What is left unguarded that way is the list itself — so this
    reads the argument the verifier actually passes.
    """
    _install()
    seen = {}
    real_decode = jwt.decode

    def spy(token, key, **kwargs):
        seen.update(kwargs)
        return real_decode(token, key, **kwargs)

    jwt.decode = spy
    try:
        auth.verify_token(_generic_token(), _generic_cfg())
    finally:
        jwt.decode = real_decode

    assert seen["algorithms"] == ["RS256"], (
        f"the verifier allowed {seen['algorithms']} — an asymmetric verifier that also accepts "
        "a symmetric algorithm can be forged with the public key, which is public"
    )
    assert seen["options"]["require"] == ["exp", "iss", "aud"]
    assert seen["options"]["verify_exp"] is True
    assert seen["options"]["verify_nbf"] is True
