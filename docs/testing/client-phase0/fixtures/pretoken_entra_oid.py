"""Pre-token-generation trigger for the Phase 0 test pool: emit the Entra object id as ``entra_oid``.

The trusted token issuer cannot map ``custom:`` claims (its claim path refuses a colon), and a mapped
attribute is writable, so the claim is taken from the federated identity Cognito recorded at sign-in:
the first ``identities`` entry's ``userId``, which is the SAML NameID. The federation is SAML with a
persistent NameID sourced from ``user.objectid``; over OIDC this would be Entra's pairwise ``sub``,
never the object id, and check 5 says so when the subject is not the object id.
"""

import json
from typing import Any


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    """Add ``entra_oid`` to the ID token when the user signed in through a federated provider.

    Args:
      event: The pre-token-generation (V1) event.
      _context: The Lambda context, unused.

    Returns:
      The event, with the claim added when there is a federated identity.

    Raises:
      None.
    """
    raw = event.get("request", {}).get("userAttributes", {}).get("identities")
    identities = json.loads(raw) if isinstance(raw, str) else []
    if identities:
        event["response"]["claimsOverrideDetails"] = {
            "claimsToAddOrOverride": {"entra_oid": identities[0]["userId"]}
        }
    return event
