"""Env-derived configuration for the table-builder control-plane Lambdas.

Read once at import; modules reference config.X at call time (never
from config import X) so tests can patch the attribute and the change takes effect.
"""

import os
import re

# Set by Terraform; AWS_REGION is provided by the runtime.
USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID", "")
ADMIN_BUCKET = os.environ.get("ADMIN_BUCKET", "")
USER_SPACE_BUCKET = os.environ.get("USER_SPACE_BUCKET", "")
SHARED_SPACE_BUCKET = os.environ.get("SHARED_SPACE_BUCKET", "")
REGION = os.environ.get("AWS_REGION", "")

# The shared analytics workgroup execute-ddl runs the CREATE DDL in.
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "")

# Target queue for outcome notifications; when unset, emits are a logged no-op.
NOTIFICATIONS_QUEUE_URL = os.environ.get("NOTIFICATIONS_QUEUE_URL", "")

# Catalog-safe identifier: lowercase, leading letter, [a-z0-9_], 3-63 chars. The
# single rule for usernames, DB names, view names, table names, and partition-key
# names.
CATALOG_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

# Partition-key projection types the modal can declare.
PARTITION_TYPES = frozenset({"integer", "date", "string"})
