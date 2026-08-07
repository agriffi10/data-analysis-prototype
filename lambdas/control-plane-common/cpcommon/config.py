"""Env-derived configuration shared by every control-plane Lambda.

Read once at import. Modules reference ``config.X`` at call time, never
``from config import X``, so tests can patch the attribute and the change takes effect.
Domain constants stay in their domain configs.

Everything required here must be in the common Lambda environment of every function that
attaches this layer: a shared layer's import-time requirement runs at cold start for every
attaching function, so one missing variable on one verb is a cold-start crash.

Attributes:
  USER_POOL_ID: Cognito user pool, set by Terraform.
  APP_CLIENT_ID: Cognito app client, set by Terraform.
  ADMIN_BUCKET: Admin bucket name, set by Terraform.
  USER_SPACE_BUCKET: Per-user prefix bucket name, set by Terraform.
  SHARED_SPACE_BUCKET: Shared-space bucket name, set by Terraform.
  ATHENA_WORKGROUP: Athena workgroup, set by Terraform.
  REGION: Provided by the Lambda runtime, not by Terraform.
  NOTIFICATIONS_QUEUE_URL: Optional and never required — notifications are best-effort, so
    an unset queue URL makes every emit a logged no-op rather than crashing the verb.
  CATALOG_IDENTIFIER_RE: The single catalog-safe identifier rule — lowercase, leading
    letter, [a-z0-9_], 3-63 chars — for usernames, database, view, table and partition-key
    names.
  REFRESH_MAX_DEFINITION_BYTES: Largest live table definition a refresh will carry onto the
    Step Functions state. Its own bound, deliberately not table-share's, which was measured
    for a 50-recipient Map. Breaching the 256 KB state-payload limit raises
    States.DataLimitExceeded outside every Catch, so an oversized table is refused up front.
    Sizing evidence is in ``docs/lambda-rationale.md``.
"""

import os
import re


def _require(name: str) -> str:
    """Reads a required environment variable, failing fast at import if unset or empty.

    Surfaces a missing variable as a clear, named error at cold start rather than an opaque
    S3, Athena, Cognito or JWKS failure mid-invocation.

    Args:
      name: The environment variable to read.

    Returns:
      Its value.

    Raises:
      RuntimeError: If the variable is unset or empty.
    """
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"required environment variable {name!r} is unset or empty")
    return value


USER_POOL_ID = _require("COGNITO_USER_POOL_ID")
APP_CLIENT_ID = _require("COGNITO_APP_CLIENT_ID")
ADMIN_BUCKET = _require("ADMIN_BUCKET")
USER_SPACE_BUCKET = _require("USER_SPACE_BUCKET")
SHARED_SPACE_BUCKET = _require("SHARED_SPACE_BUCKET")
ATHENA_WORKGROUP = _require("ATHENA_WORKGROUP")
REGION = os.environ.get("AWS_REGION", "")

NOTIFICATIONS_QUEUE_URL = os.environ.get("NOTIFICATIONS_QUEUE_URL", "")

CATALOG_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

REFRESH_MAX_DEFINITION_BYTES = 40 * 1024
