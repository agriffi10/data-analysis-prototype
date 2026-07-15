"""User-facing data-quality notification text + reason codes (SPEC-109 seeds; SPEC-114 fills).

Registers this domain's reason codes with ``cpcommon.messages`` (SPEC-107 FR-005): that
gives a DOMAIN-SCOPED resolver over the shared base table, and — the part that matters at
every raise site — makes each code a VALID ``TerminalError`` reason. Raising a
``TerminalError`` with a code that isn't registered here is a ``ValueError`` AT THE RAISE
SITE, so a typo can never reach a user as a silent generic message.

Reason codes are EXPORTED CONSTANTS: no bare string literals at raise sites.

Raw AWS/Athena/Python text never reaches a notification body (SPEC-106) — it stays in
CloudWatch and the SFN execution history. SPEC-114 adds the verdict/top-issues wording and
the emitters; this module carries only what SPEC-109's validate-authorize raises.
"""

from cpcommon import messages as _cpmessages

# ── Exported reason-code constants ───────────────────────────────────────────
# `unauthorized` / `forbidden` are cpcommon BASE codes, re-exported so verb code has ONE
# import for every reason it raises. They must NOT be re-declared in _BODIES below — the
# resolver hard-errors on a domain re-defining a shared base code.
UNAUTHORIZED = _cpmessages.UNAUTHORIZED
FORBIDDEN = _cpmessages.FORBIDDEN

#: A malformed envelope: missing/renamed/wrong-typed field, or no requestId (SPEC-109 FR-001).
INVALID_REQUEST = "invalid_request"

# reason -> the clause after 'Couldn't check data quality[ on "{location}"]: '.
_BODIES = {
    INVALID_REQUEST: "the request was malformed. Please try again.",
}

#: Domain-scoped resolver (shared base table + the domain table above), SPEC-107 FR-005.
resolver = _cpmessages.register(_BODIES)


def failure_message(reason: str, location: str = "") -> str:
    """Map a terminal reason (+ context) to the message the actor sees.

    An unknown reason falls back to the shared generic rather than leaking the code, and no
    raw AWS/Athena text is ever interpolated (SPEC-106 FR-008). SPEC-114 extends this with
    the verdict/top-issues wording.
    """
    if reason in (UNAUTHORIZED, FORBIDDEN):
        return "You don't have access to check data quality there."
    where = f' on "{location}"' if location else ""
    return f"Couldn't check data quality{where}: {resolver.body(reason)}"
