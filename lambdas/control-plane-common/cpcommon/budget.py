"""A wall-clock budget for optional calls that run after a verb's real work has succeeded.

A stall is not a fault: a call that never answers raises nothing for a swallow to catch, and it
holds the verb until its Lambda timeout, which fails a run whose outcome the user may already have
been told. The bounded client's timeouts limit each wait inside a call and not the call, so a worst
case derived from them is a model with gaps; this bounds the call itself. The long form, and why
an abandoned call is safe only for some calls, is ``lambdas/info/shared-layer.md``.

Attributes:
  CALL_CAP_SECONDS: How long one call may hold its caller — one attempt's connect and read bounds
    on a bounded client, which a call that answers normally finishes well inside. A slower call,
    or one the client would retry, is abandoned at the cost of what it was for.
"""

import contextvars
import threading
import time
from collections.abc import Callable

from . import clients

CALL_CAP_SECONDS = clients.BOUNDED_CONNECT_SECONDS + clients.BOUNDED_READ_SECONDS


class Budget:
    """A deadline for a run of optional calls, each of which may hold its caller for one cap.

    A loop that makes every call through one budget holds its caller for at most its seconds plus
    ``CALL_CAP_SECONDS``, whatever the client under it does: the deadline is checked before each
    call starts, and no call is waited on past the cap.
    """

    def __init__(self, seconds: float, label: str) -> None:
        """Starts the budget's clock.

        Args:
          seconds: How long calls may keep starting.
          label: What the calls are for, for the timeout's message.

        Returns:
          None.

        Raises:
          None.
        """
        self._deadline = time.monotonic() + seconds
        self._label = label

    def call[T](self, fn: Callable[[], T]) -> T:
        """Runs one call on a worker thread and waits for it no longer than the cap.

        An abandoned call is not cancelled: its thread finishes or fails on its own, in Lambda
        possibly during a later invocation of the same container. So only a call whose late
        completion is harmless belongs here — a read, or a write conditioned on what was read.

        Args:
          fn: The call, taking no arguments.

        Returns:
          What the call returns.

        Raises:
          TimeoutError: When the deadline has passed before the call starts, or the call is
            still running at the cap.
          Exception: Whatever the call raised, unchanged, so a compare-and-swap still reads a
            precondition failure as one.
        """
        if time.monotonic() > self._deadline:
            raise TimeoutError(f"{self._label} ran out of time")
        returned: list[T] = []
        raised: list[BaseException] = []
        context = contextvars.copy_context()

        def _run() -> None:
            """Runs the call in the caller's context and records how it ended.

            Args:
              None.

            Returns:
              None.

            Raises:
              None. The outcome is recorded for the caller to return or raise.
            """
            try:
                returned.append(context.run(fn))
            except BaseException as err:  # noqa: BLE001
                raised.append(err)

        worker = threading.Thread(target=_run, name="budget-call", daemon=True)
        worker.start()
        worker.join(CALL_CAP_SECONDS)
        if worker.is_alive():
            raise TimeoutError(f"{self._label}: a call ran past {CALL_CAP_SECONDS}s")
        if raised:
            raise raised[0]
        return returned[0]
