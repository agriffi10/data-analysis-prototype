"""Shared, domain-extensible user-facing message registry (SPEC-106, SPEC-107 FR-005).

cpcommon holds the reason codes every control plane shares — access-denied, malformed
input, the unexpected-error catch-all — plus the machinery each domain layer uses to
add its own codes on top:

- ``register(domain_table)`` returns a domain-scoped ``Resolver`` (shared base table +
  that one domain's table) and marks every code in it valid.
- ``register_reasons(codes)`` marks codes valid for raise-time validation WITHOUT a
  wording resolver — the seam the existing tbcommon/tscommon message modules use, which
  keep their own bespoke ``failure_message`` formatters (SPEC-107 FR-002, unchanged
  behaviour) but must still make their reason codes valid TerminalError reasons.
- ``is_known_reason(code)`` is what ``cpcommon.errors.TerminalError`` checks at raise
  time (SPEC-107 FR-005): a mistyped reason fails loudly in dev/test instead of silently
  degrading to a generic message in production.

Registries are DOMAIN-SCOPED: tbcommon and tscommon each build their own resolver, so
both can define ``invalid_table_name`` with different wording without colliding — only a
domain re-defining a shared BASE code is a hard error, never a cross-domain clash (CI
imports both domain packages in one pytest process). Substitution uses ``str.replace``
on named ``{token}`` markers, never ``str.format``, so a literal brace in a table or
database name can't raise (SPEC-083 FR-005 / SPEC-106). Raw AWS/Athena text is never
placed in a message body — it stays in logs and the SFN record (SPEC-106 FR-008).
"""

from collections.abc import Iterable, Mapping

# ── Exported base reason-code constants (no bare literals at raise sites) ──────
UNAUTHORIZED = "unauthorized"
FORBIDDEN = "forbidden"
MALFORMED_EVENT = "malformed_event"
UNEXPECTED_ERROR = "unexpected_error"

# Shared base table: reason code -> friendly clause. Domain resolvers layer their own
# table on top of this. These are the generic codes any control plane can raise; a
# domain's own wording (e.g. tbcommon's "You don't have access to create a table here.")
# lives in its domain message module, not here.
BASE_MESSAGES: dict[str, str] = {
    UNAUTHORIZED: "you don't have access to do that.",
    FORBIDDEN: "you don't have access to do that.",
    MALFORMED_EVENT: "the request was malformed. Please try again.",
    UNEXPECTED_ERROR: "something went wrong. Please try again.",
}

BASE_REASONS = frozenset(BASE_MESSAGES)

# Global set of every valid reason code — seeded with the base codes, extended by each
# domain registration. ``TerminalError`` checks membership here at raise time (FR-005).
# A SET, so the same code registered by two domains (invalid_table_name in both
# tbcommon and tscommon) is fine: only a code's VALIDITY is global; the differing
# wording stays in each domain's own resolver.
_known_reasons: set[str] = set(BASE_REASONS)


def is_known_reason(reason: str) -> bool:
    """True iff ``reason`` is a registered base or domain reason code."""
    return reason in _known_reasons


class Resolver:
    """A domain-scoped reason -> friendly-text resolver (base table + one domain table)."""

    def __init__(self, domain_messages: Mapping[str, str]):
        overlap = set(domain_messages) & BASE_REASONS
        if overlap:
            raise ValueError(f"domain re-defines shared base reason codes: {sorted(overlap)}")
        self._table: dict[str, str] = {**BASE_MESSAGES, **dict(domain_messages)}
        _known_reasons.update(domain_messages)

    def body(self, reason: str, **tokens: str) -> str:
        """Return the friendly clause for ``reason`` with ``{token}`` markers replaced.

        An unknown reason falls back to the unexpected-error clause rather than leaking
        the code. Substitution is ``str.replace`` (never ``str.format``) so a literal
        brace in a substituted value can't raise.
        """
        text = self._table.get(reason, self._table[UNEXPECTED_ERROR])
        for name, value in tokens.items():
            text = text.replace("{" + name + "}", value or "")
        return text


def register(domain_messages: Mapping[str, str]) -> Resolver:
    """Build a domain resolver (shared base + ``domain_messages``) and register its codes."""
    return Resolver(domain_messages)


def register_reasons(reasons: Iterable[str]) -> None:
    """Mark ``reasons`` valid for raise-time TerminalError validation (no resolver).

    For domain modules that keep their own ``failure_message`` formatter but still need
    their reason codes to pass ``is_known_reason`` under FR-005 (tbcommon / tscommon).
    Idempotent; base codes already present are harmless to re-add.
    """
    _known_reasons.update(reasons)
