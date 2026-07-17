"""Unit tests for cpcommon.errors — the transient-fault classifier (SPEC follow-up).

The classifier is the shared home for the logic four verbs used to copy. Runnable under
pytest or directly: python3 test_errors_cpcommon.py.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402

from cpcommon import errors  # noqa: E402


class _FakeClientError(Exception):
    """A botocore-SHAPED error: carries ``.response["Error"]["Code"]``.

    The shape is the whole point — ``_error_code`` reads ``.response``, so a test that
    raised a plain exception with a code-shaped MESSAGE would exercise nothing (that exact
    trap shipped vacuous tests in the per-verb suites this consolidates)."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


@pytest.mark.parametrize("code", sorted(errors._TRANSIENT_CODES))
def test_every_transient_code_raises_TransientError(code):
    with pytest.raises(errors.TransientError):
        errors.raise_if_transient(_FakeClientError(code))


@pytest.mark.parametrize("code", ["AccessDenied", "NoSuchKey", "403", "404", "ValidationException"])
def test_a_deterministic_code_is_not_mapped(code):
    # Returns None (does not raise), so the caller re-raises the original unchanged.
    assert errors.raise_if_transient(_FakeClientError(code)) is None


def test_the_detail_is_carried_into_the_message():
    try:
        errors.raise_if_transient(_FakeClientError("SlowDown"), "list bkt/prefix")
    except errors.TransientError as err:
        assert "list bkt/prefix" in str(err)
        assert "SlowDown" in str(err)
        return
    raise AssertionError("expected TransientError")


def test_the_original_is_chained_as_the_cause():
    original = _FakeClientError("SlowDown")
    try:
        errors.raise_if_transient(original)
    except errors.TransientError as err:
        assert err.__cause__ is original
        return
    raise AssertionError("expected TransientError")


def test_error_code_is_defensive_against_malformed_responses():
    """A classifier must never itself throw while classifying. Each of these has no usable
    code and must yield "" (→ not transient), never an AttributeError/TypeError."""
    class _NoResponse(Exception):
        pass

    class _ResponseNone(Exception):
        response = None

    class _ErrorNone(Exception):
        response = {"Error": None}

    class _ResponseNotDict(Exception):
        response = "nope"

    for exc in (_NoResponse(), _ResponseNone(), _ErrorNone(), _ResponseNotDict(), RuntimeError("boom")):
        assert errors._error_code(exc) == ""
        assert errors.raise_if_transient(exc) is None


def test_a_code_shaped_MESSAGE_without_a_response_is_not_transient():
    """The vacuity guard, pinned: RuntimeError('ThrottlingException') has the code in its
    MESSAGE but no .response, so it is NOT transient. A test relying on message text would
    be exercising nothing — this asserts the classifier ignores the message."""
    assert errors.raise_if_transient(RuntimeError("ThrottlingException")) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
