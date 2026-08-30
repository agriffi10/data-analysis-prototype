"""Shared, domain-extensible registry of user-facing failure messages.

cpcommon holds the reason codes every control plane shares — access-denied, malformed
input, the unexpected-error catch-all — plus the machinery each domain layer uses to add its
own codes on top.

Registries are domain-scoped, so two domains can define the same code with different wording
without colliding; only a domain re-defining a shared base code is a hard error. Only a
code's *validity* is global. Substitution uses ``str.replace`` on named markers, never
``str.format``, so a literal brace in a table or database name cannot raise. Raw AWS or
Athena text is never placed in a message body — it stays in logs and the SFN record.

A resolver renders a whole sentence, not only its tail. Every control plane composes the
same three parts — an access-denied short-circuit, a prefix naming the operation, and the
body for the reason — so those are resolver configuration rather than three hand-written
copies of one algorithm. The prefix and the access-denied clause are
marker-substituted templates like the bodies, because table-builder's verb varies per
request and reaches its access-denied clause too: a create-only line would tell a user they
cannot create a table they were trying to refresh.

Attributes:
  UNAUTHORIZED: Base reason code, exported so raise sites carry no bare literals.
  FORBIDDEN: Base reason code.
  MALFORMED_EVENT: Base reason code.
  UNEXPECTED_ERROR: Base reason code, and the fallback wording for an unknown reason.
  UNSUPPORTED_ASSURANCE: Base reason code for a principal kind no plane accepts — an
    ``identity.assurance`` outside ``cpcommon.actor.ACCEPTED_ASSURANCE``, or a delegated actor.
    A base code rather than a domain one because every plane refuses it identically and eight
    copies of one sentence is eight chances to disagree. Its wording names neither assurance,
    tokens nor delegation: the user cannot act on any of them, and the value rides the operator
    detail. Unreachable in production while the API mints only ``interactive``, which is the
    point — the day something mints a machine principal, every plane refuses it until that plane
    is deliberately widened.
  BASE_MESSAGES: The generic codes any control plane can raise, mapped to friendly clauses.
    A domain's own wording lives in its domain message module, not here.
  BASE_REASONS: The base codes as a frozen set.
  ACCESS_DENIED_REASONS: The base codes that mean "not allowed", which every plane
    short-circuits to a clause naming no resource — the request may not have got far enough
    to trust one.
  _MARKER_PATTERN: Marker discovery for blank-when-absent. Matches any brace group rather
    than lowercase words, because the surrounding code is camelCase and a camelCase marker
    would otherwise be missed and rendered raw to a user — the exact failure it exists to
    prevent.
"""

import re
from collections.abc import Iterable, Mapping

UNAUTHORIZED = "unauthorized"
FORBIDDEN = "forbidden"
MALFORMED_EVENT = "malformed_event"
UNEXPECTED_ERROR = "unexpected_error"
UNSUPPORTED_ASSURANCE = "unsupported_assurance"

BASE_MESSAGES: dict[str, str] = {
    UNAUTHORIZED: "you don't have access to do that.",
    FORBIDDEN: "you don't have access to do that.",
    MALFORMED_EVENT: "the request was malformed. Please try again.",
    UNEXPECTED_ERROR: "something went wrong. Please try again.",
    UNSUPPORTED_ASSURANCE: "the request could not be started. Please try again.",
}

BASE_REASONS = frozenset(BASE_MESSAGES)

ACCESS_DENIED_REASONS = frozenset({UNAUTHORIZED, FORBIDDEN})

_MARKER_PATTERN = re.compile(r"\{([^{}]*)\}")

_known_reasons: set[str] = set(BASE_REASONS)


def _fill(text: str, tokens: Mapping[str, str]) -> str:
    """Substitutes the supplied markers in a template.

    Args:
      text: The template.
      tokens: Marker names and their replacement values; a falsy value renders empty.

    Returns:
      The template with every supplied marker replaced.

    Raises:
      None.
    """
    for name, value in tokens.items():
        text = text.replace("{" + name + "}", value or "")
    return text


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

    Holds the shared base table layered under one domain's table, plus the wording that
    turns a body into the sentence the actor reads.

    The domain table is held by reference rather than copied, so a table edited after
    registration resolves through the edit — which is what lets a domain's tests probe their
    own wording without rebuilding the resolver.

    Attributes:
      markers: Every marker this resolver's wording declares — bodies, prefix and
        access-denied clause alike — discovered from that wording rather than listed, so a new
        one is blanked-when-absent automatically instead of shipping literally the first time
        a caller forgets it. The prefix is included precisely because it is the template most
        likely to grow one. Empty unless ``blank_unfilled``.

        Discovered once, at construction, while the domain table is held by reference: a body
        added later resolves and substitutes but is **not** blanked. That asymmetry is
        deliberate — it is what lets a domain's tests inject a probe body carrying a literal
        brace and assert it survives, which is the behaviour ``str.replace``-not-``str.format``
        exists to guarantee. Production tables are static, so nothing else depends on it.
    """

    def __init__(
        self,
        domain_messages: Mapping[str, str],
        *,
        prefix: str = "",
        access_denied: str = "",
        fallback: str | None = None,
        blank_unfilled: bool = False,
    ):
        """Builds the layered table and marks the domain's codes valid.

        Args:
          domain_messages: The domain's own reason code to friendly clause mapping.
          prefix: Optional marker-substituted template placed before the body, naming the
            operation that failed. Empty means ``message`` returns the body alone.
          access_denied: Optional marker-substituted template returned whole for an
            access-denied reason, naming no resource. Empty means those reasons resolve
            through the ordinary prefix-and-body path like any other.
          fallback: Wording for a reason absent from both tables. Defaults to the base
            unexpected-error clause; a domain that shipped a shorter one passes it here
            rather than losing it to the move.
          blank_unfilled: Whether ``body`` also blanks the declared markers no token filled.
            An absent token must leave a sentence rather than a literal brace group on the
            user's screen; off by default because a domain whose emitters always pass their
            tokens would rather see the marker in a test than a gap in a sentence.

        Returns:
          None.

        Raises:
          ValueError: If the domain re-defines a shared base reason code.
        """
        overlap = set(domain_messages) & BASE_REASONS
        if overlap:
            raise ValueError(f"domain re-defines shared base reason codes: {sorted(overlap)}")
        self._domain = domain_messages
        self._prefix = prefix
        self._access_denied = access_denied
        self._fallback = BASE_MESSAGES[UNEXPECTED_ERROR] if fallback is None else fallback
        self._blank_unfilled = blank_unfilled
        self.markers: frozenset[str] = (
            frozenset(
                _MARKER_PATTERN.findall(
                    " ".join([*domain_messages.values(), prefix, access_denied])
                )
            )
            if blank_unfilled
            else frozenset()
        )
        _known_reasons.update(domain_messages)

    def template(self, reason: str) -> str:
        """Returns the unsubstituted template a reason resolves to.

        The seam a domain's own tests use to ask what a reason renders from, now that a code
        may live in either the domain table or the shared base one.

        Args:
          reason: The reason code to resolve.

        Returns:
          The domain body, the base body, or this resolver's fallback wording.

        Raises:
          None.
        """
        if reason in self._domain:
            return self._domain[reason]
        if reason in BASE_MESSAGES:
            return BASE_MESSAGES[reason]
        return self._fallback

    def _blank(self, text: str) -> str:
        """Empties the declared markers no token filled, when the domain asked for it.

        Args:
          text: Already-substituted wording.

        Returns:
          The wording with any surviving declared marker removed, or unchanged when the
          domain wants an unfilled marker to remain visible.

        Raises:
          None.
        """
        if not self._blank_unfilled:
            return text
        for marker in self.markers:
            text = text.replace("{" + marker + "}", "")
        return text

    def body(self, reason: str, **tokens: str) -> str:
        """Returns the friendly clause for a reason with its markers substituted.

        An unknown reason falls back to this resolver's fallback wording rather than leaking
        the code.

        Args:
          reason: The reason code to resolve.
          **tokens: Marker names and their replacement values; a None value renders empty.

        Returns:
          The resolved clause.

        Raises:
          None.
        """
        return self._blank(_fill(self.template(reason), tokens))

    def message(self, reason: str, **tokens: str) -> str:
        """Returns the whole actor-facing sentence for a reason and its context.

        Args:
          reason: The reason code to resolve.
          **tokens: Marker values for the prefix, the access-denied clause and the body
            alike. A caller passes its trusted context last so a raise site's token cannot
            shadow it.

        Returns:
          The access-denied clause for an access-denied reason, otherwise the prefix
          followed by the body.

        Raises:
          None.
        """
        if self._access_denied and reason in ACCESS_DENIED_REASONS:
            return self._blank(_fill(self._access_denied, tokens))
        return self._blank(_fill(self._prefix, tokens)) + self.body(reason, **tokens)


def register(
    domain_messages: Mapping[str, str],
    *,
    prefix: str = "",
    access_denied: str = "",
    fallback: str | None = None,
    blank_unfilled: bool = False,
) -> Resolver:
    """Builds a domain resolver over the shared base table and registers its codes.

    Args:
      domain_messages: The domain's own reason code to friendly clause mapping.
      prefix: Optional marker-substituted template placed before the body.
      access_denied: Optional marker-substituted template for the access-denied reasons.
      fallback: Optional wording for a reason absent from both tables.
      blank_unfilled: Whether an unfilled declared marker renders empty rather than raw.

    Returns:
      A ``Resolver`` scoped to that domain.

    Raises:
      ValueError: If the domain re-defines a shared base reason code.
    """
    return Resolver(
        domain_messages,
        prefix=prefix,
        access_denied=access_denied,
        fallback=fallback,
        blank_unfilled=blank_unfilled,
    )


def register_reasons(reasons: Iterable[str]) -> None:
    """Marks reason codes valid for raise-time validation without building a resolver.

    The seam for a module that raises codes it does not own the wording for — ``cpcommon.glue``
    raises shape refusals that each plane words for itself. All three domain layers went
    through ``register`` instead. Idempotent; re-adding a base code is
    harmless.

    Args:
      reasons: The codes to mark valid.

    Returns:
      None.

    Raises:
      None.
    """
    _known_reasons.update(reasons)
