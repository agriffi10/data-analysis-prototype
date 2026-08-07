"""Shared, domain-extensible registry of user-facing failure messages.

cpcommon holds the reason codes every control plane shares — access-denied, malformed
input, the unexpected-error catch-all — plus the machinery each domain layer uses to add its
own codes on top.

Registries are domain-scoped, so two domains can define the same code with different wording
without colliding; only a domain re-defining a shared base code is a hard error. Only a
code's *validity* is global. Substitution uses ``str.replace`` on named markers, never
``str.format``, so a literal brace in a table or database name cannot raise. Raw AWS or
Athena text is never placed in a message body — it stays in logs and the SFN record.

Attributes:
  UNAUTHORIZED: Base reason code, exported so raise sites carry no bare literals.
  FORBIDDEN: Base reason code.
  MALFORMED_EVENT: Base reason code.
  UNEXPECTED_ERROR: Base reason code, and the fallback wording for an unknown reason.
  BASE_MESSAGES: The generic codes any control plane can raise, mapped to friendly clauses.
    A domain's own wording lives in its domain message module, not here.
  BASE_REASONS: The base codes as a frozen set.
"""

from collections.abc import Iterable, Mapping

UNAUTHORIZED = "unauthorized"
FORBIDDEN = "forbidden"
MALFORMED_EVENT = "malformed_event"
UNEXPECTED_ERROR = "unexpected_error"

BASE_MESSAGES: dict[str, str] = {
    UNAUTHORIZED: "you don't have access to do that.",
    FORBIDDEN: "you don't have access to do that.",
    MALFORMED_EVENT: "the request was malformed. Please try again.",
    UNEXPECTED_ERROR: "something went wrong. Please try again.",
}

BASE_REASONS = frozenset(BASE_MESSAGES)

_known_reasons: set[str] = set(BASE_REASONS)


def is_known_reason(reason: str) -> bool:
    """Reports whether a reason code has been registered as a base or domain code.

    This is what ``cpcommon.errors.TerminalError`` checks at raise time, so a mistyped
    reason fails loudly in dev and test instead of silently degrading to a generic message
    in production.

    Args:
      reason: The code to check.

    Returns:
      True if the code is registered.

    Raises:
      None.
    """
    return reason in _known_reasons


class Resolver:
    """A domain-scoped resolver from reason code to friendly text.

    Holds the shared base table layered under one domain's table.
    """

    def __init__(self, domain_messages: Mapping[str, str]):
        """Builds the layered table and marks the domain's codes valid.

        Args:
          domain_messages: The domain's own reason code to friendly clause mapping.

        Returns:
          None.

        Raises:
          ValueError: If the domain re-defines a shared base reason code.
        """
        overlap = set(domain_messages) & BASE_REASONS
        if overlap:
            raise ValueError(f"domain re-defines shared base reason codes: {sorted(overlap)}")
        self._table: dict[str, str] = {**BASE_MESSAGES, **dict(domain_messages)}
        _known_reasons.update(domain_messages)

    def body(self, reason: str, **tokens: str) -> str:
        """Returns the friendly clause for a reason with its markers substituted.

        An unknown reason falls back to the unexpected-error clause rather than leaking the
        code.

        Args:
          reason: The reason code to resolve.
          **tokens: Marker names and their replacement values; a None value renders empty.

        Returns:
          The resolved clause.

        Raises:
          None.
        """
        text = self._table.get(reason, self._table[UNEXPECTED_ERROR])
        for name, value in tokens.items():
            text = text.replace("{" + name + "}", value or "")
        return text


def register(domain_messages: Mapping[str, str]) -> Resolver:
    """Builds a domain resolver over the shared base table and registers its codes.

    Args:
      domain_messages: The domain's own reason code to friendly clause mapping.

    Returns:
      A ``Resolver`` scoped to that domain.

    Raises:
      ValueError: If the domain re-defines a shared base reason code.
    """
    return Resolver(domain_messages)


def register_reasons(reasons: Iterable[str]) -> None:
    """Marks reason codes valid for raise-time validation without building a resolver.

    The seam for domain modules that keep their own bespoke ``failure_message`` formatter
    but still need their codes to pass ``is_known_reason``. Idempotent; re-adding a base
    code is harmless.

    Args:
      reasons: The codes to mark valid.

    Returns:
      None.

    Raises:
      None.
    """
    _known_reasons.update(reasons)
