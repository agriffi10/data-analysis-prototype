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


# Retryable AWS fault codes — the canonical superset the per-verb copies converged on
# (S3 SlowDown/RequestTimeout/500/503, Glue/generic throttles, Athena 5xx). A code NOT in
# here is deterministic (AccessDenied, NoSuchKey, 403/404): retrying it just burns the
# SFN's attempts on something that cannot resolve.
_TRANSIENT_CODES = frozenset({
    "Throttling",
    "ThrottlingException",
    "TooManyRequestsException",
    "RequestLimitExceeded",
    "SlowDown",
    "RequestTimeout",
    "InternalError",
    "InternalServerException",
    "InternalErrorException",
    "ServiceUnavailable",
    "ServiceUnavailableException",
    "500",
    "503",
})


def error_code(exc) -> str:
    """The botocore error code on ``exc``, or "" if it has none.

    Public because callers need it beyond transient classification too — e.g. matching a
    ``NoSuchKey``/404 to distinguish a folder from a file. The single canonical extractor
    (mirrors ``shared-space-common/casio.error_code``).

    Defensive at every level: a non-dict ``response`` or a ``None`` ``Error`` yields ""
    rather than raising — a classifier must never itself throw while classifying a fault.
    """
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return ""
    error = response.get("Error")
    if not isinstance(error, dict):
        return ""
    return str(error.get("Code", ""))


def raise_if_transient(exc, detail: str = "") -> None:
    """Re-raise a retryable AWS fault as ``TransientError``; return ``None`` otherwise.

    WHY VERBS NEED THIS, because the naive read is wrong: an exception raised inside a
    Lambda reaches Step Functions as its PYTHON CLASS NAME, so a bare botocore fault
    arrives as ``errorType: "ClientError"`` — a name no verb's Retry list names, so a
    one-off throttle would fail the whole request PERMANENTLY. Mapping it to
    ``TransientError`` (which the Retry lists DO name) is what actually gets it retried.
    A non-transient code falls through and the caller re-raises it unchanged, so a
    deterministic fault (AccessDenied) stays terminal instead of wasting retries.

    This helps ONLY under a state whose Retry ``ErrorEquals`` names ``TransientError`` —
    the code half and the state-machine half must move together.
    """
    code = error_code(exc)
    if code in _TRANSIENT_CODES:
        raise TransientError(f"{detail}: transient {code}" if detail else f"transient {code}") from exc
