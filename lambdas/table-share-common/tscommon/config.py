"""Env-derived configuration for the table-share control-plane Lambdas.

Read once at import; modules reference config.X at call time (never
from config import X) so tests can patch the attribute and the change takes effect.
"""

import os
import re


def _require(name: str) -> str:
    """Return a required env var, failing fast at import if it's unset or empty.

    Surfaces a missing var as a clear, named error at cold start rather than an
    opaque S3/Cognito/JWKS failure mid-invocation (SPEC-083 FR-001).
    """
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"required environment variable {name!r} is unset or empty")
    return value


# Set by Terraform (required — fail fast if missing); AWS_REGION is provided by the runtime.
USER_POOL_ID = _require("COGNITO_USER_POOL_ID")
APP_CLIENT_ID = _require("COGNITO_APP_CLIENT_ID")
ADMIN_BUCKET = _require("ADMIN_BUCKET")
REGION = os.environ.get("AWS_REGION", "")

# Catalog-safe identifier: lowercase, leading letter, [a-z0-9_], 3-63 chars. The
# single rule for usernames, DB names, view names, and (result) table names.
CATALOG_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

# The two recipient kinds a share request may target (SPEC-089 contract).
RECIPIENT_KINDS = frozenset({"user", "space"})
