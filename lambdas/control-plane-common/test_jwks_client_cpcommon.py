"""The JWKS client's two dangerous defaults, and the bound on the refetch an unknown kid triggers.

Both defaults were harmless while the only caller was a Step Functions verb. Once an
unauthenticated caller can reach the verifier, a stream of tokens carrying random ``kid``s is an
amplification vector against the provider's JWKS endpoint, driven by requests that have not been
authorized and never will be.

**THE COUNTER IS ON ``fetch_data``, NOT ON THE RESPONSE.** Every one of those requests correctly
returns a refusal whether or not the bound exists, so a test asserting the refusal proves nothing
at all — it passes identically against a client that refetches twenty times. Counting the fetches
is the only assertion here that can fail.

**And it counts the COLD fetch separately from the refetch.** The inherited key-set cache is
empty on a cold container, so the first lookup legitimately fetches once; the thing being bounded
is the *cache-bypassing* refetch after it. Asserting a flat "exactly one" would be wrong on the
first run and would get "fixed" by loosening the assertion rather than by reading it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import jwt
import pytest
from cpcommon import auth, clients
from cpcommon.errors import AuthError
from cpcommon.jwks import (
    API_FUNCTION_TIMEOUT_SECONDS,
    API_GATEWAY_INTEGRATION_CEILING_SECONDS,
    JWKS_HTTP_TIMEOUT_SECONDS,
    JWKS_REFRESH_COOLDOWN_SECONDS,
    CooldownJWKClient,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

JWKS_URI = "https://provider.example/.well-known/jwks.json"
KNOWN_KID = "the-live-key"
ROTATED_KID = "the-new-key"


def _jwk(kid):
    """Renders the test key as a JWKS entry under the given kid."""
    entry = RSAAlgorithm.to_jwk(_KEY.public_key(), as_dict=True)
    entry.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return entry


class _Clock:
    """A monotonic clock a test advances by hand."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _client(kids=(KNOWN_KID,), clock=None, fail=None):
    """Builds a cooldown client over a counted, in-memory key set.

    Args:
      kids: Which kids the endpoint currently publishes. Mutated by a test to rotate.
      clock: The time source, so a test can advance it.
      fail: An exception to raise from every fetch, for the transport-failure case.

    Returns:
      A tuple of the client and a one-element list holding the fetch count.
    """
    fetches = [0]
    published = list(kids)
    client = CooldownJWKClient(JWKS_URI, clock=clock or _Clock())

    def fetch_data():
        fetches[0] += 1
        if fail is not None:
            raise fail
        data = {"keys": [_jwk(kid) for kid in published]}
        if client.jwk_set_cache is not None:
            client.jwk_set_cache.put(data)
        return data

    client.fetch_data = fetch_data
    return client, fetches, published


def _token(kid):
    """Mints a token whose header names the given kid."""
    return jwt.encode({"sub": "alice"}, _KEY, algorithm="RS256", headers={"kid": kid})


def test_the_http_timeout_is_explicit_and_clears_the_function_budget():
    client, _, _ = _client()
    assert client.timeout == JWKS_HTTP_TIMEOUT_SECONDS
    # Asserted against the named constants, never a literal: the number that matters is the
    # function's own budget, which is itself set one second under API Gateway's hard ceiling so
    # the function answers first. A fetch allowed to outlive it produces a gateway 504 that
    # reads as an API fault and names nothing.
    assert API_FUNCTION_TIMEOUT_SECONDS < API_GATEWAY_INTEGRATION_CEILING_SECONDS
    assert JWKS_HTTP_TIMEOUT_SECONDS < API_FUNCTION_TIMEOUT_SECONDS


def test_many_distinct_unknown_kids_inside_one_window_cause_at_most_one_refetch():
    clock = _Clock()
    client, fetches, _ = _client(clock=clock)

    for index in range(20):
        with pytest.raises(PyJWKClientError):
            client.get_signing_key_from_jwt(_token(f"unknown-{index}"))

    # One cold fetch to populate the key set, then ONE cache-bypassing refetch for the whole
    # window. Without the cooldown this is 21: a fetch per distinct kid, every one of them
    # unauthenticated.
    assert fetches[0] == 2, (
        f"20 distinct unknown kids caused {fetches[0]} fetches — the refetch is unbounded"
    )


def test_the_known_kid_still_resolves_without_any_refetch():
    client, fetches, _ = _client()
    assert client.get_signing_key_from_jwt(_token(KNOWN_KID)) is not None
    assert fetches[0] == 1, "a kid already in the cached set must not trigger a refetch"


def test_a_rotation_succeeds_once_the_window_has_elapsed():
    clock = _Clock()
    client, fetches, published = _client(clock=clock)

    # First sight of the new kid, before the provider publishes it: one refetch, still refused.
    with pytest.raises(PyJWKClientError):
        client.get_signing_key_from_jwt(_token(ROTATED_KID))
    assert fetches[0] == 2

    published.append(ROTATED_KID)

    # The negative half. Inside the window the key set is NOT refetched, so the genuinely
    # rotated key stays invisible — the accepted, bounded cost.
    with pytest.raises(PyJWKClientError):
        client.get_signing_key_from_jwt(_token(ROTATED_KID))
    assert fetches[0] == 2, "a refetch happened inside the cooldown window"

    clock.advance(JWKS_REFRESH_COOLDOWN_SECONDS + 1)

    assert client.get_signing_key_from_jwt(_token(ROTATED_KID)) is not None
    assert fetches[0] == 3, "the rotation needed exactly one refetch"


def test_a_cold_client_refetches_immediately_rather_than_waiting_out_a_window():
    """Stamping the cooldown at construction would refuse a rotated key for the first minute
    of every cold container — a real refusal introduced to prevent a hypothetical one. Neither
    the counter nor the rotation test above can see it, because both run after a refetch."""
    clock = _Clock()
    client, fetches, published = _client(clock=clock)

    # The provider rotates between this container's cold read and its next one, which is the
    # ordinary way a warm fleet meets a new key.
    cold = client.fetch_data

    def rotating():
        data = cold()
        if ROTATED_KID not in published:
            published.append(ROTATED_KID)
        return data

    client.fetch_data = rotating

    # The very first lookup this container ever performs. The kid misses the cold set, and with
    # no refetch behind it there is no window to be inside — so it must refetch at once and
    # resolve. A cooldown stamped at construction stops at one fetch and refuses.
    assert client.get_signing_key_from_jwt(_token(ROTATED_KID)) is not None
    assert fetches[0] == 2


def test_the_cooled_refusal_is_worded_exactly_like_the_uncooled_one():
    """The control planes interpolate this message into text three suites pin. Two wordings
    would make that text depend on whether an earlier request happened to open the window."""
    clock = _Clock()
    client, _, _ = _client(clock=clock)

    with pytest.raises(PyJWKClientError) as uncooled:
        client.get_signing_key_from_jwt(_token("ghost"))
    with pytest.raises(PyJWKClientError) as cooled:
        client.get_signing_key_from_jwt(_token("ghost"))

    assert str(uncooled.value) == str(cooled.value)
    assert str(cooled.value) == 'Unable to find a signing key that matches: "ghost"'


def test_a_transport_failure_is_unavailable_and_never_an_auth_failure():
    """The fail-CLOSED direction, and the one that decides an HTTP status.

    ``PyJWKClientConnectionError`` subclasses ``PyJWKClientError``, so a single broad handler
    turns a provider outage into "your token is bad" — which at an API tells every user to sign
    in again for something no user can fix. No happy-path test can see this.
    """
    client, _, _ = _client(fail=PyJWKClientConnectionError("endpoint unreachable"))
    clients.jwks = lambda url: client

    cfg = auth.VerifierConfig(
        issuer="https://provider.example",
        audience="a-client",
        jwks_uri=JWKS_URI,
        username_claim="username",
        required_claims={},
    )

    with pytest.raises(auth.VerifierUnavailable) as raised:
        auth.verify_token(_token(KNOWN_KID), cfg)

    assert not isinstance(raised.value, AuthError), (
        "an unreachable provider must not be catchable as an authentication failure"
    )
    assert str(raised.value) == auth.REASON_JWKS_UNAVAILABLE
