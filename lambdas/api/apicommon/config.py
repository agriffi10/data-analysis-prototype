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
    this module's laziness exists to prevent. It is a ceiling and not a control — what keeps a
    credential out of a log record is the scrub, never this number.
  _OIDC_VARS: Attribute name to environment variable, for the provider block.
"""

import json
import os

from cpcommon.auth import VerifierConfig

MAX_STACK_BYTES = 8192

_OIDC_VARS = {
    "ISSUER": "OIDC_ISSUER",
    "AUDIENCE": "OIDC_AUDIENCE",
    "JWKS_URI": "OIDC_JWKS_URI",
    "USERNAME_CLAIM": "OIDC_USERNAME_CLAIM",
    "REQUIRED_CLAIMS": "OIDC_REQUIRED_CLAIMS",
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
