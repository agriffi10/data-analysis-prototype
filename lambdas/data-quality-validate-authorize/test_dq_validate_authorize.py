"""Unit tests for the data-quality validate-authorize Lambda (SPEC-109).

Pure logic, AWS stubbed: auth.verified_username and registry.load are replaced on the
verb module, so no token is minted and no S3 is touched. Runnable under pytest or
directly: python3 test_dq_validate_authorize.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import dq_validate_authorize as v  # noqa: E402
from cpcommon.errors import TerminalError  # noqa: E402
from dqcommon import messages  # noqa: E402

USER_BUCKET = "dq-user-bkt"
SHARED_BUCKET = "dq-shared-bkt"


def _setup(actor="alice", spaces=None):
    spaces = spaces or {}
    v.config.USER_SPACE_BUCKET = USER_BUCKET
    v.config.SHARED_SPACE_BUCKET = SHARED_BUCKET
    v.auth.verified_username = lambda token, **kw: actor
    v.reg.load = lambda name: spaces.get(name)


def _event(**over):
    body = {
        "requestId": "11111111-2222-4333-8444-555555555555",
        "idToken": "stub-token",
        "space": {"kind": "personal", "bucket": USER_BUCKET, "prefix": "alice/"},
        "location": "alice/sales/",
    }
    body.update(over)
    return [{"body": json.dumps(body)}]


def _expect_reason(event, reason):
    try:
        v.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        return exc
    raise AssertionError(f"expected TerminalError({reason!r}), but the handler succeeded")


# ── identity (FR-004) ────────────────────────────────────────────────────────


def test_valid_personal_request_binds_the_verified_actor():
    _setup(actor="alice")
    out = v.handler(_event(), None)
    assert out["actor"] == "alice"
    assert out["requestId"] == "11111111-2222-4333-8444-555555555555"
    assert out["location"] == "alice/sales"
    assert out["reportPrefix"] == "alice/_data-quality-reports/11111111-2222-4333-8444-555555555555/"


def test_report_key_is_seeded_as_a_present_null():
    """THE KEY MUST EXIST FROM THE FIRST VERB, and `in` is the assertion, not the value.

    RecordFailure reads `$.reportKey`, and a Pass state's JSONPath hard-fails on an ABSENT
    key with an uncatchable States.Runtime — killing the execution before NotifyFailure and
    leaving a failed request with no notification at all. A null VALUE is fine; a missing
    key is fatal. So this asserts membership first: `out.get("reportKey") is None` would
    pass just as happily on a key that was never emitted.
    """
    _setup(actor="alice")
    out = v.handler(_event(), None)
    assert "reportKey" in out, "reportKey must be a PRESENT key, not merely absent-and-falsy"
    assert out["reportKey"] is None, "nothing has written a report yet at this point"


def test_actor_is_never_read_from_the_body():
    # A body that tries to assert an identity must be ignored — the actor comes from the
    # verified token claim only.
    _setup(actor="alice")
    out = v.handler(_event(actor="mallory", username="mallory"), None)
    assert out["actor"] == "alice"


def test_token_failure_is_unauthorized():
    _setup()

    def _raise(token, **kw):
        raise TerminalError("unauthorized", "token verification failed: expired")

    v.auth.verified_username = _raise
    _expect_reason(_event(), "unauthorized")


def test_unparseable_body_is_unauthorized():
    _setup()
    _expect_reason([{"body": "not json"}], "unauthorized")


def test_missing_request_id_is_invalid_request():
    _setup()
    body = json.loads(_event()[0]["body"])
    del body["requestId"]
    _expect_reason([{"body": json.dumps(body)}], "invalid_request")


def test_missing_space_is_invalid_request():
    _setup()
    body = json.loads(_event()[0]["body"])
    del body["space"]
    _expect_reason([{"body": json.dumps(body)}], "invalid_request")


# ── personal authorization (FR-005) ──────────────────────────────────────────


def test_personal_space_of_another_user_is_forbidden():
    _setup(actor="alice")
    _expect_reason(_event(space={"kind": "personal", "bucket": USER_BUCKET, "prefix": "bob/"}), "forbidden")


def test_personal_location_outside_the_space_is_forbidden():
    _setup(actor="alice")
    _expect_reason(_event(location="bob/secrets/"), "forbidden")


def test_personal_wrong_bucket_is_forbidden():
    _setup(actor="alice")
    _expect_reason(_event(space={"kind": "personal", "bucket": SHARED_BUCKET, "prefix": "alice/"}), "forbidden")


def test_path_traversal_cannot_escape_the_space():
    _setup(actor="alice")
    # Normalizes to "bob/secrets" — outside alice/ — so it fails the space-prefix check.
    _expect_reason(_event(location="alice/../bob/secrets"), "forbidden")


def test_reserved_prefix_cannot_be_checked():
    _setup(actor="alice")
    for reserved in ("alice/user_settings/x.json", "alice/athenaresults/q.csv", "alice/shared_tables/t/"):
        _expect_reason(_event(location=reserved), "forbidden")


# ── shared authorization (FR-005) ────────────────────────────────────────────


def _shared_event(**over):
    return _event(space={"kind": "shared", "bucket": SHARED_BUCKET, "prefix": "salesteam/"}, location="salesteam/raw/", **over)


def test_shared_active_member_is_authorized():
    _setup(actor="alice", spaces={"salesteam": {"status": "active", "members": ["alice", "bob"]}})
    out = v.handler(_shared_event(), None)
    assert out["actor"] == "alice"
    assert out["location"] == "salesteam/raw"


def test_shared_PENDING_member_is_authorized():
    """SPEC-073 grants access at ADD time, so a member whose join chip is still Pending
    must pass. 'active' here is the SPACE's provisioning status, not the member's chip.
    Pinned so nobody 'fixes' this into a membership check later."""
    _setup(
        actor="alice",
        spaces={"salesteam": {"status": "active", "members": ["alice", "bob"], "acknowledged": ["bob"]}},
    )
    out = v.handler(_shared_event(), None)
    assert out["actor"] == "alice"


def test_shared_non_member_is_forbidden():
    _setup(actor="mallory", spaces={"salesteam": {"status": "active", "members": ["alice"]}})
    _expect_reason(_shared_event(), "forbidden")


def test_shared_inactive_space_is_forbidden():
    _setup(actor="alice", spaces={"salesteam": {"status": "pending", "members": ["alice"]}})
    _expect_reason(_shared_event(), "forbidden")


def test_shared_unknown_space_is_forbidden():
    _setup(actor="alice", spaces={})
    _expect_reason(_shared_event(), "forbidden")


def test_shared_wrong_bucket_is_forbidden():
    _setup(actor="alice", spaces={"salesteam": {"status": "active", "members": ["alice"]}})
    _expect_reason(
        _event(space={"kind": "shared", "bucket": USER_BUCKET, "prefix": "salesteam/"}, location="salesteam/raw/"),
        "forbidden",
    )


def test_unknown_space_kind_is_forbidden():
    _setup(actor="alice")
    _expect_reason(_event(space={"kind": "hybrid", "bucket": USER_BUCKET, "prefix": "alice/"}), "forbidden")


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


# -- SPEC-132: the narrative ------------------------------------------------------------


def test_it_narrates_the_actor_the_space_and_the_normalized_location(captured_events):
    """FR-001: the four things an operator needs before they can go and look."""
    _setup(actor="alice")

    v.handler(_event(), None)

    authorized = captured_events.messages("authorized")
    assert len(authorized) == 1
    fields = authorized[0]["fields"]
    assert fields["actor"] == "alice"
    assert fields["space"] == "alice"
    assert fields["space_kind"] == "own"
    assert fields["location"] == "alice/sales"
    assert fields["report_prefix"].endswith("/")
    assert fields["verb"] == "validate-authorize"


def test_a_shared_check_is_distinguishable_from_a_personal_one(captured_events):
    """A shared check turned on a registry membership lookup that could itself be the thing
    that went wrong; a personal one can only ever read the actor's own prefix.
    """
    _setup(actor="alice", spaces={"team_data": {"status": "active", "members": ["alice"]}})

    v.handler(
        _event(
            space={"kind": "shared", "bucket": SHARED_BUCKET, "prefix": "team_data/"},
            location="team_data/sales/",
        ),
        None,
    )

    assert captured_events.messages("authorized")[0]["fields"]["space_kind"] == "shared"


def test_both_authorization_phases_get_their_own_child_span(captured_events):
    _setup(actor="alice")

    v.handler(_event(), None)

    parent = captured_events.spans("validate-authorize")[0]
    for step in ("authorize", "validate-destination"):
        spans = captured_events.spans(step)
        assert spans, f"no {step} span"
        assert spans[0]["parent_span_id"] == parent["span_id"]


def test_a_refusal_names_its_reason_token(captured_events):
    """FR-003: countable across runs, which prose is not."""
    _setup(actor="alice")

    _expect_reason(_event(location="bob/secrets/"), messages.FORBIDDEN)

    failed = captured_events.messages("authorization failed")
    assert failed and failed[0]["level"] == "ERROR"
    assert failed[0]["fields"]["reason"] == messages.FORBIDDEN
    assert failed[0]["fields"]["actor"] == "alice"


def test_a_refusal_says_nothing_about_which_space_exists(captured_events):
    """The membership oracle the raise site is careful about must not reopen here: one
    reason for "no such space" and for "not a member", in the events as in the message.
    """
    _setup(actor="mallory", spaces={"team_data": {"status": "active", "members": ["alice"]}})

    _expect_reason(
        _event(
            space={"kind": "shared", "bucket": SHARED_BUCKET, "prefix": "team_data/"},
            location="team_data/sales/",
        ),
        messages.FORBIDDEN,
    )
    _setup(actor="mallory", spaces={})
    _expect_reason(
        _event(
            space={"kind": "shared", "bucket": SHARED_BUCKET, "prefix": "no_such_space/"},
            location="no_such_space/sales/",
        ),
        messages.FORBIDDEN,
    )

    reasons = {e["fields"]["reason"] for e in captured_events.messages("authorization failed")}
    assert reasons == {messages.FORBIDDEN}, "the events distinguish two cases the message does not"


def test_no_event_from_this_verb_carries_the_id_token(captured_events):
    """The one thing in the envelope that is a credential rather than a name."""
    _setup(actor="alice")

    v.handler(_event(), None)

    assert "stub-token" not in json.dumps(captured_events.events)
