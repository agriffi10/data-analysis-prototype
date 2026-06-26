"""Unit tests for the shared-space provisioner skeleton (SPEC-050). Written to run
under pytest *or* as a plain script (`python3 test_shared_space_provisioner.py`)
since the JS CI does not run a Python interpreter — these are for local verification.

SPEC-050 is foundation only: the handler dispatches/echoes and must NEVER raise on a
malformed message (it would otherwise retry into the DLQ during early testing). Real
per-action behavior arrives in SPEC-051+.
"""

import json

from shared_space_provisioner import handler


def _record(action="create", **payload):
    body = {"action": action, **payload}
    return {"body": json.dumps(body)}


def test_echoes_action_from_single_record_batch():
    result = handler([_record(action="create", name="team_alpha")], None)
    assert result == {"status": "dispatched", "count": 1, "actions": ["create"]}


def test_accepts_bare_dict_record():
    result = handler(_record(action="delete", name="team_alpha"), None)
    assert result["count"] == 1
    assert result["actions"] == ["delete"]


def test_malformed_body_does_not_raise():
    # Garbage body -> action is None, no exception (so it is not retried to the DLQ).
    result = handler([{"body": "not json"}], None)
    assert result == {"status": "dispatched", "count": 1, "actions": [None]}


def test_empty_event_is_safe():
    assert handler([], None) == {"status": "dispatched", "count": 0, "actions": []}


def test_unexpected_event_type_is_safe():
    assert handler(None, None) == {"status": "dispatched", "count": 0, "actions": []}


if __name__ == "__main__":
    test_echoes_action_from_single_record_batch()
    test_accepts_bare_dict_record()
    test_malformed_body_does_not_raise()
    test_empty_event_is_safe()
    test_unexpected_event_type_is_safe()
    print("All shared_space_provisioner tests passed.")
