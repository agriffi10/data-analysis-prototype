"""Tests for the notification primitives cpcommon owns (SPEC-156 FR-002).

The sender and the failure decorator are exercised through each plane's own notify tests;
what is asserted here is the deduplication token, which two planes had copied verbatim, and
``actor_of``, which file-send and archive had copied verbatim between them.

Runnable under pytest or directly: python3 test_notify_cpcommon.py.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from cpcommon.notify import actor_of, dedup_id


def test_the_token_is_the_request_id_and_the_outcome():
    assert dedup_id("r-1", "failure") == "r-1:failure"


def test_no_request_id_falls_back_to_content_based_dedup():
    """None is the honest answer, not an invented id: an invented one would defeat the
    queue's own content-based deduplication rather than replace it."""
    assert dedup_id("", "failure") is None
    assert dedup_id(None, "failure") is None


def test_this_builder_composes_a_token_and_does_not_choose_one():
    """The distinction the docstring turns on, pinned where a reader will hit it.

    SPEC-114's one-token-per-outcome rule is data-quality's and shared-spaces' — it lives in
    what those planes pass as `step`, not here. table-builder deliberately passes the VERB
    name from its decorator and "failure" from its notify-failure verb, suppressing the
    duplicate a different way. So this function must stay a pure composer: two callers that
    disagree get different ids, and that is correct rather than a bug to unify.
    """
    assert dedup_id("r-1", "apply") != dedup_id("r-1", "failure")
    assert dedup_id("r-1", "failure") != dedup_id("r-2", "failure")


def test_the_four_planes_disagree_on_the_step_and_the_shared_builder_survives_it():
    """Reads the real callers rather than restating the docstring: data-quality's step is an
    OUTCOME constant, table-builder's decorator step is a VERB name. If these ever converge,
    the docstring on `dedup_id` needs rewriting, not this test deleting."""
    import dqcommon.notify as dq

    assert dq.FAILURE_STEP == "failure" and dq.SUCCESS_STEP == "completed"
    assert dedup_id("r-1", dq.FAILURE_STEP) == "r-1:failure"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── actor_of — the flat SPEC-164 envelope file-send and archive share ────────


def test_a_verified_username_is_read_straight_off_the_request():
    assert actor_of({"actor": "alice"}) == "alice"


def test_the_token_object_is_unwrapped_to_its_verified_username():
    """After validate-authorize binds the identity, `actor` is the object it verified — the
    username on it is the verified claim, never the body's own assertion."""
    assert actor_of({"actor": {"username": "alice", "token": "tok"}}) == "alice"


@pytest.mark.parametrize(
    "event",
    [
        [{"body": "{}"}],
        "not-an-object",
        None,
        {},
        {"actor": None},
        {"actor": {}},
        {"actor": {"username": None}},
        {"actor": 42},
    ],
    ids=[
        "the-raw-sqs-array",
        "not-an-object",
        "none",
        "no-actor-field",
        "null-actor",
        "empty-token-object",
        "token-object-with-no-username",
        "actor-of-the-wrong-type",
    ],
)
def test_a_pre_identity_event_yields_no_actor_rather_than_raising(event):
    """That window is real and is not an error: validate-authorize's event is the raw SQS array
    until the token is verified. An emit with no addressee is a logged no-op — never a message
    sent to whoever the untrusted body named."""
    assert actor_of(event) == ""
