"""Domain configuration for the shared-space control-plane Lambdas.

The shared core — the requirement helper and the user pool, bucket, region and
notifications-queue reads — lives in ``cpcommon.config``, and callers that need one of those
read it directly. There is one definition at runtime and one attribute to patch in tests,
rather than a re-export that looks like a single source and is really a second copy.

What is left is the shared-space domain surface. Read once at import; modules reference these
at call time rather than importing the names, so a test patch takes effect.

Attributes:
  SCHEMA_VERSION: The registry record's schema version.
  OWNER_ONLY_ACTIONS: Actions the authorizer restricts to the space's owner.
  VALID_ACTIONS: Every action the authorizer recognises.
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

from cpcommon.config import _require

SCHEMA_VERSION = 1
OWNER_ONLY_ACTIONS = frozenset({"add_members", "remove_members", "delete"})
VALID_ACTIONS = frozenset(
    {"create", "add_members", "remove_members", "leave", "delete", "forget", "acknowledge_membership"}
)

PORTAL_ROLE_ARN = _require("PORTAL_ROLE_ARN")
MAX_SHARED_MEMBERSHIPS = int(os.environ.get("MAX_SHARED_MEMBERSHIPS", "10"))

DATABASE_PERMISSIONS = ["DESCRIBE", "CREATE_TABLE", "ALTER", "DROP"]
TABLE_PERMISSIONS = ["SELECT", "INSERT", "DESCRIBE", "ALTER", "DROP"]
