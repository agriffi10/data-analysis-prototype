"""Shared configuration for the shared-space control-plane Lambdas.

Env-derived constants, read once at import. Modules reference them as ``config.X``
at call time (never ``from config import X``) so tests can patch the attribute
(e.g. ``config.ADMIN_BUCKET = "admin-bkt"``) and the change takes effect.

Published in the ``shared-space-common`` Lambda layer and imported by the validator
and every verb Lambda.
"""

import os


def _require(name: str) -> str:
    """Return a required env var, failing fast at import if it's unset or empty.

    Surfaces a missing var as a clear, named error at cold start rather than an opaque
    S3/JWKS failure mid-invocation (SPEC-083 FR-001).
    """
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"required environment variable {name!r} is unset or empty")
    return value


SCHEMA_VERSION = 1
OWNER_ONLY_ACTIONS = frozenset({"add_members", "remove_members", "delete"})
VALID_ACTIONS = frozenset(
    {"create", "add_members", "remove_members", "leave", "delete", "forget", "acknowledge_membership"}
)

# Set by Terraform (required — fail fast if missing); AWS_REGION is provided by the runtime.
USER_POOL_ID = _require("COGNITO_USER_POOL_ID")
APP_CLIENT_ID = _require("COGNITO_APP_CLIENT_ID")
ADMIN_BUCKET = _require("ADMIN_BUCKET")
SHARED_SPACE_BUCKET = _require("SHARED_SPACE_BUCKET")
USER_SPACE_BUCKET = _require("USER_SPACE_BUCKET")
PORTAL_ROLE_ARN = _require("PORTAL_ROLE_ARN")
MAX_SHARED_MEMBERSHIPS = int(os.environ.get("MAX_SHARED_MEMBERSHIPS", "10"))
REGION = os.environ.get("AWS_REGION", "")

# Target queue for `create` notifications. When unset, notify.emit_notification is a
# logged no-op, so this module stays deployable without the notifications pipeline.
NOTIFICATIONS_QUEUE_URL = os.environ.get("NOTIFICATIONS_QUEUE_URL", "")

# LF permissions granted to the SHARED portal role per shared DB — identical to the
# personal-DB grant. Per-user isolation is the IAM membership tag, not this grant;
# LF just lets the role use the DB under enforcement.
DATABASE_PERMISSIONS = ["DESCRIBE", "CREATE_TABLE", "ALTER", "DROP"]
TABLE_PERMISSIONS = ["SELECT", "INSERT", "DESCRIBE", "ALTER", "DROP"]
