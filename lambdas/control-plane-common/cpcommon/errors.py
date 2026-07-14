"""Error types that drive every control-plane Step Function's fail/retry routing.

Extracted to cpcommon by SPEC-107 so the table-builder, table-share (and the future
data-quality / file-converter) verbs all raise ONE ``TerminalError`` / ``TransientError``
type instead of per-layer copies.
"""

from . import messages


class TerminalError(Exception):
    """A deterministic, non-retryable failure (bad auth, bad input, a name conflict).

    The Step Function's Catch routes it to the recorded-failure/Fail state with no side
    effects. ``reason`` is a stable machine code (e.g. ``unauthorized``) mapped to
    friendly notification text by the domain's messages resolver; ``detail`` is
    human/log context only (never surfaced to the user — SPEC-106 FR-008).

    ``reason`` MUST be a code registered with ``cpcommon.messages`` (the shared base
    codes plus every domain's registered codes). Constructing one with an unknown reason
    raises ``ValueError`` at the raise site (SPEC-107 FR-005) — a mistyped reason can
    never reach the user as a silent generic fallback, and the data-quality /
    file-converter arcs rely on this guarantee.
    """

    def __init__(self, reason, detail=""):
        if not messages.is_known_reason(reason):
            raise ValueError(
                f"unknown TerminalError reason {reason!r}: register it via the domain "
                "messages table (or cpcommon.messages base codes) before raising it"
            )
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class TransientError(Exception):
    """A retryable, non-deterministic failure (throttling, a 5xx).

    Raising it surfaces the type name to the Step Function, whose Retry on that name
    re-runs the whole verb — the opposite of ``TerminalError``, which the Catch records
    as a final outcome.
    """
