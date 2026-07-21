"""Unit tests for dqcommon.notify — the data-quality outcome emitters (SPEC-114).

Runnable under pytest or directly: python3 test_notify_dqcommon.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon import clients, config  # noqa: E402
from cpcommon.errors import TerminalError, TransientError  # noqa: E402
from dqcommon import messages, notify  # noqa: E402

QUEUE = "https://sqs.test/dat-prod-notifications-requests.fifo"


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}

    def bodies(self):
        return [json.loads(c["MessageBody"]) for c in self.calls]


def _arm():
    config.NOTIFICATIONS_QUEUE_URL = QUEUE
    fake = _FakeSqs()
    clients._sqs = fake
    return fake


def _personal(name="alice"):
    return {"kind": "personal", "bucket": "dat-prod-user-space", "prefix": f"{name}/"}


def _shared(name="finance"):
    return {"kind": "shared", "bucket": "dat-prod-shared-space", "prefix": f"{name}/"}


def _summary(**over):
    event = {
        "requestId": "r-1",
        "actor": "alice",
        "location": "alice/sales",
        "space": _personal(),
        "verdict": "clean",
        "topIssues": [],
        "hasApproximateFigures": True,
        "hasIncompleteFigures": False,
    }
    event.update(over)
    return event


# ── report_link: the SPEC-113 resolution precedence, from the producer side ───


def test_link_for_a_personal_check_carries_the_space_segment():
    """A link without the space cannot locate a report (FR-001)."""
    assert notify.report_link("alice", _personal(), "r-1") == "/data-quality/alice/r-1"


def test_link_for_a_shared_space_check_resolves():
    """The criterion that a shared-space link is BUILDABLE at all (FR-001)."""
    assert notify.report_link("alice", _shared("finance"), "r-1") == "/data-quality/finance/r-1"


def test_no_link_when_a_shared_space_is_named_like_the_actor():
    """THE PRECEDENCE RULE. The report view resolves a segment equal to the viewer's own
    username as PERSONAL and never consults shared names for it
    (useDataQualityReport.resolveSpace). So this link would send alice to her own personal
    space and 404 — a permanent not-found, which FR-001 says is worse than no link."""
    assert notify.report_link("alice", _shared("alice"), "r-1") is None


def test_a_personal_space_that_is_not_the_actors_own_mints_no_link():
    """The mirror case: the view would resolve that segment as a shared name, not personal."""
    assert notify.report_link("alice", _personal("bob"), "r-1") is None


def test_no_link_without_the_pieces_to_build_one():
    assert notify.report_link("alice", {}, "r-1") is None
    assert notify.report_link("alice", _personal(), "") is None
    assert notify.report_link("", _personal(), "r-1") is None


def test_link_refuses_segments_that_could_change_the_url():
    """Traversal or a query string must never reach a user's inbox as a clickable path."""
    assert notify.report_link("alice", {"kind": "personal", "prefix": "../../etc/"}, "r-1") is None
    assert notify.report_link("alice", _personal(), "r-1?x=1") is None


# ── Success notification (FR-001) ────────────────────────────────────────────


def test_success_notification_is_one_message_to_the_actor_with_the_link():
    fake = _arm()
    notify.emit_completed(_summary())
    assert len(fake.calls) == 1
    body = fake.bodies()[0]
    assert body["action"] == "create"
    assert body["username"] == "alice"
    assert body["link"] == "/data-quality/alice/r-1"
    assert fake.calls[0]["MessageGroupId"] == "alice"
    assert fake.calls[0]["MessageDeduplicationId"] == "r-1:completed"


def test_success_notification_for_a_shared_space_links_with_the_space():
    fake = _arm()
    notify.emit_completed(_summary(space=_shared("finance"), location="finance/raw"))
    assert fake.bodies()[0]["link"] == "/data-quality/finance/r-1"


def test_success_notification_omits_the_link_when_none_can_be_built():
    """The message must still be emitted — the user hears the verdict either way."""
    fake = _arm()
    notify.emit_completed(_summary(space=_shared("alice")))
    assert len(fake.calls) == 1
    assert "link" not in fake.bodies()[0]


def test_an_approximate_clean_result_is_never_reported_unqualified():
    """FR-001's core promise: an unqualified 'clean' over a sampled scan is a lie."""
    fake = _arm()
    notify.emit_completed(_summary(verdict="clean", hasApproximateFigures=True))
    message = fake.bodies()[0]["message"]
    assert "no issues found" in message
    assert "estimates" in message


def test_a_skipped_or_failed_check_says_something_is_missing():
    """hasIncompleteFigures is the flag that VARIES, so it gets the real warning."""
    fake = _arm()
    notify.emit_completed(_summary(hasIncompleteFigures=True))
    assert "couldn't be completed" in fake.bodies()[0]["message"]


def test_issues_found_names_the_top_issues_and_the_total():
    fake = _arm()
    notify.emit_completed(
        _summary(verdict="issues_found", topIssues=["`a` has 3 empty values", "12 duplicate rows"])
    )
    message = fake.bodies()[0]["message"]
    assert "2 issues found" in message
    assert "`a` has 3 empty values" in message
    assert "12 duplicate rows" in message


def test_a_long_issue_list_is_truncated_but_the_count_is_not():
    """Nothing is hidden: the message names two and states how many there are."""
    fake = _arm()
    notify.emit_completed(_summary(verdict="issues_found", topIssues=[f"issue {i}" for i in range(5)]))
    message = fake.bodies()[0]["message"]
    assert "5 issues found" in message
    assert "(and 3 more)" in message
    assert "issue 4" not in message


def test_success_message_carries_no_report_document():
    """The findings stay in the report; the notification carries the summary only."""
    fake = _arm()
    notify.emit_completed(_summary(exact={"rowCount": 5}, approximate={"encoding": {}}))
    assert "rowCount" not in fake.bodies()[0]["message"]


# ── Failure notification (FR-002) ────────────────────────────────────────────


def test_failure_notification_fills_the_per_request_tokens():
    """The FR-002 criteria that a message NAMES the offending file / count / key."""
    fake = _arm()
    err = TerminalError(messages.UNREADABLE_HEADER, "boom", tokens={"object": "alice/s/bad.csv"})
    notify.emit_failure({"actor": "alice", "location": "alice/s", "requestId": "r-1"}, err)
    message = fake.bodies()[0]["message"]
    assert "alice/s/bad.csv" in message
    assert "{object}" not in message


def test_failure_notification_never_carries_the_raw_detail():
    """err.detail is raw service text: logs and the SFN record only (SPEC-106 FR-008)."""
    fake = _arm()
    err = TerminalError(
        messages.QUERY_FAILED,
        "SYNTAX_ERROR: line 1:8: Column 'x' cannot be resolved [serde: org.apache.hadoop]",
    )
    notify.emit_failure({"actor": "alice", "location": "alice/s", "requestId": "r-1"}, err)
    message = fake.bodies()[0]["message"]
    assert "SYNTAX_ERROR" not in message
    assert "org.apache.hadoop" not in message


def test_failure_before_the_actor_is_bound_notifies_nobody():
    """No trustworthy recipient — a logged no-op, not a message to a guessed inbox."""
    fake = _arm()
    notify.emit_failure({"location": "alice/s", "requestId": "r-1"}, TerminalError(messages.QUERY_FAILED))
    assert fake.calls == []


def test_emit_unexpected_tolerates_a_non_dict_event():
    """validate-authorize's input is the raw SQS ARRAY; a failure there must not crash."""
    fake = _arm()
    notify.emit_unexpected([{"body": "{}"}], "validate")
    assert fake.calls == []


# ── Dedup: the FR-004 collapse ───────────────────────────────────────────────


def test_decorator_and_notify_failure_share_one_dedup_id():
    """THE COLLAPSE. Both paths emit for the same failure; identical ids make SQS FIFO keep
    one. A per-verb step token would make these differ and the user would get two."""
    fake = _arm()
    err = TerminalError(messages.QUERY_FAILED, "boom")
    notify.emit_failure({"actor": "alice", "requestId": "r-1", "location": "l"}, err)
    decorator_id = fake.calls[0]["MessageDeduplicationId"]
    # What dq_notify_failure builds, from the same request id.
    assert decorator_id == f"r-1:{notify.FAILURE_STEP}"
    assert notify.FAILURE_STEP != notify.SUCCESS_STEP


def test_every_verb_step_produces_the_same_failure_dedup_id():
    """One token per OUTCOME, not per verb — the step argument must not reach the id."""
    fake = _arm()
    err = TerminalError(messages.QUERY_FAILED, "boom")
    for step in ("inspect-source", "check-query", "assemble-report"):
        notify.emit_failure({"actor": "alice", "requestId": "r-1", "location": "l"}, err, step)
    ids = {c["MessageDeduplicationId"] for c in fake.calls}
    assert ids == {"r-1:failure"}


def test_a_cleanup_failure_cannot_mask_the_real_reason():
    """FR-003: the user must see what actually went wrong, not a cleanup error.

    The failure path runs the failing verb, THEN DropTempTablesOnFailure. If cleanup also
    fails, both emit — and because they share the `{requestId}:failure` id, SQS FIFO keeps
    the one it saw FIRST, which is the real cause. Order is the mechanism, so this asserts
    the order rather than trusting it.
    """
    fake = _arm()

    @notify.notifies_on_failure("check-query")
    def failing_verb(event, context):
        raise TerminalError(messages.QUERY_TIMEOUT, "the profile query timed out")

    @notify.notifies_on_failure("drop-temp-tables")
    def cleanup(event, context):
        raise TerminalError(messages.QUERY_FAILED, "glue DeleteTable blew up")

    event = {"actor": "alice", "requestId": "r-1", "location": "alice/sales"}
    for verb in (failing_verb, cleanup):
        try:
            verb(event, None)
        except TerminalError:
            pass

    ids = [c["MessageDeduplicationId"] for c in fake.calls]
    assert ids == ["r-1:failure", "r-1:failure"], "both must carry the id that collapses them"
    # The FIRST is what the queue keeps, and it must be the real cause, not the cleanup one.
    assert "too large" in fake.bodies()[0]["message"]
    assert "contact the Administrator" in fake.bodies()[1]["message"]


def test_no_dedup_id_without_a_request_id():
    """Falls back to the queue's content dedup rather than inventing an id."""
    fake = _arm()
    notify.emit_failure({"actor": "alice"}, TerminalError(messages.QUERY_FAILED))
    assert "MessageDeduplicationId" not in fake.calls[0]


# ── notifies_on_failure (FR-003) ─────────────────────────────────────────────


def test_a_bare_keyerror_still_reaches_the_user_as_a_friendly_message():
    """FR-003: an exception the handler never anticipated must not be silent."""
    fake = _arm()

    @notify.notifies_on_failure("inspect-source")
    def handler(event, context):
        raise KeyError("manifestKey")

    try:
        handler({"actor": "alice", "requestId": "r-1", "location": "alice/s"}, None)
        raise AssertionError("the exception must still propagate for the SFN Catch")
    except KeyError:
        pass
    message = fake.bodies()[0]["message"]
    assert "manifestKey" not in message  # no internals leaked
    assert "something went wrong" in message.lower()


def test_a_terminal_error_notifies_once_from_the_decorator():
    fake = _arm()

    @notify.notifies_on_failure("check-query")
    def handler(event, context):
        raise TerminalError(messages.QUERY_TIMEOUT, "profile timed out")

    try:
        handler({"actor": "alice", "requestId": "r-1", "location": "alice/s"}, None)
    except TerminalError:
        pass
    assert len(fake.calls) == 1
    assert "too large" in fake.bodies()[0]["message"]


def test_a_transient_error_does_not_notify():
    """The SFN Retry will re-run the verb; notifying now would be premature."""
    fake = _arm()

    @notify.notifies_on_failure("byte-scan")
    def handler(event, context):
        raise TransientError("throttled")

    try:
        handler({"actor": "alice", "requestId": "r-1"}, None)
    except TransientError:
        pass
    assert fake.calls == []


def test_emission_is_best_effort_and_never_fails_the_pipeline():
    """FR-005: a notification failure must never change the pipeline outcome."""

    class _Boom:
        def send_message(self, **kwargs):
            raise RuntimeError("sqs is down")

    config.NOTIFICATIONS_QUEUE_URL = QUEUE
    clients._sqs = _Boom()
    notify.emit_completed(_summary())  # must not raise


def test_unset_queue_url_is_a_no_op():
    config.NOTIFICATIONS_QUEUE_URL = ""
    fake = _FakeSqs()
    clients._sqs = fake
    notify.emit_completed(_summary())
    assert fake.calls == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("all notify tests passed")
