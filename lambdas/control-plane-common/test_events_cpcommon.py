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
