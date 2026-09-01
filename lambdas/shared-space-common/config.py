"""Domain configuration for the shared-space control-plane Lambdas.

The shared core — the requirement helper and the user pool, bucket, region and
notifications-queue reads — lives in ``cpcommon.config``, and callers that need one of those
read it directly. There is one definition at runtime and one attribute to patch in tests,
rather than a re-export that looks like a single source and is really a second copy.

What is left is the shared-space domain surface. Read once at import; modules reference these
at call time rather than importing the names, so a test patch takes effect.

Attributes:
  SCHEMA_VERSION: The registry record's schema version.
  OWNER_ONLY_ACTIONS: Actions the authorizer restricts to the space's owner. Transfer is not one
    of them: those raise, and a raise in the validator loses the actor and the space, so the
    refusal reaches nobody. Transfer returns its refusal instead.
  VALID_ACTIONS: Every action the authorizer recognises.
  OPERATOR_ACTIONS: The actions an operator-origin message may ask for. Every other action is
    refused on that origin even though the queue accepts it from the API, because the operator
    door exists for the one case the UI cannot serve and widening it later should be a decision
    rather than an oversight.
  OPERATOR_ORIGIN: The origin value an operator message declares. A message carrying any other
    value is refused rather than treated as a UI request, so an unknown origin fails closed the
    way an unknown assurance does.
  TRANSFER_READER_ROLE_ID: The reader role's IAM unique ID, which is the half of the SQS
    ``SenderId`` before the colon. Read lazily at call time rather than through ``require`` at
    import: the two deploy workflows race, so there is a window in which this code is live and
    the variable is not, and a module-level requirement would fail EVERY verb on this plane at
    cold start during it. Empty is refused at the comparison, which is the safe direction —
    an operator message is refused, and no UI request consults it at all.
  PORTAL_ROLE_ARN: The portal role Lake Formation grants are made to. Domain-specific — no
    other control plane grants to it — so it keeps the same import-time fail-fast the shared
    config uses: a missing variable surfaces as a named cold-start error rather than an opaque
    Lake Formation failure mid-request.
  MAX_SHARED_MEMBERSHIPS: Per-user membership cap.
  DATABASE_PERMISSIONS: Lake Formation database permissions granted to the shared portal role
    per shared database, identical to the personal-database grant. Per-user isolation is the
    IAM membership tag, not this grant; Lake Formation just lets the role use the database
    under enforcement.
  TABLE_PERMISSIONS: The same, at table level.
"""

import os

from cpcommon.config import require

SCHEMA_VERSION = 1
OWNER_ONLY_ACTIONS = frozenset({"add_members", "remove_members", "delete"})
VALID_ACTIONS = frozenset(
    {
        "create",
        "add_members",
        "remove_members",
        "leave",
        "delete",
        "forget",
        "acknowledge_membership",
        "transfer_ownership",
    }
)

OPERATOR_ACTIONS = frozenset({"transfer_ownership"})
OPERATOR_ORIGIN = "operator"
TRANSFER_READER_ROLE_ID = os.environ.get("SHARED_SPACE_TRANSFER_READER_ROLE_ID", "")

PORTAL_ROLE_ARN = require("PORTAL_ROLE_ARN")
MAX_SHARED_MEMBERSHIPS = int(os.environ.get("MAX_SHARED_MEMBERSHIPS", "10"))

DATABASE_PERMISSIONS = ["DESCRIBE", "CREATE_TABLE", "ALTER", "DROP"]
TABLE_PERMISSIONS = ["SELECT", "INSERT", "DESCRIBE", "ALTER", "DROP"]
