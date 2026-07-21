"""Domain configuration for the shared-space control-plane Lambdas.

SPEC-125 removed this module's SHARED core — the ``_require`` helper and the User-Pool /
bucket / region / notifications-queue reads — which duplicated ``cpcommon.config``. Callers
that need one of those now read ``cpcommon.config`` directly (``from cpcommon import config
as cpconfig``), so there is ONE definition at runtime and one attribute to patch in tests,
rather than a re-export that looks like a single source and is really a second copy.

What is left is the shared-space DOMAIN surface: the registry schema version, the action
sets the authorizer gates on, the portal role Lake Formation grants target, the membership
cap, and the LF permission lists. Nothing else in the repo has an opinion about any of them.

Read once at import. Modules reference them as ``config.X`` at call time (never ``from
config import X``) so a test patch takes effect.
"""

import os

from cpcommon.config import _require

SCHEMA_VERSION = 1
OWNER_ONLY_ACTIONS = frozenset({"add_members", "remove_members", "delete"})
VALID_ACTIONS = frozenset(
    {"create", "add_members", "remove_members", "leave", "delete", "forget", "acknowledge_membership"}
)

# The portal role Lake Formation grants are made to. Domain-specific — no other control
# plane grants to it — so it keeps the same import-time fail-fast cpcommon.config uses:
# a missing var surfaces as a named cold-start error, not an opaque LF failure mid-request.
PORTAL_ROLE_ARN = _require("PORTAL_ROLE_ARN")
MAX_SHARED_MEMBERSHIPS = int(os.environ.get("MAX_SHARED_MEMBERSHIPS", "10"))

# LF permissions granted to the SHARED portal role per shared DB — identical to the
# personal-DB grant. Per-user isolation is the IAM membership tag, not this grant;
# LF just lets the role use the DB under enforcement.
DATABASE_PERMISSIONS = ["DESCRIBE", "CREATE_TABLE", "ALTER", "DROP"]
TABLE_PERMISSIONS = ["SELECT", "INSERT", "DESCRIBE", "ALTER", "DROP"]
