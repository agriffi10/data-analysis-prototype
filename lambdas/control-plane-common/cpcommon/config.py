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

The eight attributes are declared under ``TYPE_CHECKING`` and resolved by ``__getattr__``
under ``else``, and the branch is what makes the declarations worth writing: a module-level
``__getattr__`` typed ``-> str`` makes a checker accept ANY attribute name here, so a
misspelled ``config.ADMIN_BUKCET`` would typecheck and fail at runtime. Hiding the hook from
the checker and naming the eight keeps that a type error, as it was before SPEC-156.

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
from typing import TYPE_CHECKING

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


def require(name: str) -> str:
    """The fleet's ONE fail-fast environment reader, for values outside ``_REQUIRED_VARS``.

    ``_REQUIRED_VARS`` above is the set every control plane needs, and a domain layer must not
    add to it: that set is a fleet-wide contract, asserted per plane by
    ``test_the_common_environment_satisfies_every_import_time_require``, so a variable only one
    plane sets would fail every other plane's guard. SPEC-168's ``ARCHIVE_BUCKET`` is the first
    such value and this is what it uses instead.

    Exported rather than left private so a domain layer reaches for it instead of writing its
    own three-line ``os.environ`` check — one reader means one error sentence and one place the
    fail-fast behaviour is decided (SPEC-156).

    **It is a FUNCTION, not a module attribute, and that is what keeps a domain config
    import-safe.** A constant resolved at import time in a layer module runs for every
    attaching function whether or not it uses the value, and an unset variable then crashes at
    COLD START, where no test and no deploy can see it (PR #196).

    Args:
      name: The environment variable to read.

    Returns:
      Its value.

    Raises:
      RuntimeError: If the variable is unset or empty.
    """
    return _require(name)


if TYPE_CHECKING:
    USER_POOL_ID: str
    APP_CLIENT_ID: str
    ADMIN_BUCKET: str
    USER_SPACE_BUCKET: str
    SHARED_SPACE_BUCKET: str
    ATHENA_WORKGROUP: str
    REGION: str
    NOTIFICATIONS_QUEUE_URL: str
else:

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
