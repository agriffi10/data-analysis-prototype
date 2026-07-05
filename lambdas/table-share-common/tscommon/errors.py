"""Error types that drive the table-share Step Function's fail/retry routing."""


class TerminalError(Exception):
    """A deterministic, non-retryable failure (bad auth, bad input, name conflict).

    The Step Function's Catch routes it to the recorded-failure state with no side
    effects. ``reason`` is a stable machine code (e.g. ``unauthorized``) that maps to
    a user-facing notification (SPEC-094); ``detail`` is human/log context only.
    """

    def __init__(self, reason, detail=""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class TransientError(Exception):
    """A retryable, non-deterministic failure (throttling, a 5xx).

    Raising it surfaces the type name to the Step Function, whose Retry on that name
    re-runs the whole verb — the opposite of ``TerminalError``, which the Catch
    records as a final outcome.
    """
