"""Error types that drive every control-plane Step Function's fail/retry routing.

Extracted to cpcommon by SPEC-107 so the table-builder, table-share (and the future
data-quality / file-converter) verbs all raise ONE ``TerminalError`` / ``TransientError``
type instead of per-layer copies.
"""

import json

from . import messages

#: What a Step Functions Catch parks under ``$.error``: the error NAME and, optionally, a
#: Cause. Only the name is guaranteed — see ``failure_reason``.
_SFN_ERROR = "Error"
_SFN_CAUSE = "Cause"


#: Longest raw-service text allowed into a TerminalError detail (see ``bounded_detail``).
MAX_DETAIL_CHARS = 500


def bounded_detail(text) -> str:
    """Truncate raw service text before it becomes a ``TerminalError`` detail.

    WHY A DETAIL'S LENGTH IS A PAYLOAD PROBLEM: the detail becomes the exception's message,
    which Lambda returns as the ``Cause`` of the Step Functions error, which the terminal
    states now carry as a raw object (PR #252). In table-share that object is repeated PER
    RECIPIENT into the Map's result array. Step Functions caps a state payload at 256 KB
    and a ``Cause`` at 32 KB — so ONE verbose reason repeated across recipients can breach
    the payload limit at as few as SEVEN of them, raising States.DataLimitExceeded on the
    Map and destroying every per-recipient outcome it exists to preserve.

    Athena's ``StateChangeReason`` is the realistic source: a syntax or Lake Formation error
    can echo a large fragment of the statement, and this arc generates wide DDL.

    NOTHING IS LOST — callers log the full text before truncating (``cpcommon.athena``
    does). The truncated head keeps what a reader actually uses: engine messages lead with
    the useful part.
    """
    text = str(text)
    if len(text) <= MAX_DETAIL_CHARS:
        return text
    return f"{text[:MAX_DETAIL_CHARS]}… [truncated {len(text) - MAX_DETAIL_CHARS} chars; full text in logs]"


def failure_reason(error) -> str:
    """Extract a stable reason code from a Step Functions error object, tolerating any shape.

    THIS EXISTS BECAUSE ASL CANNOT DO IT SAFELY, and trying anyway killed executions
    outright. The three control planes used to decode the Cause in a ``Pass`` state:

        "cause.$": "States.StringToJson($.error.Cause)"

    A Pass state cannot ``Catch``, and ``States.StringToJson`` raises ``States.Runtime`` on
    anything that is not a JSON string. Verified against the live service with TestState:

        Lambda TerminalError (JSON Cause)   -> SUCCEEDED
        States.Timeout (no Cause key)       -> States.Runtime  "JsonPath ... could not be found"
        States.DataLimitExceeded (prose)    -> States.Runtime  "Cannot convert String to Json"
        Lambda.Unknown (prose)              -> States.Runtime  "Cannot convert String to Json"

    Three of four realistic shapes killed the execution BEFORE the recorded-failure and
    notify states — so on precisely the failures a user most needs to hear about (a timeout,
    an oversized payload, a Lambda that died without a handled error) they were told nothing
    at all. Python can do this safely in a way ASL cannot, so the decode moved here and the
    machines now pass ``$.error`` through untouched.

    Returns the verb's own reason code when there is one (a ``TerminalError``'s
    ``"reason: detail"`` message decodes to its reason), otherwise the raw SFN error name —
    which is already a stable code like ``States.Timeout``. Never raises, and never returns
    empty: a caller mapping this to user-facing text always gets something to map, and an
    unmapped code falls through to the domain resolver's generic (SPEC-106).
    """
    if not isinstance(error, dict):
        return messages.UNEXPECTED_ERROR

    # str(), because a malformed error object must still yield something a resolver can map.
    name = str(error.get(_SFN_ERROR) or messages.UNEXPECTED_ERROR)
    cause = error.get(_SFN_CAUSE)
    if not isinstance(cause, str) or not cause:
        # No Cause at all — States.Timeout's shape. The error NAME is the reason.
        return name

    try:
        decoded = json.loads(cause)
    except ValueError:
        # A plain-sentence Cause (States.DataLimitExceeded, Lambda.Unknown). Its prose is
        # raw engine text and must never reach a user (SPEC-106 FR-008); it stays in the
        # execution history, and the caller gets the stable name to map instead.
        return name

    if not isinstance(decoded, dict):
        return name

    # THE SPLIT IS ONLY VALID FOR A TerminalError, so it is gated on the type rather than
    # applied to any errorMessage that happens to contain a colon. TerminalError composes
    # its message as f"{reason}: {detail}" from a REGISTERED, colon-free reason code, so
    # taking everything before the first colon reverses exactly what the raise site did.
    #
    # Every other exception's message is prose, and splitting it yields prose dressed up as
    # a reason code. Both of these are routine, not exotic:
    #
    #   ClientError  -> "An error occurred (AccessDeniedException) when calling the
    #                    CreateTable operation"      <- from the FIRST colon of an AWS message
    #   TransientError -> "listing objects"          <- what raise_if_transient composes
    #
    # Neither is a registered code, so a resolver would fall back to the generic anyway —
    # but the value is logged, recorded, and handed to SPEC-114/121 code not yet written,
    # and raw engine prose must never travel as if it were a code (SPEC-106 FR-008).
    if decoded.get("errorType") != TerminalError.__name__:
        return name

    message = decoded.get("errorMessage")
    if not isinstance(message, str) or not message:
        return name
    return message.split(":", 1)[0].strip() or name


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
        # BOUNDED HERE, not at the call sites, so the invariant cannot be forgotten. The
        # detail becomes this exception's message, which Lambda returns as the Step
        # Functions error Cause, which table-share repeats PER RECIPIENT into its Map
        # result — so one verbose raw-service string can push a state payload over 256 KB.
        # A review of the per-call-site version found it applied at ONE of at least three
        # sites that interpolate raw text (Athena's start-query branch, and copy.py's
        # "copy {src} -> {dest}" with two 1024-byte S3 keys), and both of the misses were
        # in the Map path, where a CORRELATED failure produces N identical oversized
        # Causes — the worst case. Callers that need the full text log it first.
        self.detail = bounded_detail(detail) if detail else detail
        super().__init__(f"{reason}: {self.detail}" if self.detail else reason)


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
