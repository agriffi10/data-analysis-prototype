"""The refusal surface: one status, one body, and nothing about why.

**Every authentication failure returns the same bytes.** No token, a malformed token, a bad
signature, a wrong issuer, a wrong audience, a wrong token type, a missing username claim and
an expired-but-otherwise-valid token are indistinguishable to the caller. A body that varied
per failure would be a map of which check failed, which is exactly what someone probing this
boundary wants.

**Expiry is deliberately not distinguished**, and the reason is worth stating because the
opposite looks helpful: the browser refreshes once and retries once on ANY 401, so a
discriminator buys the client nothing and costs the oracle above. A builder who adds a
``token_expired`` code to drive the refresh has reintroduced it.

**The reason a request was refused goes to the log record**, where an operator can read it and
a caller cannot.

**Three AWS-side conditions are kept apart, because conflating them makes isolation-working-
correctly read as a bug and a bug read as a refusal.** A denial is 403 and must never trigger a
re-login. An identity this API cannot assume is 5xx, because no user action fixes it. An unusable
token is 401 and belongs entirely to the boundary above — nothing here mints one, and nothing
here reuses its code for an AWS-side failure.

**A refusal body names nothing.** Not a bucket, not a key, not a space, not a role. A 403 that
described what was refused would answer "does that exist?" for anyone willing to ask, which is
the question the product declines to answer anywhere else.

Attributes:
  UNAUTHENTICATED_STATUS: The one status this module returns.
  UNAUTHENTICATED_CODE: The machine code the browser maps to its "sign in again" wording. It is
    settled here and serialised by the transport contract, which does not change it.
  UNAUTHENTICATED_BODY: The one body. A single frozen literal, so byte-identity is structural
    rather than something eight call sites have to agree about.
  UNAUTHENTICATED_HEADERS: Sent with every refusal. The challenge header is what makes this a
    well-formed 401 rather than a 401-shaped 403.
  SERVER_FAULT_STATUS: What a misconfiguration or an unreachable provider returns. NEVER 401 —
    that reads to the browser as "sign in again", which cannot fix either.
  SERVER_FAULT_CODE: Its machine code.
  FORBIDDEN_STATUS: What a refused AWS call returns. The isolation model WORKING, not failing.
  FORBIDDEN_CODE: Its machine code. Deliberately not the unauthenticated one: signing in again
    cannot help, and telling a user it can sends them through a refresh that changes nothing.
  IDENTITY_UNAVAILABLE_STATUS: What an unusable identity returns — the caller did nothing wrong
    and can do nothing about it, so it is a fault on this side.
  IDENTITY_UNAVAILABLE_CODE: Its machine code, resolving to the browser's contact-the-admin
    wording.
  DENIAL_CODES: The service codes meaning "this principal is not authorized". Lake Formation's
    denials arrive under the second of them.
  JSON_CONTENT_TYPE: The content type every response carries, success or not.
"""

import json
from typing import Any

from .identity import IdentityUnavailableError, aws_error_code

UNAUTHENTICATED_STATUS = 401
UNAUTHENTICATED_CODE = "SessionExpired"

SERVER_FAULT_STATUS = 500
SERVER_FAULT_CODE = "ServerError"

FORBIDDEN_STATUS = 403
FORBIDDEN_CODE = "AccessDenied"

IDENTITY_UNAVAILABLE_STATUS = 500
IDENTITY_UNAVAILABLE_CODE = "IdentityUnavailable"

DENIAL_CODES = frozenset({"AccessDenied", "AccessDeniedException"})

JSON_CONTENT_TYPE = "application/json"

UNAUTHENTICATED_BODY = json.dumps({"error": "unauthorized", "code": UNAUTHENTICATED_CODE})

UNAUTHENTICATED_HEADERS = {
    "content-type": JSON_CONTENT_TYPE,
    "www-authenticate": "Bearer",
}


def unauthenticated() -> dict[str, Any]:
    """Builds the one refusal.

    Takes no argument, and that is the design: there is nothing a caller could pass that ought
    to reach the response, so the function offers nowhere to put it.

    Args:
      None.

    Returns:
      The 401 response, body already serialized.

    Raises:
      None.
    """
    return {
        "statusCode": UNAUTHENTICATED_STATUS,
        "headers": dict(UNAUTHENTICATED_HEADERS),
        "body": UNAUTHENTICATED_BODY,
    }


def server_fault() -> dict[str, Any]:
    """Builds the refusal for a fault on this side of the boundary.

    Reached when configuration is unusable or the provider's keys cannot be retrieved — neither
    of which says anything about the caller's token, so neither may answer 401.

    Args:
      None.

    Returns:
      The 5xx response, body already serialized.

    Raises:
      None.
    """
    return {
        "statusCode": SERVER_FAULT_STATUS,
        "headers": {"content-type": JSON_CONTENT_TYPE},
        "body": json.dumps({"error": "server_error", "code": SERVER_FAULT_CODE}),
    }


def forbidden() -> dict[str, Any]:
    """Builds the refusal for a call AWS declined.

    Takes no argument, for the same reason the unauthenticated one does not: there is nothing a
    caller could pass that ought to reach the response, so the function offers nowhere to put it.
    That is what keeps this from becoming an existence oracle.

    Args:
      None.

    Returns:
      The 403 response, body already serialized.

    Raises:
      None.
    """
    return {
        "statusCode": FORBIDDEN_STATUS,
        "headers": {"content-type": JSON_CONTENT_TYPE},
        "body": json.dumps({"error": "forbidden", "code": FORBIDDEN_CODE}),
    }


def identity_unavailable() -> dict[str, Any]:
    """Builds the refusal for a caller this API could not act as.

    Args:
      None.

    Returns:
      The 5xx response, body already serialized.

    Raises:
      None.
    """
    return {
        "statusCode": IDENTITY_UNAVAILABLE_STATUS,
        "headers": {"content-type": JSON_CONTENT_TYPE},
        "body": json.dumps(
            {"error": "identity_unavailable", "code": IDENTITY_UNAVAILABLE_CODE}
        ),
    }


def for_exception(exc: BaseException) -> dict[str, Any] | None:
    """Classifies a failure raised by a route into the one response that fits it.

    Returns None rather than a fallback for anything it does not recognise, so an unexpected
    failure keeps rising and is recorded by the span instead of being flattened into a refusal
    that says something untrue about it.

    **What keeps an assume failure out of the 403 branch is not the ordering here.** STS answers
    ``AccessDenied`` when the trust policy is wrong, and reporting that to the caller as a denial
    would tell every user they lack a permission for a misconfiguration only an operator can fix.
    The thing that prevents it is that the identity layer WRAPS every STS failure before it
    leaves — the wrapper carries no service response, so it can only be classified by type. The
    order below is defensive and was measured not to be load-bearing: swapping these two lines
    changes no outcome, while removing the wrap changes two. Stated because a reason that reads
    false to whoever checks it is worse than none.

    Args:
      exc: The exception a route raised.

    Returns:
      The response, or None if this is not a condition with a defined answer.

    Raises:
      None.
    """
    if isinstance(exc, IdentityUnavailableError):
        return identity_unavailable()
    if aws_error_code(exc) in DENIAL_CODES:
        return forbidden()
    return None
