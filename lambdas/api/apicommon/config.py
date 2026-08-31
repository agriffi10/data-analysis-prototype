"""The API's own configuration — the provider block, read from the environment.

Five values describe who issues the tokens this API verifies, and the verifier reads nothing
else about the provider. That is what makes swapping providers a configuration change instead
of a rewrite of every authorization path in the product.

**Resolved at first access, never at import.** A required value read at import time is a cold
start that fails before any handler runs, where no test and no deploy can see it — this fleet
has already lost a whole control plane that way. So the provider block is built by a FUNCTION
called per request, not by module constants: there is nothing here to resolve at import, which
is a stronger arrangement than resolving lazily and easier to keep true.

**A missing or unusable value is a server fault, not an authentication failure.** It raises
``ConfigError``, which the router answers with a 5xx. Answering 401 would tell the browser to
sign in again for a misconfiguration no user can fix, and the SPA would spend a token refresh
discovering that.

Attributes:
  MAX_STACK_BYTES: Ceiling on the stack trace attached to a failed span. A PLAIN CONSTANT with
    no environment behind it, deliberately: it is read where structured logging is configured,
    which happens at module scope, so an environment read here would be the cold-start failure
    this module's laziness exists to prevent. It is a ceiling and not a control, and what keeps a
    credential out of a log record is **that nothing is given one to emit** — a handler receives
    the verified principal and no bearer, and ``format_exception`` renders source lines rather
    than locals. There is no scrubber; a line here once said there was.
  ASSUME_ROLE_DURATION_SECONDS: How long a caller's assumed session lasts. Matches the enhanced
    flow's hour exactly, and it is a CEILING IN BOTH DIRECTIONS. Shortening it caps every
    presigned download link and every multipart upload window at the shorter value, a
    user-visible regression with no failing test. Lengthening it is refused by AWS: the function
    runs on an assumed-role session of its own, so this call is role chaining, which AWS caps at
    one hour and FAILS rather than clamps.
  CREDENTIAL_EXPIRY_MARGIN_SECONDS: How much life a cached credential must have left to be
    handed out again. DERIVED from the function's own timeout rather than chosen: the
    schedulable unit is one request, a request's whole life is bounded by that timeout, and the
    longest call it makes is subsumed by the same bound rather than omitted from it. Clock skew
    is not allowed for here and deliberately so — the single forced re-assume on an expired
    credential is that allowance, and an invented number would hide a wrong model.
  _OIDC_VARS: Attribute name to environment variable, for the provider block.
  _IDENTITY_VARS: Attribute name to environment variable, for the identity layer. Required like
    the provider block and for the same reason: a defaulted role ARN fails far from its cause,
    and a defaulted membership count silently drops every shared space a user is in.
"""

import json
import os

from cpcommon.auth import VerifierConfig
from cpcommon.jwks import API_FUNCTION_TIMEOUT_SECONDS

MAX_STACK_BYTES = 8192

ASSUME_ROLE_DURATION_SECONDS = 3600
CREDENTIAL_EXPIRY_MARGIN_SECONDS = API_FUNCTION_TIMEOUT_SECONDS

_OIDC_VARS = {
    "ISSUER": "OIDC_ISSUER",
    "AUDIENCE": "OIDC_AUDIENCE",
    "JWKS_URI": "OIDC_JWKS_URI",
    "USERNAME_CLAIM": "OIDC_USERNAME_CLAIM",
    "REQUIRED_CLAIMS": "OIDC_REQUIRED_CLAIMS",
}

_IDENTITY_VARS = {
    "PORTAL_ROLE_ARN": "PORTAL_ROLE_ARN",
    "PRINCIPAL_TAG_KEY": "PRINCIPAL_TAG_KEY",
    "MAX_SHARED_MEMBERSHIPS": "MAX_SHARED_MEMBERSHIPS",
    "SHARED_SPACE_BUCKET": "SHARED_SPACE_BUCKET",
    "USER_SPACE_BUCKET": "USER_SPACE_BUCKET",
    "ADMIN_BUCKET": "ADMIN_BUCKET",
    "ATHENA_WORKGROUP": "ATHENA_WORKGROUP",
}


class ConfigError(Exception):
    """A configuration value is missing or unusable, so this request cannot be served.

    Deliberately its own type rather than a ``RuntimeError``: the router has to tell it from
    every authentication failure, because the two get opposite HTTP statuses and opposite
    advice to the user.
    """


def _require(name: str) -> str:
    """Reads a required environment variable, failing loudly at the point of use.

    Args:
      name: The environment variable to read.

    Returns:
      Its value.

    Raises:
      ConfigError: If the variable is unset or empty. An unset repo variable renders as the
        empty string, so the two cases are the same case.
    """
    value = os.environ.get(name, "")
    if not value:
        raise ConfigError(f"required environment variable {name!r} is unset or empty")
    return value


def verifier_config() -> VerifierConfig:
    """Builds the provider parameters this API verifies tokens against.

    The single place in ``lambdas/api/`` that constructs one, so there is one answer to "which
    provider is this API verifying" and it is read from the environment rather than named in
    code.

    Args:
      None.

    Returns:
      The provider block.

    Raises:
      ConfigError: If any of the five is unset, or the required-claims document is not a JSON
        object. Failing here is the fail-closed direction: the alternative is verifying against
        a partially-configured provider, which succeeds for tokens it should refuse.
    """
    raw = _require(_OIDC_VARS["REQUIRED_CLAIMS"])
    try:
        required = json.loads(raw)
    except ValueError as exc:
        raise ConfigError(f"{_OIDC_VARS['REQUIRED_CLAIMS']} is not valid JSON") from exc
    if not isinstance(required, dict):
        raise ConfigError(f"{_OIDC_VARS['REQUIRED_CLAIMS']} is not a JSON object")

    return VerifierConfig(
        issuer=_require(_OIDC_VARS["ISSUER"]),
        audience=_require(_OIDC_VARS["AUDIENCE"]),
        jwks_uri=_require(_OIDC_VARS["JWKS_URI"]),
        username_claim=_require(_OIDC_VARS["USERNAME_CLAIM"]),
        required_claims={str(claim): str(value) for claim, value in required.items()},
    )


def portal_role_arn() -> str:
    """Returns the role the API assumes to act as its caller.

    Read per call rather than at import, like every other value here. It is the EXISTING portal
    role — the same ARN the Identity Pool's role attachment names — so every policy, bucket
    policy and Lake Formation grant that authorizes a browser session authorizes this one too.

    Args:
      None.

    Returns:
      The portal role's ARN.

    Raises:
      ConfigError: If the variable is unset or empty.
    """
    return _require(_IDENTITY_VARS["PORTAL_ROLE_ARN"])


def principal_tag_key() -> str:
    """Returns the session-tag key carrying the username.

    Configuration rather than a literal, and its agreement with the stamper is ASSERTED rather
    than structural: the Identity Pool's principal-tag map and two of the portal role's policy
    templates hard-code this name, and threading a variable through them would edit templates
    this spec is forbidden to touch. A wrong value here produces a session whose tags match no
    policy statement, which reads as a denial everywhere and names nothing.

    Args:
      None.

    Returns:
      The tag key.

    Raises:
      ConfigError: If the variable is unset or empty.
    """
    return _require(_IDENTITY_VARS["PRINCIPAL_TAG_KEY"])


def max_shared_memberships() -> int:
    """Returns how many membership slots a caller can carry.

    The same count that sizes the Cognito custom attributes, the Identity Pool's tag map and the
    portal role's shared-space policy. A hand-copied number here drops the slots above it, and
    dropping a slot leaves every personal feature working while shared spaces refuse — which
    presents as the propagation delay the product already documents.

    Args:
      None.

    Returns:
      The slot count.

    Raises:
      ConfigError: If the variable is unset, empty, or not a positive integer. A non-numeric
        value is the same case as an unset one: neither can size anything.
    """
    raw = _require(_IDENTITY_VARS["MAX_SHARED_MEMBERSHIPS"])
    try:
        slots = int(raw)
    except ValueError as exc:
        raise ConfigError(
            f"{_IDENTITY_VARS['MAX_SHARED_MEMBERSHIPS']} is not an integer"
        ) from exc
    if slots < 1:
        raise ConfigError(
            f"{_IDENTITY_VARS['MAX_SHARED_MEMBERSHIPS']} must be at least 1"
        )
    return slots


def user_space_bucket() -> str:
    """Returns the bucket holding every user's personal prefix.

    Args:
      None.

    Returns:
      The bucket name.

    Raises:
      ConfigError: If the variable is unset or empty.
    """
    return _require(_IDENTITY_VARS["USER_SPACE_BUCKET"])


def athena_workgroup() -> str:
    """Returns the workgroup every query this API starts runs in.

    Required, with no default, and the absent default is the point: an unset workgroup sends
    queries to Athena's ``primary``, whose results location is the account default. That is a
    write outside the isolation model, made by a query that otherwise succeeds — so it fails
    here, loudly, rather than there, silently.

    Args:
      None.

    Returns:
      The workgroup name.

    Raises:
      ConfigError: If the variable is unset or empty.
    """
    return _require(_IDENTITY_VARS["ATHENA_WORKGROUP"])


def admin_bucket() -> str:
    """Returns the bucket holding the control-plane documents this API reads.

    One document today, the membership index, and it is read on the execution role rather than
    the caller's — which is why the variable belongs to the identity block rather than to the two
    user-facing buckets beside it.

    Args:
      None.

    Returns:
      The bucket name.

    Raises:
      ConfigError: If the variable is unset or empty.
    """
    return _require(_IDENTITY_VARS["ADMIN_BUCKET"])


def shared_space_bucket() -> str:
    """Returns the bucket holding every shared space's prefix.

    Args:
      None.

    Returns:
      The bucket name.

    Raises:
      ConfigError: If the variable is unset or empty.
    """
    return _require(_IDENTITY_VARS["SHARED_SPACE_BUCKET"])


def queue_url(queue_id: str) -> str:
    """Returns the URL of one FIFO request queue.

    Read through the queue registry rather than from a name written here, so the eight variables
    have one home and a queue cannot be reached without being declared.

    Args:
      queue_id: The queue's registry id.

    Returns:
      The queue's URL.

    Raises:
      ConfigError: If the variable is unset or empty, or if no queue carries that id. An unset
        repo variable renders as the empty string, so an unconfigured queue is an operator fault
        answered as a fault, never as a refusal the caller could act on.
    """
    from .contract import QUEUES

    for queue in QUEUES:
        if queue.id == queue_id:
            return _require(queue.env_var)
    raise ConfigError(f"no queue is registered under {queue_id!r}")
