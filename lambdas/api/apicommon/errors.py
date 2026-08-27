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
  JSON_CONTENT_TYPE: The content type every response carries, success or not.
"""

import json
from typing import Any

UNAUTHENTICATED_STATUS = 401
UNAUTHENTICATED_CODE = "SessionExpired"

SERVER_FAULT_STATUS = 500
SERVER_FAULT_CODE = "ServerError"

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
