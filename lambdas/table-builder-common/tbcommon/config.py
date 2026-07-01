"""Env-derived configuration for the table-builder control-plane Lambdas (SPEC-067).

Read once at import; modules reference ``config.X`` at call time (never
``from config import X``) so tests can patch the attribute and the change takes
effect. Published in the ``table-builder-common`` Lambda layer.
"""

import os
import re

# ── Environment (set by Terraform; AWS_REGION is provided by the runtime) ─────
USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID", "")
ADMIN_BUCKET = os.environ.get("ADMIN_BUCKET", "")
USER_SPACE_BUCKET = os.environ.get("USER_SPACE_BUCKET", "")
SHARED_SPACE_BUCKET = os.environ.get("SHARED_SPACE_BUCKET", "")
REGION = os.environ.get("AWS_REGION", "")

# SPEC-070: the shared analytics workgroup execute-ddl runs the CREATE DDL in.
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "")

# SPEC-072 seam: target for outcome notifications. Unset until SPEC-072 wires the
# env var + the sqs:SendMessage grant, in which case emit is a logged no-op.
NOTIFICATIONS_QUEUE_URL = os.environ.get("NOTIFICATIONS_QUEUE_URL", "")

# Catalog-safe identifier (SPEC-033/048): lowercase, leading letter, [a-z0-9_], 3-63
# chars. The single rule for usernames, DB names, view names, table names, and
# partition-key names.
CATALOG_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

# Partition-key projection types the modal can declare (SPEC-067/069).
PARTITION_TYPES = frozenset({"integer", "date", "string"})
