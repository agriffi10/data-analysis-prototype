"""Unit tests for cpcommon.events.parse_sqs_request — the shared SQS-record parser.

Consolidates the ``_extract_record`` + ``_parse_request`` pair the three control-plane
validate-authorize verbs each carried; every guard is exercised so a regression in one
branch fails here rather than silently in one verb. Runnable under pytest or directly:
python3 test_events_cpcommon.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from cpcommon import events
from cpcommon.errors import TerminalError

REASON = "unauthorized"


def _sqs(body) -> list:
    """Wrap a body (str or object) the way an EventBridge Pipe forwards one SQS record."""
    return [{"body": body if isinstance(body, str) else json.dumps(body)}]


def test_parses_the_single_record_body_from_a_pipe_array():
    assert events.parse_sqs_request(_sqs({"action": "share", "n": 1}), reason=REASON) == {
        "action": "share",
        "n": 1,
    }


def test_accepts_a_bare_record_dict_too():
    assert events.parse_sqs_request({"body": json.dumps({"ok": True})}, reason=REASON) == {"ok": True}


@pytest.mark.parametrize(
    ("event", "detail"),
    [
        ([], "empty event"),
        ("not-a-batch", "unrecognised event shape"),
        ([{"noBody": 1}], "missing message body"),
        ([{"body": ""}], "missing message body"),
        ([{"body": "{not json"}], "body is not valid JSON"),
    ],
)
def test_malformed_inputs_raise_terminal_with_the_callers_reason(event, detail):
    with pytest.raises(TerminalError) as exc:
        events.parse_sqs_request(event, reason=REASON)
    assert exc.value.reason == REASON
    assert detail in exc.value.detail


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── SPEC-156 FR-005: the `exc=` factory path ────────────────────────────────
# shared-space-validate's own envelope parser was deleted in favour of this one, and the only
# thing that copy existed for was the exception TYPE its Step Function's Catch is written
# against. Nothing else in the tree asserts those four detail strings, so replacing them all
# with a constant left the whole suite green — these are that guard.


class _AuthorizationError(Exception):
    """Stands in for shared-space's own type: a one-argument factory, not a TerminalError."""


def test_the_exc_factory_carries_the_callers_type_on_every_envelope_failure():
    for event, detail in (
        ([], "empty event"),
        ("not-an-envelope", "unrecognised event shape"),
        ([{"body": ""}], "missing message body"),
        ([{}], "missing message body"),
    ):
        try:
            events.parse_sqs_request(event, reason=events.MALFORMED, exc=_AuthorizationError)
        except _AuthorizationError as exc:
            assert str(exc) == detail, f"{event!r} -> {str(exc)!r}"
        else:
            raise AssertionError(f"expected _AuthorizationError for {event!r}")


def test_the_exc_factory_reports_the_json_error_verbatim():
    try:
        events.parse_sqs_request(
            [{"body": "{oops"}], reason=events.MALFORMED, exc=_AuthorizationError
        )
    except _AuthorizationError as exc:
        # The interpolated decoder text IS the byte-identity this test is named for: dropping
        # `{err}` and keeping the prefix left the whole suite green.
        try:
            json.loads("{oops")
        except ValueError as expected:
            assert str(exc) == f"body is not valid JSON: {expected}"
    else:
        raise AssertionError("expected _AuthorizationError")


def test_the_default_path_is_untouched_by_the_new_parameter():
    """Every existing caller passes no `exc`, and must still get a TerminalError."""
    try:
        events.parse_sqs_request([], reason=events.MALFORMED)
    except TerminalError as exc:
        assert exc.reason == events.MALFORMED
        assert exc.detail == "empty event"
    else:
        raise AssertionError("expected TerminalError")


# ── timed_out_execution_input — the second door's read-back ──────────────────
#
# Consolidates the `_timed_out_input` copy that file-send and archive notify-failure each
# carried. Both doors kept a test that they are WIRED to this; the mechanism's own branches,
# and every way it can decline to answer, are exercised once here.


class _FakeSfn:
    """Step Functions, for the read-back the timeout door falls back to."""

    def __init__(self, described=None, error=None):
        self._described = described
        self._error = error
        self.calls = []

    def describe_execution(self, executionArn):
        self.calls.append(executionArn)
        if self._error:
            raise self._error
        return self._described or {}


@pytest.fixture
def sfn(monkeypatch):
    """Installs a fake Step Functions client and hands it back for assertions."""
    fake = _FakeSfn()
    monkeypatch.setattr(events.clients, "sfn", lambda: fake)
    return fake


def test_the_event_s_own_input_is_used_when_it_carries_one(sfn):
    """One API call per timeout at most, and none at all in the common case."""
    detail = {"input": '{"a":1}', "inputDetails": {"included": True}}

    assert events.timed_out_execution_input(detail) == '{"a":1}'
    assert sfn.calls == []


def test_the_input_is_read_back_when_eventbridge_dropped_it(sfn):
    """EventBridge caps an event at 256 KB and Step Functions drops the input rather than exceed
    it, so on a plane whose item cap approaches 200 KB the biggest requests — the ones that run
    long enough to time out — are exactly the ones the event alone cannot attribute."""
    sfn._described = {"input": '{"recovered":true}'}
    detail = {"inputDetails": {"included": False}, "executionArn": "arn:x"}

    assert events.timed_out_execution_input(detail) == '{"recovered":true}'
    assert sfn.calls == ["arn:x"]


def test_an_empty_input_is_read_back_even_though_included_is_true(sfn):
    """`included: true` with an empty string is still nothing to attribute — the read-back is
    gated on having usable input, not on the flag alone."""
    sfn._described = {"input": '{"recovered":true}'}

    assert events.timed_out_execution_input({"input": "", "executionArn": "arn:x"}) == (
        '{"recovered":true}'
    )
    assert sfn.calls == ["arn:x"]


@pytest.mark.parametrize(
    "detail",
    [
        "not-an-object",
        None,
        {"inputDetails": {"included": False}},
        {"inputDetails": {"included": False}, "executionArn": ""},
        {"inputDetails": {"included": False}, "executionArn": 42},
    ],
    ids=["detail-not-an-object", "no-detail", "no-arn", "blank-arn", "arn-not-a-string"],
)
def test_an_unattributable_detail_yields_no_input_rather_than_raising(detail, sfn):
    """A raise would be an async Lambda failure, and EventBridge RETRIES those — turning one
    unattributable event into three."""
    assert events.timed_out_execution_input(detail) == ""
    assert sfn.calls == []


def test_a_failed_read_back_yields_no_input_rather_than_raising(monkeypatch):
    """Same reason: the caller degrades to no addressee and logs it, which is a no-op. An
    AccessDenied here must not become three retried invocations."""
    fake = _FakeSfn(error=RuntimeError("AccessDenied"))
    monkeypatch.setattr(events.clients, "sfn", lambda: fake)

    assert events.timed_out_execution_input({"inputDetails": {"included": False}, "executionArn": "arn:x"}) == ""
    assert fake.calls == ["arn:x"]


def test_a_described_execution_with_no_usable_input_yields_no_input(monkeypatch):
    """DescribeExecution answered, but with nothing to parse — indistinguishable, for the
    caller's purposes, from not having asked."""
    monkeypatch.setattr(events.clients, "sfn", lambda: _FakeSfn(described={"input": None}))

    assert events.timed_out_execution_input({"inputDetails": {"included": False}, "executionArn": "arn:x"}) == ""
