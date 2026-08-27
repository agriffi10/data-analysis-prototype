"""The refusal surface: which condition gets which code, and nothing about why.

**Every authentication failure returns the same bytes.** No token, a malformed token, a bad
signature, a wrong issuer, a wrong audience, a wrong token type, a missing username claim and an
expired-but-otherwise-valid token are indistinguishable to the caller. A body that varied per
failure would be a map of which check failed, which is exactly what someone probing this boundary
wants.

**Expiry is deliberately not distinguished**, and the reason is worth stating because the opposite
looks helpful: the browser refreshes once and retries once on ANY 401, so a discriminator buys the
client nothing and costs the oracle above. A builder who adds a ``token_expired`` code to drive the
refresh has reintroduced it.

**The reason a request was refused goes to the log record**, where an operator can read it and a
caller cannot.

**Three AWS-side conditions are kept apart, because conflating them makes isolation-working-
correctly read as a bug and a bug read as a refusal.** A denial is 403 and must never trigger a
re-login. An identity this API cannot assume is 5xx, because no user action fixes it. An unusable
token is 401 and belongs entirely to the boundary above — nothing here mints one, and nothing here
reuses its code for an AWS-side failure.

**A refusal body names nothing.** Not a bucket, not a key, not a space, not a role. A 403 that
described what was refused would answer "does that exist?" for anyone willing to ask, which is the
question the product declines to answer anywhere else.

**No status is written here.** A code decides its status once, in the contract, and this module
names only codes — so the wire's status set stays one decision in one place rather than a set of
literals spread across the modules that happen to raise.

Attributes:
  UNAUTHENTICATED_CODE: The machine code the browser maps to its "sign in again" wording.
  SERVER_FAULT_CODE: What a misconfiguration or an unreachable provider returns. NEVER the
    unauthenticated one — that reads to the browser as "sign in again", which cannot fix either.
  FORBIDDEN_CODE: What a refused AWS call returns. The isolation model WORKING, not failing.
    Deliberately not the unauthenticated one: signing in again cannot help, and telling a user it
    can sends them through a refresh that changes nothing.
  IDENTITY_UNAVAILABLE_CODE: What an unusable identity returns — the caller did nothing wrong and
    can do nothing about it, so it is a fault on this side.
  INTERNAL_ERROR_CODE: The outermost mapping for anything unrecognised, carrying the exception's
    TYPE and never its message.
  NOT_FOUND_CODE: What an unregistered route returns to an identified caller.
  DENIAL_CODES: The service codes meaning "this principal is not authorized". Lake Formation's
    denials arrive under the second of them.
  CHALLENGE_HEADERS: The extra header a 401 carries. What makes it a well-formed 401 rather than a
    401-shaped 403.
"""

from typing import Any

from .config import ConfigError
from .envelope import failure
from .identity import IdentityUnavailableError, aws_error_code

UNAUTHENTICATED_CODE = "SessionExpired"
SERVER_FAULT_CODE = "ApiUnavailable"
FORBIDDEN_CODE = "AccessDenied"
IDENTITY_UNAVAILABLE_CODE = "IdentityUnavailable"
INTERNAL_ERROR_CODE = "InternalError"
NOT_FOUND_CODE = "NotFound"

DENIAL_CODES = frozenset({"AccessDenied", "AccessDeniedException"})

CHALLENGE_HEADERS = {"www-authenticate": "Bearer"}


def unauthenticated(request_id: str = "") -> dict[str, Any]:
    """Builds the one refusal.

    Takes nothing about the caller, and that is the design: there is nothing a caller could pass
    that ought to reach the response, so the function offers nowhere to put it.

    Args:
      request_id: The gateway's id for this request, echoed so a reported failure is findable.

    Returns:
      The 401 response, body already serialized, carrying the challenge header.

    Raises:
      None.
    """
    response = failure(UNAUTHENTICATED_CODE, request_id)
    response["headers"].update(CHALLENGE_HEADERS)
    return response


def server_fault(request_id: str = "") -> dict[str, Any]:
    """Builds the refusal for a fault on this side of the boundary.

    Reached when configuration is unusable or the provider's keys cannot be retrieved — neither of
    which says anything about the caller's token, so neither may answer 401.

    Args:
      request_id: The gateway's id for this request.

    Returns:
      The 5xx response, body already serialized.

    Raises:
      None.
    """
    return failure(SERVER_FAULT_CODE, request_id)


def forbidden(request_id: str = "") -> dict[str, Any]:
    """Builds the refusal for a call AWS declined.

    Names nothing about what was refused, for the same reason the unauthenticated one names
    nothing about the caller: that is what keeps this from becoming an existence oracle.

    Args:
      request_id: The gateway's id for this request.

    Returns:
      The 403 response, body already serialized.

    Raises:
      None.
    """
    return failure(FORBIDDEN_CODE, request_id)


def identity_unavailable(request_id: str = "") -> dict[str, Any]:
    """Builds the refusal for a caller this API could not act as.

    Args:
      request_id: The gateway's id for this request.

    Returns:
      The 5xx response, body already serialized.

    Raises:
      None.
    """
    return failure(IDENTITY_UNAVAILABLE_CODE, request_id)


def not_found(request_id: str = "") -> dict[str, Any]:
    """Builds the answer for a route this API does not serve.

    One rule for an unregistered method as well as an unregistered path: a 405 would advertise
    which paths exist to a caller who may not use them, and only reaching this after
    authentication is what keeps it from being an inventory.

    Args:
      request_id: The gateway's id for this request.

    Returns:
      The 404 response, body already serialized. It echoes neither the method nor the path — both
      are caller-controlled, and a request line is not a thing to round-trip.

    Raises:
      None.
    """
    return failure(NOT_FOUND_CODE, request_id)


def internal_error(exc: BaseException, request_id: str = "") -> dict[str, Any]:
    """Builds the answer for a fault with no defined mapping.

    The detail names the exception's TYPE and never its message. A message is where a bucket name,
    a key, a role ARN or a caller's own value ends up, and the outermost handler is the one place
    that sees every one of them.

    Args:
      exc: The exception that reached the outermost handler.
      request_id: The gateway's id for this request.

    Returns:
      The 500 response, body already serialized.

    Raises:
      None.
    """
    return failure(INTERNAL_ERROR_CODE, request_id, detail=type(exc).__name__)


def for_exception(exc: BaseException, request_id: str = "") -> dict[str, Any] | None:
    """Classifies a failure raised by a route into the one response that fits it.

    Returns None rather than a fallback for anything it does not recognise, so an unexpected
    failure keeps rising and is recorded by the span instead of being flattened into a refusal
    that says something untrue about it.

    **What keeps an assume failure out of the 403 branch is not the ordering here.** STS answers
    ``AccessDenied`` when the trust policy is wrong, and reporting that to the caller as a denial
    would tell every user they lack a permission for a misconfiguration only an operator can fix.
    The thing that prevents it is that the identity layer WRAPS every STS failure before it leaves
    — the wrapper carries no service response, so it can only be classified by type. The order
    below is defensive and was measured not to be load-bearing: swapping these two lines changes
    no outcome, while removing the wrap changes two. Stated because a reason that reads false to
    whoever checks it is worse than none.

    A configuration failure raised by a route is answered the same way the boundary above already
    answers one — a server fault, never a 401 and never a denial. Without that it reaches the
    caller as a bare gateway 500 carrying no code, which is the one outcome the wire contract has
    no name for.

    Args:
      exc: The exception a route raised.
      request_id: The gateway's id for this request.

    Returns:
      The response, or None if this is not a condition with a defined answer.

    Raises:
      None.
    """
    if isinstance(exc, IdentityUnavailableError):
        return identity_unavailable(request_id)
    if isinstance(exc, ConfigError):
        return server_fault(request_id)
    if aws_error_code(exc) in DENIAL_CODES:
        return forbidden(request_id)
    return None
