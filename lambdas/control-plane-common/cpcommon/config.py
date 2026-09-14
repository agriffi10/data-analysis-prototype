"""Env-derived configuration shared by every control-plane Lambda.

Resolved on first access, not at import, and cached in the module namespace afterwards.
Modules reference ``config.X`` at call time, never ``from config import X``, so tests can
patch the attribute and the change takes effect. Domain constants stay in their domain
configs.

Importing this module requires nothing. Reading an attribute requires that attribute's
variable — so a function pays only for what it actually uses, and a missing variable still
fails loudly, with the same named error, at first use. That is what changed
and why: the eager ``_require`` of six variables at import meant a function setting three of
them could not import ``cpcommon.auth`` at all, which is how ``notifications-writer`` came to
carry a second copy of the fleet's JWKS verification path.

Laziness is not silence. A required variable that is unset raises exactly where it is read,
naming itself, rather than being papered over with a default.

The six attributes are declared under ``TYPE_CHECKING`` and resolved by ``__getattr__``
under ``else``, and the branch is what makes the declarations worth writing: a module-level
``__getattr__`` typed ``-> str`` makes a checker accept ANY attribute name here, so a
misspelled ``config.ADMIN_BUKCET`` would typecheck and fail at runtime. Hiding the hook from
the checker and naming the six keeps that a type error.

Attributes:
  ADMIN_BUCKET: Admin bucket name, set by Terraform.
  USER_SPACE_BUCKET: Per-user prefix bucket name, set by Terraform.
  SHARED_SPACE_BUCKET: Shared-space bucket name, set by Terraform.
  ATHENA_WORKGROUP: Athena workgroup, set by Terraform.
  REGION: Provided by the Lambda runtime, not by Terraform.
  NOTIFICATIONS_QUEUE_URL: Optional and never required — notifications are best-effort, so
    an unset queue URL makes every emit a logged no-op rather than crashing the verb.
  STATE_PAYLOAD_LIMIT_BYTES: What Step Functions accepts for one state payload AND for one
    execution input. Breaching either raises ``States.DataLimitExceeded``, which is thrown OUTSIDE
    every Catch — so a request over it is not refused, it disappears.
  CAUSE_MAX_CHARS: The longest error ``Cause`` the service will carry. It is a maximum length in
    CHARACTERS on the execution-history event shapes, not a byte quota on a state, and the
    distinction is the whole reason the next constant exists.
  CAUSE_RESERVATION_BYTES: What a ``Cause`` must be reserved at on a state. A Cause is a JSON
    document sitting inside a JSON string, so it is escaped there like every other value, and the
    worst escaping ``json.dumps`` produces for the characters it emits is two bytes a character.
    Reserving it unescaped would exempt the one value in the model most certainly escaped.
  CATALOG_IDENTIFIER_RE: The single catalog-safe identifier rule — lowercase, leading
    letter, [a-z0-9_], 3-63 chars — for usernames, database, view, table and partition-key
    names.
  MAX_FIFO_KEY_CHARS: The longest ``MessageGroupId`` or ``MessageDeduplicationId`` SQS accepts on
    a FIFO queue.
  FIFO_KEY_RE: The single FIFO key rule — one to ``MAX_FIFO_KEY_CHARS`` printable ASCII
    characters with no space, SQS's "alphanumeric characters and punctuation" written as a
    pattern — for the API's enqueue keys and the notification sender's deduplication id alike.
    Apply it with ``fullmatch``: its ``$`` also matches before a final newline, so ``match``
    would wave ``"abc\\n"`` through and SQS would refuse the send.
  _REQUIRED_VARS: Attribute name to environment variable, for the values a control plane
    cannot run without.
  _OPTIONAL_VARS: The same, for values that degrade to an empty string rather than raising.
"""

import os
import re
from typing import TYPE_CHECKING

_REQUIRED_VARS = {
    "ADMIN_BUCKET": "ADMIN_BUCKET",
    "USER_SPACE_BUCKET": "USER_SPACE_BUCKET",
    "SHARED_SPACE_BUCKET": "SHARED_SPACE_BUCKET",
    "ATHENA_WORKGROUP": "ATHENA_WORKGROUP",
}

_OPTIONAL_VARS = {
    "REGION": "AWS_REGION",
    "NOTIFICATIONS_QUEUE_URL": "NOTIFICATIONS_QUEUE_URL",
}

STATE_PAYLOAD_LIMIT_BYTES = 256 * 1024
CAUSE_MAX_CHARS = 32_768
CAUSE_RESERVATION_BYTES = 2 * CAUSE_MAX_CHARS

CATALOG_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

MAX_FIFO_KEY_CHARS = 128
FIFO_KEY_RE = re.compile(f"^[\x21-\x7e]{{1,{MAX_FIFO_KEY_CHARS}}}$")


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
    add to it: that set is a fleet-wide contract every plane's Terraform environment must supply,
    so a variable only one plane sets breaks every other plane. ``ARCHIVE_BUCKET`` was the first
    such value and this is what it uses instead.

    **Adding a name here is guarded across the fleet — which it never was before.** The guard
    whose name suggested otherwise read ``table-builder`` alone, and was retired with the suite
    cut that flattened the coverage floor. ``test_fleet_environment.py`` now computes, for every
    deployed function, the required names its import closure can actually reach, and refuses one
    its Terraform does not supply. So a name added to this set costs nothing on the planes that
    never read it, and reddens precisely the functions that would otherwise raise here at first
    access — which apply, ``update-function-code`` and the rest of this suite are blind to. A
    name nothing reads yet reddens nothing, so the declaration is pinned separately there.

    Exported rather than left private so a domain layer reaches for it instead of writing its
    own three-line ``os.environ`` check — one reader means one error sentence and one place the
    fail-fast behaviour is decided.

    **Being a FUNCTION is what lets a domain config stay import-safe, and the two callers use
    that differently on purpose.** ``arcommon.config.archive_bucket()`` calls it lazily, so a verb
    that never touches the archive bucket never pays for the variable — that is the shape to copy.
    ``shared-space-common/config.py`` binds ``PORTAL_ROLE_ARN`` at import instead, deliberately:
    every verb on that plane makes Lake Formation grants to it, so there is no invocation that
    would rather find out later, and a missing value surfaces as a named cold-start error rather
    than an opaque Lake Formation failure mid-request. The rule is therefore about the READER, not
    the shape: resolve at import only where the value is common to every verb that imports the
    module. Anywhere else, a constant resolved at import runs for every function that resolves the
    package whether or not it uses the value — and with one image, that is the whole fleet — while
    an unset variable crashes at COLD START, where no test and no deploy can see it.

    Args:
      name: The environment variable to read.

    Returns:
      Its value.

    Raises:
      RuntimeError: If the variable is unset or empty.
    """
    return _require(name)


if TYPE_CHECKING:
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
