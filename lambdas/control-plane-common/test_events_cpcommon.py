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
        assert str(exc).startswith("body is not valid JSON: ")
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
