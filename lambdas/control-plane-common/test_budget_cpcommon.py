"""cpcommon.budget — a deadline for optional calls, and a cap on how long any one is waited for."""

import contextvars
import threading
import time

import pytest
from cpcommon import budget

_TRACE = contextvars.ContextVar("trace", default=None)


def test_a_call_returns_its_value_in_the_callers_context():
    """The call runs on another thread, so the trace a log line carries must travel with it."""
    _TRACE.set("00-trace-01")
    calls = budget.Budget(5, "the index")

    assert calls.call(lambda: ("done", _TRACE.get())) == ("done", "00-trace-01")


def test_a_call_that_raises_raises_the_same_error():
    """A compare-and-swap reads a precondition failure off the error itself, so it must arrive
    unchanged rather than wrapped."""
    refused = RuntimeError("PreconditionFailed")
    calls = budget.Budget(5, "the index")

    def _refuse():
        raise refused

    with pytest.raises(RuntimeError) as caught:
        calls.call(_refuse)

    assert caught.value is refused


def test_a_call_still_running_at_the_cap_is_abandoned(monkeypatch):
    """A stall raises nothing, so the cap is the only thing that can end the wait."""
    monkeypatch.setattr(budget, "CALL_CAP_SECONDS", 0.05)
    released = threading.Event()
    calls = budget.Budget(5, "the index")
    started = time.monotonic()

    try:
        with pytest.raises(TimeoutError, match="ran past"):
            calls.call(lambda: released.wait(2))
        waited = time.monotonic() - started
    finally:
        released.set()

    assert waited < 1


def test_no_call_starts_once_the_deadline_has_passed(monkeypatch):
    clock = iter([0, 6])
    monkeypatch.setattr(budget.time, "monotonic", lambda: next(clock))
    started = []
    calls = budget.Budget(5, "the index")

    with pytest.raises(TimeoutError, match="ran out of time"):
        calls.call(lambda: started.append(True))

    assert started == []
