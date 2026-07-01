"""Terminal-error type for the table-builder control plane (SPEC-067).

A ``TerminalError`` is a deterministic, non-retryable failure (bad auth, bad input,
a table that already exists, …). Raising it lets the Step Function's ``Catch`` route
to the recorded-failure/Fail state with no side effects. ``reason`` is a STABLE
machine code (e.g. ``unauthorized``, ``invalid_table_name``) that SPEC-072 maps to a
user-facing notification; ``detail`` is human/log context only.
"""


class TerminalError(Exception):
    def __init__(self, reason, detail=""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class TransientError(Exception):
    """A retryable, non-deterministic failure (Athena/S3 throttling, a 5xx). Raising
    it (rather than a ``TerminalError``) surfaces the exception TYPE name
    ``TransientError`` to the Step Function, whose ``Retry`` on that name re-runs the
    whole verb — the opposite of ``TerminalError``, which the ``Catch`` records as a
    final outcome. Used by ``execute-ddl``'s Athena start+poll (SPEC-070)."""
