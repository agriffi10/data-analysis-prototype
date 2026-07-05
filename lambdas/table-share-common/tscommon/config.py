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


# Set by Terraform (required — fail fast if missing); AWS_REGION is provided by the
# runtime. EVERYTHING _require()d here must be in the module's COMMON lambda env —
# the fail-fast runs at import for every verb that touches any tscommon module
# (the table-builder hit this in production, PR #196: per-verb env + a shared
# layer config's import-time require = cold-start crash on the verbs missing it).
ADMIN_BUCKET = _require("ADMIN_BUCKET")
USER_SPACE_BUCKET = _require("USER_SPACE_BUCKET")
SHARED_SPACE_BUCKET = _require("SHARED_SPACE_BUCKET")
USER_POOL_ID = _require("COGNITO_USER_POOL_ID")
APP_CLIENT_ID = _require("COGNITO_APP_CLIENT_ID")
ATHENA_WORKGROUP = _require("ATHENA_WORKGROUP")
REGION = os.environ.get("AWS_REGION", "")

# Optional (never _require): notifications are best-effort — an unset queue URL
# makes every emit a logged no-op, it must not crash the verbs (SPEC-094).
NOTIFICATIONS_QUEUE_URL = os.environ.get("NOTIFICATIONS_QUEUE_URL", "")

# Copy caps (SPEC-090): a share exceeding either is a whole-request terminal
# failure ("too large for v1 — S3 Batch Operations is the deferred escape hatch").
# Sized so a recipient Map item's parallel server-side copy finishes comfortably
# inside copy-objects' 900s timeout (architecture §12).
SHARE_MAX_OBJECTS = 1000
SHARE_MAX_TOTAL_BYTES = 20 * 1024**3  # 20 GiB

# Catalog-safe identifier: lowercase, leading letter, [a-z0-9_], 3-63 chars. The
# single rule for usernames, DB names, view names, and (result) table names.
CATALOG_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

# The two recipient kinds a share request may target (SPEC-089 contract).
RECIPIENT_KINDS = frozenset({"user", "space"})
