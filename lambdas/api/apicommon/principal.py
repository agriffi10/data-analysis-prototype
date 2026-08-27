"""Resolving who is calling, from the one place a credential is allowed to arrive.

**The token is read from ``Authorization: Bearer <token>`` and from nowhere else.** Not a query
parameter — those reach access logs, and a credential in an access log is a credential in a
place nobody is guarding. Not a cookie, because a cookie is attached by the browser
automatically and that is the whole of what makes CSRF a thing; a bearer header is attached
only by script that can read the token, and cross-origin script cannot. Not a body field. This
function is given the headers alone, so the other three are unreachable rather than merely
unread.

**A malformed header is refused, never salvaged.** A value carrying a second scheme, or
doubled whitespace, is a request nobody meant to send; guessing at it is how a parser comes to
accept something the thing on the other side never emitted.

Attributes:
  AUTHORIZATION: The header the credential arrives in, matched case-insensitively because a
    header name is case-insensitive by definition and only some gateways normalise it.
  BEARER: The scheme, compared lowercased for the same reason.
  REASON_NO_CREDENTIAL: Logged when nothing usable arrived. A fixed literal, like every
    other reason code — an interpolated one would carry the caller's header into the log.
"""

from collections.abc import Mapping

from cpcommon.auth import AuthError, Principal, verify_token

from . import config

AUTHORIZATION = "authorization"
BEARER = "bearer"

REASON_NO_CREDENTIAL = "no_bearer_credential"


def _bearer_token(headers: Mapping[str, str]) -> str:
    """Extracts the bearer token from a header mapping.

    Args:
      headers: The request's headers.

    Returns:
      The raw token.

    Raises:
      AuthError: If the header is absent, or is not exactly a bearer credential.
    """
    value = ""
    for name, supplied in headers.items():
        if name.lower() == AUTHORIZATION:
            value = supplied or ""
            break

    parts = value.split(" ")
    if len(parts) != 2 or parts[0].lower() != BEARER or not parts[1]:
        raise AuthError(REASON_NO_CREDENTIAL)
    return parts[1]


def resolve(headers: Mapping[str, str]) -> Principal:
    """Returns the verified caller, or refuses.

    Args:
      headers: The request's headers. The only thing this function is given, so a username the
        caller stated in a query string or a body cannot reach it.

    Returns:
      The verified caller.

    Raises:
      AuthError: With a fixed reason code, if no usable credential was supplied or the token
        does not verify.
      VerifierUnavailable: If the provider's keys could not be retrieved.
      ConfigError: If this API's own provider configuration is unusable.
    """
    return verify_token(_bearer_token(headers), config.verifier_config())
