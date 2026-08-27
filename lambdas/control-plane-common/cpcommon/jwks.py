"""The JWKS client, with the two defaults that are hazards at an internet-facing boundary.

``PyJWKClient(url)`` was built with every default while its only caller was a Step Functions
verb, where both of these were harmless. Neither is harmless once an unauthenticated caller can
reach the verifier.

**The timeout.** PyJWT's default is 30 seconds, which is longer than the API function's own
budget. Left there, a hung JWKS endpoint produces a gateway timeout that reads as an API fault
and names nothing.

**The unknown-``kid`` refetch.** ``PyJWKClient.get_signing_key`` refreshes the key set,
deliberately bypassing the cache, whenever a ``kid`` misses. That is correct for a rotation and
catastrophic under attack: a stream of tokens carrying random ``kid``s is an unauthenticated
amplification against the provider's JWKS endpoint, driven by requests that have not been
authorized and never will be. The bound here is a **cooldown on the refetch itself**.

**It is deliberately NOT a negative cache keyed by ``kid``**, which is the design that suggests
itself and does not work: such a cache misses on every *distinct* unknown ``kid``, which is
exactly the traffic being bounded, so it would pass review and fail the counter.

**The cost is bounded eventual consistency, and it is accepted rather than implied.** For up to
``JWKS_REFRESH_COOLDOWN_SECONDS`` after a provider rotates its signing keys, this client refuses
tokens signed with the new one. Cognito publishes both keys across a rotation and a window this
short sits far inside any overlap, so no real rotation is expected to reach a user; the trade is
a bounded refusal against an unauthenticated amplification vector, and refusal is the
fail-closed direction.

Attributes:
  JWKS_HTTP_TIMEOUT_SECONDS: How long one JWKS fetch may take. Generous for a small HTTPS GET
    and far under the function's own budget, so the verifier gives up long before its caller.
  JWKS_REFRESH_COOLDOWN_SECONDS: The shortest interval between two cache-bypassing refetches.
  API_GATEWAY_INTEGRATION_CEILING_SECONDS: AWS's hard, non-raisable ceiling on an HTTP API
    integration. Named because it is what sizes everything below it.
  API_FUNCTION_TIMEOUT_SECONDS: The API function's own timeout, set one second under that
    ceiling so the function answers first and the caller gets its error rather than a gateway
    504 raised while the invocation keeps running and keeps billing.
"""

import time
from collections.abc import Callable

from jwt import PyJWK, PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

JWKS_HTTP_TIMEOUT_SECONDS = 5
JWKS_REFRESH_COOLDOWN_SECONDS = 60

API_GATEWAY_INTEGRATION_CEILING_SECONDS = 30
API_FUNCTION_TIMEOUT_SECONDS = 29


def _unavailable(exc: Exception) -> PyJWKClientConnectionError:
    """Presents any failure to READ the key set as one unavailable-provider type.

    The distinction this draws is the one an HTTP status turns on: "this token is bad" against
    "whether this token is good could not be established". Only the transport error was treated
    as the second, and PyJWT raises it for exactly two causes — so a provider answering a proxy
    page, an array instead of an object, a key set with no usable keys, or failing TLS all
    arrived as ordinary verification failures and were refused as 401. That tells every user to
    sign in again for an outage, and brings a refresh storm with it.

    Args:
      exc: The failure raised while reading the key set.

    Returns:
      The exception to raise in its place.

    Raises:
      None.
    """
    return PyJWKClientConnectionError(
        f"the key set could not be read: {type(exc).__name__}"
    )


def _no_matching_key(kid: str) -> PyJWKClientError:
    """Builds the refusal for a ``kid`` that is not in the key set.

    **One builder, used by both the cooled and the uncooled path**, because the two must be
    indistinguishable to a caller. The control planes interpolate this message into the text
    three suites pin, so a differently-worded refusal on the cooldown path would make that text
    depend on whether some earlier request happened to open the window.

    Args:
      kid: The key id that did not match.

    Returns:
      The exception to raise, worded exactly as PyJWT words it.

    Raises:
      None.
    """
    return PyJWKClientError(f'Unable to find a signing key that matches: "{kid}"')


class CooldownJWKClient(PyJWKClient):
    """A ``PyJWKClient`` whose cache-bypassing refetch is rate-limited per container.

    **One invocation per container is assumed**, which is the Lambda execution model this
    fleet runs under. The cooldown stamp is not synchronised, so under genuine concurrency
    the bound degrades to one refetch per thread rather than one per container — still
    bounded, but by a different number than the one this class is named for.

    Attributes:
      _cooldown: Seconds that must pass between two refetches.
      _clock: Monotonic time source, injected so a test can advance it.
      _last_refresh: When the last refetch happened, or ``None`` if none ever has.
    """

    def __init__(
        self,
        uri: str,
        *,
        timeout: float = JWKS_HTTP_TIMEOUT_SECONDS,
        cooldown: float = JWKS_REFRESH_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        """Builds the client.

        ``_last_refresh`` starts unset rather than stamped with the current time, and the
        difference is load-bearing: stamping it here would refuse a genuinely rotated key for
        the first ``cooldown`` seconds of every cold container, which is a real refusal
        introduced to prevent a hypothetical one.

        Args:
          uri: The JWKS endpoint.
          timeout: Seconds one fetch may take.
          cooldown: Seconds between refetches.
          clock: Monotonic time source.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__(uri, timeout=timeout)
        self._cooldown = cooldown
        self._clock = clock
        self._last_refresh: float | None = None

    def get_signing_key(self, kid: str) -> PyJWK:
        """Returns the signing key for ``kid``, refetching at most once per cooldown window.

        **The refetch is stamped before it is attempted, not after.** Stamping afterwards
        means a fetch that raises never records itself, so every subsequent unknown ``kid``
        tries again and the bound evaporates exactly when the endpoint is already
        unhealthy — which is when it carries weight. The cost is that one failed fetch
        spends the window.

        The first lookup goes through ``get_signing_keys()`` rather than reading the cache
        directly. That distinction matters: the inherited key-set cache is empty on a cold
        container and expires on its own lifespan, so reading it directly would refuse every
        token until something else happened to populate it. That fetch is the ordinary one and
        is not what this class bounds — the bound is on the *cache-bypassing* refetch below.

        Args:
          kid: The key id from the token's header.

        Returns:
          The matching signing key.

        Raises:
          PyJWKClientError: If no key matches, whether or not a refetch was permitted.
        """
        signing_key = self.match_kid(self._key_set(refresh=False), kid)
        if signing_key is not None:
            return signing_key

        now = self._clock()
        if self._last_refresh is not None and now - self._last_refresh < self._cooldown:
            raise _no_matching_key(kid)

        self._last_refresh = now
        signing_key = self.match_kid(self._key_set(refresh=True), kid)
        if signing_key is None:
            raise _no_matching_key(kid)
        return signing_key

    def _key_set(self, *, refresh: bool) -> list[PyJWK]:
        """Reads the key set, or reports the provider as unavailable.

        A ``kid`` that is genuinely absent from a key set that WAS read is left alone — that is
        an authentication failure and stays one. Everything here is the other case.

        Args:
          refresh: Whether to bypass the cache.

        Returns:
          The signing keys.

        Raises:
          PyJWKClientConnectionError: If the key set could not be read, for any reason.
        """
        try:
            return self.get_signing_keys(refresh=refresh)
        except PyJWKClientConnectionError:
            raise
        except Exception as exc:
            raise _unavailable(exc) from exc
