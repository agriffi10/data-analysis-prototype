"""Env-derived configuration for the table-builder control-plane Lambdas.

Read once at import; modules reference config.X at call time (never
from config import X) so tests can patch the attribute and the change takes effect.
"""

import os
import re


def _require(name: str) -> str:
    """Return a required env var, failing fast at import if it's unset or empty.

    Surfaces a missing var as a clear, named error at cold start rather than an opaque
    S3/Athena/JWKS failure mid-invocation (SPEC-083 FR-001).
    """
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"required environment variable {name!r} is unset or empty")
    return value


# Set by Terraform (required — fail fast if missing); AWS_REGION is provided by the runtime.
USER_POOL_ID = _require("COGNITO_USER_POOL_ID")
APP_CLIENT_ID = _require("COGNITO_APP_CLIENT_ID")
ADMIN_BUCKET = _require("ADMIN_BUCKET")
USER_SPACE_BUCKET = _require("USER_SPACE_BUCKET")
SHARED_SPACE_BUCKET = _require("SHARED_SPACE_BUCKET")
REGION = os.environ.get("AWS_REGION", "")

# The shared analytics workgroup execute-ddl runs the CREATE DDL in.
ATHENA_WORKGROUP = _require("ATHENA_WORKGROUP")

# Target queue for outcome notifications; when unset, emits are a logged no-op.
NOTIFICATIONS_QUEUE_URL = os.environ.get("NOTIFICATIONS_QUEUE_URL", "")

# Catalog-safe identifier: lowercase, leading letter, [a-z0-9_], 3-63 chars. The
# single rule for usernames, DB names, view names, table names, and partition-key
# names.
CATALOG_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

# Partition-key projection types the modal can declare.
PARTITION_TYPES = frozenset({"integer", "date", "string"})
