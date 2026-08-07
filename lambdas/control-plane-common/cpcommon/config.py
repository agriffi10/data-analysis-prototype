"""Env-derived configuration shared by every control-plane Lambda.

Resolved on first access, not at import, and cached in the module namespace afterwards.
Modules reference ``config.X`` at call time, never ``from config import X``, so tests can
patch the attribute and the change takes effect. Domain constants stay in their domain
configs.

Importing this module requires nothing. Reading an attribute requires that attribute's
variable — so a function pays only for what it actually uses, and a missing variable still
fails loudly, with the same named error, at first use. That is what SPEC-156 FR-004 changed
and why: the eager ``_require`` of six variables at import meant a function setting three of
them could not import ``cpcommon.auth`` at all, which is how ``notifications-writer`` came to
carry a second copy of the fleet's JWKS verification path.

Laziness is not silence. A required variable that is unset raises exactly where it is read,
naming itself, rather than being papered over with a default.

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
  _REQUIRED_VARS: Attribute name to environment variable, for the values a control plane
    cannot run without.
  _OPTIONAL_VARS: The same, for values that degrade to an empty string rather than raising.
"""

import os
import re

_REQUIRED_VARS = {
    "USER_POOL_ID": "COGNITO_USER_POOL_ID",
    "APP_CLIENT_ID": "COGNITO_APP_CLIENT_ID",
    "ADMIN_BUCKET": "ADMIN_BUCKET",
    "USER_SPACE_BUCKET": "USER_SPACE_BUCKET",
    "SHARED_SPACE_BUCKET": "SHARED_SPACE_BUCKET",
    "ATHENA_WORKGROUP": "ATHENA_WORKGROUP",
}

_OPTIONAL_VARS = {
    "REGION": "AWS_REGION",
    "NOTIFICATIONS_QUEUE_URL": "NOTIFICATIONS_QUEUE_URL",
}

CATALOG_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

REFRESH_MAX_DEFINITION_BYTES = 40 * 1024


def _require(name: str) -> str:
    """Reads a required environment variable, failing fast if unset or empty.

    Surfaces a missing variable as a clear, named error at the point of use rather than an
    opaque S3, Athena, Cognito or JWKS failure later in the invocation.

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


def __getattr__(name: str) -> str:
    """Resolves an env-derived attribute on first access and caches it in the module.

    Caching into ``globals()`` rather than re-reading keeps the read-once semantics the
    callers were written against, and leaves the attribute an ordinary module global that a
    test can patch — this hook only runs while the name is absent.

    Args:
      name: The attribute being read.

    Returns:
      The resolved value.

    Raises:
      RuntimeError: If the name maps to a required variable that is unset or empty.
      AttributeError: If the name is not an env-derived attribute of this module.
    """
    if name in _REQUIRED_VARS:
        value = _require(_REQUIRED_VARS[name])
    elif name in _OPTIONAL_VARS:
        value = os.environ.get(_OPTIONAL_VARS[name], "")
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Lists the module's attributes, including any not yet resolved.

    Args:
      None.

    Returns:
      The sorted attribute names.

    Raises:
      None.
    """
    return sorted({*globals(), *_REQUIRED_VARS, *_OPTIONAL_VARS})
