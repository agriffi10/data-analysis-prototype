"""Unit tests for cpcommon.errors — the transient-fault classifier (SPEC follow-up).

The classifier is the shared home for the logic four verbs used to copy. Runnable under
pytest or directly: python3 test_errors_cpcommon.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from cpcommon import errors


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


def test_canonical_set_covers_every_code_the_migrated_copies_needed():
    """The union the five migrated copies converged on. Pinned so a future trim can't
    silently re-introduce the incomplete-set bug (each old copy was a partial subset, so
    each verb previously failed permanently on transient codes it happened not to list)."""
    required = {
        # S3 (dq / tscommon-copy / infer-schema head probe / inspect listing)
        "SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable", "503", "500",
        # generic / Glue throttles
        "Throttling", "ThrottlingException", "TooManyRequestsException", "RequestLimitExceeded",
        # Athena 5xx (athena_run / tscommon-athena)
        "InternalServerException", "InternalErrorException", "ServiceUnavailableException",
    }
    missing = required - errors._TRANSIENT_CODES
    assert not missing, f"canonical _TRANSIENT_CODES dropped required codes: {sorted(missing)}"


def test_no_deterministic_code_is_transient():
    """The safety invariant behind the superset: retrying AccessDenied/NoSuchKey/403/404
    would just burn the SFN's attempts. None may ever leak into the transient set."""
    assert not (errors._TRANSIENT_CODES & {"AccessDenied", "NoSuchKey", "403", "404", "ValidationException"})


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
        # Mirrors botocore's ClientError.response shape; never mutated.
        response = {"Error": None}  # noqa: RUF012

    class _ResponseNotDict(Exception):
        response = "nope"

    for exc in (_NoResponse(), _ResponseNone(), _ErrorNone(), _ResponseNotDict(), RuntimeError("boom")):
        assert errors.error_code(exc) == ""
        assert errors.raise_if_transient(exc) is None


def test_a_code_shaped_MESSAGE_without_a_response_is_not_transient():
    """The vacuity guard, pinned: RuntimeError('ThrottlingException') has the code in its
    MESSAGE but no .response, so it is NOT transient. A test relying on message text would
    be exercising nothing — this asserts the classifier ignores the message."""
    assert errors.raise_if_transient(RuntimeError("ThrottlingException")) is None


# ── failure_reason: the decode that used to live (unsafely) in ASL ───────────
#
# Every case below is a real Step Functions error shape. The first is the only one the old
# `States.StringToJson($.error.Cause)` Pass state survived; the rest each raised an
# UNCATCHABLE States.Runtime, killing the execution before it could record or notify
# anything. Verified against the live service with TestState before this was written.


def test_a_terminal_error_decodes_to_the_verbs_own_reason_code():
    error = {
        "Error": "TerminalError",
        "Cause": json.dumps(
            {"errorMessage": "invalid_request: the envelope was malformed", "errorType": "TerminalError"}
        ),
    }

    assert errors.failure_reason(error) == "invalid_request"


@pytest.mark.parametrize(
    "label,error,expected",
    [
        # No Cause key at all. The OLD ASL failed with "JsonPath could not be found".
        ("States.Timeout", {"Error": "States.Timeout"}, "States.Timeout"),
        # A plain-sentence Cause. The OLD ASL failed with "Cannot convert String to Json".
        (
            "States.DataLimitExceeded",
            {"Error": "States.DataLimitExceeded", "Cause": "The state/task returned a result with a size exceeding the limit."},
            "States.DataLimitExceeded",
        ),
        (
            "Lambda.Unknown",
            {"Error": "Lambda.Unknown", "Cause": "The cause could not be determined."},
            "Lambda.Unknown",
        ),
        # Valid JSON, but not an object.
        ("array Cause", {"Error": "States.TaskFailed", "Cause": "[]"}, "States.TaskFailed"),
        # An object without the key we want.
        ("no errorMessage", {"Error": "States.TaskFailed", "Cause": '{"x": 1}'}, "States.TaskFailed"),
        # An errorMessage with no errorType — not a TerminalError, so not split.
        ("bare errorMessage", {"Error": "X", "Cause": '{"errorMessage": "boom"}'}, "X"),
        # A TerminalError with no colon in its message (constructed with no detail).
        (
            "TerminalError, no detail",
            {"Error": "TerminalError", "Cause": '{"errorMessage": "conflict", "errorType": "TerminalError"}'},
            "conflict",
        ),
        # An empty Cause string.
        ("empty Cause", {"Error": "X", "Cause": ""}, "X"),
    ],
)
def test_every_shape_that_used_to_kill_the_execution_now_yields_a_reason(label, error, expected):
    assert errors.failure_reason(error) == expected, label


@pytest.mark.parametrize(
    "label,error",
    [
        # An AWS message, whose FIRST colon falls in the middle of a sentence.
        (
            "botocore ClientError",
            {"Error": "ClientError", "Cause": json.dumps({
                "errorMessage": "An error occurred (AccessDeniedException) when calling the "
                                "CreateTable operation: Insufficient Lake Formation permission(s)",
                "errorType": "ClientError"})},
        ),
        # Exactly what raise_if_transient composes — every retry-exhausted throttle.
        (
            "TransientError",
            {"Error": "TransientError", "Cause": json.dumps({
                "errorMessage": "listing objects: transient SlowDown", "errorType": "TransientError"})},
        ),
    ],
)
def test_a_non_terminal_exception_never_has_its_prose_split_into_a_fake_reason(label, error):
    """The split reverses what TerminalError composed; applied to anything else it produces
    prose wearing a reason code's clothes. Both shapes here are routine, and the value is
    logged, recorded, and handed to notification code not yet written."""
    reason = errors.failure_reason(error)

    assert reason == error["Error"], label
    assert " " not in reason, f"{label}: a reason code should not be a sentence"


@pytest.mark.parametrize(
    "junk",
    [None, "a string", 42, [], {}, {"Cause": "orphan"}, {"Error": 5}, {"Error": None}],
)
def test_a_malformed_error_object_still_yields_something_mappable(junk):
    """It must NEVER raise and NEVER return empty: this runs on the failure path, where a
    second failure means the user hears nothing at all."""
    reason = errors.failure_reason(junk)

    assert isinstance(reason, str) and reason


def test_raw_engine_prose_never_leaks_into_the_reason():
    """SPEC-106 FR-008. A Cause carrying raw AWS text must not become user-facing wording —
    the caller gets a stable code to map, and the prose stays in the execution history."""
    prose = "HIVE_CURSOR_ERROR: Line too long in text file s3://bucket/key at offset 12345"
    error = {"Error": "States.TaskFailed", "Cause": prose}

    assert errors.failure_reason(error) == "States.TaskFailed"
    assert prose not in errors.failure_reason(error)


# ── bounded_detail: keeping one verbose engine message from breaking a Map ───


def test_a_short_detail_is_returned_unchanged():
    assert errors.bounded_detail("conflict on table orders") == "conflict on table orders"


def test_a_long_detail_is_truncated_and_says_so():
    """The detail becomes the exception message, which becomes the SFN error Cause, which
    table-share repeats PER RECIPIENT into the Map result. One verbose Athena reason can
    push that array past the 256 KB state-payload limit."""
    huge = "SYNTAX_ERROR: line 1:8: " + ("column_name_x, " * 500)

    bounded = errors.bounded_detail(huge)

    assert len(bounded) < len(huge)
    assert bounded.startswith("SYNTAX_ERROR: line 1:8:")   # the useful head survives
    assert "truncated" in bounded and "full text in logs" in bounded


def test_the_bound_holds_for_the_worst_case_athena_can_produce():
    """Step Functions caps a Cause at 32 KB; the bound must hold well inside it."""
    assert len(errors.bounded_detail("x" * 32768)) < errors.MAX_DETAIL_CHARS + 100


@pytest.mark.parametrize("value", [None, 42, ["a", "b"], {"k": "v"}])
def test_bounded_detail_never_raises_on_a_non_string(value):
    """It runs on the failure path, where a second failure means the user hears nothing."""
    assert isinstance(errors.bounded_detail(value), str)


def test_a_truncated_detail_still_decodes_to_its_reason_code():
    """Truncation must not break the OTHER half of this contract: failure_reason splits on
    the first colon, so the reason has to survive at the head of the message."""
    detail = errors.bounded_detail("SYNTAX_ERROR: " + "x" * 5000)
    error = {
        "Error": "TerminalError",
        "Cause": json.dumps(
            {"errorMessage": f"create_failed: {detail}", "errorType": "TerminalError"}
        ),
    }

    assert errors.failure_reason(error) == "create_failed"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
