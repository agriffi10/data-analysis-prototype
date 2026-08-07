"""Error types that drive every control-plane Step Function's fail/retry routing.

Shared so the table-builder, table-share and data-quality verbs all raise one
``TerminalError``/``TransientError`` type instead of per-layer copies. Shared-space is not among
them — it raises its own ``AuthorizationError``, which is what ``AuthError`` below exists to
bridge.

Attributes:
  MAX_DETAIL_CHARS: Longest raw-service text allowed into a ``TerminalError`` detail.
  _SFN_ERROR: The key a Step Functions Catch parks the error NAME under. The only part
    guaranteed to be present — see ``failure_reason``.
  _SFN_CAUSE: The key it parks an optional Cause under.
  _TRANSIENT_CODES: The retryable AWS fault codes, fleet-wide. A code not in here is
    deterministic — AccessDenied, NoSuchKey, a 403 or 404 — and retrying it just burns the
    state machine's attempts on something that cannot resolve.
"""

import json

from . import messages

_SFN_ERROR = "Error"
_SFN_CAUSE = "Cause"


MAX_DETAIL_CHARS = 500


def bounded_detail(text) -> str:
    """Truncates raw service text before it becomes a TerminalError detail.

    A detail's length is a payload problem. It becomes the exception's message, which Lambda
    returns as the Step Functions error Cause, which table-share repeats per recipient into
    its Map result array. Step Functions caps a state payload at 256 KB and a Cause at
    32 KB, so one verbose reason repeated across as few as seven recipients raises
    States.DataLimitExceeded on the Map and destroys every per-recipient outcome it exists
    to preserve. Athena's ``StateChangeReason`` is the realistic source — it can echo a
    large fragment of a statement, and this arc generates wide DDL.

    Nothing is lost: callers log the full text before truncating, and engine messages lead
    with the useful part.

    Args:
      text: The raw text to bound; coerced with ``str``.

    Returns:
      The text unchanged if within the cap, otherwise its head plus a truncation note.

    Raises:
      None.
    """
    text = str(text)
    if len(text) <= MAX_DETAIL_CHARS:
        return text
    return f"{text[:MAX_DETAIL_CHARS]}… [truncated {len(text) - MAX_DETAIL_CHARS} chars; full text in logs]"


def failure_reason(error) -> str:
    """Extracts a stable reason code from a Step Functions error object, tolerating any shape.

    This is the only decoder, and it exists because ASL cannot do the job safely: decoding
    the Cause in a Pass state with ``States.StringToJson`` raises an uncatchable
    States.Runtime on three of the four realistic error shapes, killing the execution before
    the notify state. The machines now pass ``$.error`` through untouched. Evidence and the
    TestState results are in ``docs/lambda-rationale.md``.

    Returns the verb's own reason code when there is one, otherwise the raw SFN error name,
    which is already a stable code like ``States.Timeout``. The reason split is gated on the
    error type rather than applied to any message containing a colon, because
    ``TerminalError`` composes its message from a registered, colon-free code while every
    other exception's message is prose — and raw engine prose must never travel as if it
    were a code.

    Args:
      error: Whatever the Step Function parked under ``$.error``; any shape is tolerated.

    Returns:
      A non-empty reason code. An unmapped code falls through to the domain resolver's
      generic text.

    Raises:
      None. Never raises and never returns empty, so a caller mapping this to user-facing
      text always has something to map.
    """
    if not isinstance(error, dict):
        return messages.UNEXPECTED_ERROR

    name = str(error.get(_SFN_ERROR) or messages.UNEXPECTED_ERROR)
    cause = error.get(_SFN_CAUSE)
    if not isinstance(cause, str) or not cause:
        return name

    try:
        decoded = json.loads(cause)
    except ValueError:
        return name

    if not isinstance(decoded, dict):
        return name

    if decoded.get("errorType") != TerminalError.__name__:
        return name

    message = decoded.get("errorMessage")
    if not isinstance(message, str) or not message:
        return name
    return message.split(":", 1)[0].strip() or name


class TerminalError(Exception):
    """A deterministic, non-retryable failure — bad auth, bad input, a name conflict.

    The Step Function's Catch routes it to the recorded-failure/Fail state with no side
    effects. The reason must be a code registered with ``cpcommon.messages``; constructing
    one with an unknown reason raises ``ValueError`` at the raise site, so a mistyped reason
    can never reach the user as a silent generic fallback.

    ``detail`` and ``tokens`` are opposites, which is why they are separate fields: detail
    is for operators and may carry raw service text but never reaches a user, while tokens
    fill the ``{object}``/``{count}`` markers in the domain's message body and must never
    carry raw service text. Tokens exist because the notification is emitted by
    ``notifies_on_failure``, far from the raise site and holding only the exception —
    without them the markers render literally.

    Attributes:
      reason: The stable machine code, mapped to friendly text by the domain resolver.
      detail: Operator context, bounded by ``bounded_detail``. Bounded here rather than at
        the call sites so the invariant cannot be forgotten — a review of the per-call-site
        version found it applied at one of at least three sites interpolating raw text, and
        both misses were in the Map path where a correlated failure produces N identical
        oversized Causes.
      tokens: User-facing substitution values, copied and stringified. Copied rather than
        aliased so a caller mutating its dict cannot retroactively change the message a
        decorator renders; stringified so a message body's ``str.replace`` cannot fail on an
        integer count. Deliberately not part of the exception message: that message becomes the
        SFN Cause, which ``failure_reason`` splits on its first colon, and an S3 key or column
        name could carry a colon and corrupt the split. Nothing is lost by that, because tokens
        are never needed on the notify-failure path — the decorator emits first and wins the
        FIFO dedup.
    """

    def __init__(self, reason, detail="", tokens=None):
        """Validates the reason, bounds the detail and composes the exception message.

        Args:
          reason: A code registered with ``cpcommon.messages``.
          detail: Optional operator context; truncated to ``MAX_DETAIL_CHARS``.
          tokens: Optional mapping of message-body markers to their values.

        Returns:
          None.

        Raises:
          ValueError: If the reason is not registered.
        """
        if not messages.is_known_reason(reason):
            raise ValueError(
                f"unknown TerminalError reason {reason!r}: register it via the domain "
                "messages table (or cpcommon.messages base codes) before raising it"
            )
        self.reason = reason
        self.detail = bounded_detail(detail) if detail else detail
        self.tokens = {str(k): str(v) for k, v in tokens.items()} if tokens else {}
        super().__init__(f"{reason}: {self.detail}" if self.detail else reason)


class TransientError(Exception):
    """A retryable, non-deterministic failure such as throttling or a 5xx.

    Raising it surfaces the type name to the Step Function, whose Retry on that name re-runs
    the whole verb — the opposite of ``TerminalError``, which the Catch records as a final
    outcome.
    """


class AuthError(Exception):
    """An ID token that could not be verified. Internal — callers translate it.

    Two control planes verify the same token with the same JWKS logic and then raise
    different exception types on failure: table-builder, table-share and data-quality raise
    ``TerminalError("unauthorized", …)``, while shared-space raises its own
    ``AuthorizationError``. Sharing the verification meant giving it an exception seam rather
    than picking a winner, so ``cpcommon.auth.verify_id_token`` raises this and each caller
    maps it to its own model.

    It should never reach a Step Function: a verb that lets one escape has skipped its
    translation and would surface a name no Catch or Retry list mentions. Its detail carries
    the same wording the two models raised before they shared this path.
    """


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
    "InternalServiceException",
    "OperationTimeoutException",
})


def error_code(exc) -> str:
    """Extracts the botocore error code from an exception, or "" if it has none.

    The single canonical extractor. Public because callers need it beyond transient
    classification — matching a NoSuchKey or 404 to distinguish a folder from a file, for
    instance. Defensive at every level: a non-dict response or a None Error yields "" rather
    than raising, because a classifier must never itself throw while classifying a fault.

    Args:
      exc: Any exception, botocore or not.

    Returns:
      The error code, or "" when there is none.

    Raises:
      None.
    """
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return ""
    error = response.get("Error")
    if not isinstance(error, dict):
        return ""
    return str(error.get("Code", ""))


def raise_if_transient(exc, detail: str = "") -> None:
    """Re-raises a retryable AWS fault as TransientError, and returns otherwise.

    Verbs need this because the naive read is wrong: an exception raised inside a Lambda
    reaches Step Functions as its Python class name, so a bare botocore fault arrives as
    ``ClientError`` — a name no verb's Retry list names, and a one-off throttle would fail
    the whole request permanently. Mapping it to ``TransientError``, which the Retry lists do
    name, is what actually gets it retried. A non-transient code falls through so a
    deterministic fault such as AccessDenied stays terminal instead of wasting retries.

    This helps only under a state whose Retry ``ErrorEquals`` names ``TransientError`` — the
    code half and the state-machine half must move together. The transient set is the
    canonical superset the per-verb copies converged on; a code not in it is deterministic.
    Glue's ``InternalServiceException`` and ``OperationTimeoutException`` are included and miss
    the generic spellings by a word — safe to widen the shared set with them because no other
    AWS service raises either code.

    Args:
      exc: The exception to classify.
      detail: Optional context prefixed to the transient error's message.

    Returns:
      None, when the fault is not transient.

    Raises:
      TransientError: When the fault's code is retryable.
    """
    code = error_code(exc)
    if code in _TRANSIENT_CODES:
        raise TransientError(f"{detail}: transient {code}" if detail else f"transient {code}") from exc
