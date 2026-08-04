"""Env-derived configuration shared by every control-plane Lambda (SPEC-107).

The shared core extracted from tbcommon/tscommon: region, User Pool identifiers, the
three bucket names, the Athena workgroup, the (optional) notifications queue URL, and
the catalog-safe identifier rule. Domain constants (tbcommon's ``PARTITION_TYPES``,
tscommon's ``SHARE_MAX_*`` / ``RECIPIENT_KINDS``) stay in their domain configs.

Read once at import; modules reference ``config.X`` at call time (never
``from config import X``) so tests can patch the attribute and the change takes effect.
EVERYTHING _require()d here MUST be in the COMMON lambda env of EVERY function that
attaches this layer — a shared layer's import-time _require runs at cold start for every
attaching function, so one missing var on one verb is a cold-start crash (the
table-builder production break, PR #196).
"""

import os
import re


def _require(name: str) -> str:
    """Return a required env var, failing fast at import if it's unset or empty.

    Surfaces a missing var as a clear, named error at cold start rather than an opaque
    S3/Athena/Cognito/JWKS failure mid-invocation (SPEC-083 FR-001).
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
ATHENA_WORKGROUP = _require("ATHENA_WORKGROUP")
REGION = os.environ.get("AWS_REGION", "")

# Optional (never _require): notifications are best-effort — an unset queue URL makes
# every emit a logged no-op; it must not crash the verbs.
NOTIFICATIONS_QUEUE_URL = os.environ.get("NOTIFICATIONS_QUEUE_URL", "")

# Catalog-safe identifier: lowercase, leading letter, [a-z0-9_], 3-63 chars. The single
# rule for usernames, DB names, view names, table names, and partition-key names.
CATALOG_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

# Largest live table definition a REFRESH will carry onto the Step Functions state
# (SPEC-143). Its own bound, deliberately NOT tscommon's SHARE_MAX_DEFINITION_BYTES: that
# 32 KiB was measured for table-share's 50-recipient Map, where the definition is copied
# into every item, and table-builder has no Map.
#
# What rides here instead is one definition plus what infer-schema then adds to the SAME
# state — its own inferred columns and the generated DDL. COLUMNS THEREFORE RIDE THREE
# TIMES while table properties ride once, so the worst case is a definition spent entirely
# on columns (an ordinary flat Parquet table), NOT a mixed one. Measured at that
# composition by test_load_table_definition.py:
#
#     cap      columns   whole state   % of 256 KB
#     32 KiB       713        92,331          35%
#     40 KiB       891       115,293          44%   <- chosen
#     48 KiB     1,069       138,255          53%   <- over half; rejected
#
# Breaching the 256 KB state-payload limit raises States.DataLimitExceeded, thrown OUTSIDE
# every Catch — no recorded outcome and no notification, on a request that already did all
# its work. So an oversized table is refused up front as a whole-request terminal.
REFRESH_MAX_DEFINITION_BYTES = 40 * 1024
