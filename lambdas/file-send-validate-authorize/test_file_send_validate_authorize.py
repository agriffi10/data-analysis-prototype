"""Unit tests for the file-send validate-authorize Lambda (SPEC-164).

Pure logic, AWS stubbed: ``auth.verified_username``, ``registry.load`` and
``cognito.user_exists`` are patched per case. Asserts the validated payload shape, the
containment rules, recipient annotation and every terminal reason.

**The containment cases are the point of this file.** FR-003 requires two independent rules
with a test each, because either alone leaves a hole a cross-tenant read fits through:
``alice2/`` passes a raw ``startswith`` against root ``alice/``, and
``"alice/../bob/secrets.csv".startswith("alice/")`` is ``True``.

Runnable under pytest or directly: python3 test_file_send_validate_authorize.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-send-common"))

# Direct-run baseline (pytest gets these from lambdas/conftest.py): the config module
# fail-fasts at import when the required vars are unset.
os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_validate_authorize as v
from cpcommon.errors import TerminalError
from fscommon.config import SEND_MAX_ITEM_BYTES, SEND_MAX_ITEMS, SEND_MAX_RECIPIENTS


def _setup(actor="alice", spaces=None, users=None):
    """Stub the boundary helpers: known registry spaces + known Cognito users."""
    spaces = spaces or {}
    users = users if users is not None else {"alice", "bob"}
    v.auth.verified_username = lambda token, **kw: actor
    v.reg.load = lambda name: spaces.get(name)
    v.cognito.user_exists = lambda name: name in users


def _event(space=None, items=None, recipients=None, token="tok", extra=None, request_id="req-1"):
    body = {
        "requestId": request_id,
        "actor": token,
        "source": {
            "space": space if space is not None else {"kind": "personal", "name": "alice"},
            "items": items if items is not None else [{"kind": "file", "key": "alice/q1.csv"}],
        },
        "recipients": recipients if recipients is not None else [{"kind": "user", "name": "bob"}],
    }
    body.update(extra or {})
    return [{"body": json.dumps(body)}]


def _active_space(members):
    return {"status": "active", "members": members}


def _expect_reason(event, reason):
    try:
        v.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        return
    raise AssertionError(f"expected TerminalError({reason!r}), but handler succeeded")


# ── The happy path and the output shape ──────────────────────────────────────


def test_a_valid_personal_send_is_validated():
    _setup()

    out = v.handler(_event(), None)

    assert out == {
        "requestId": "req-1",
        "actor": {"username": "alice"},
        "source": {
            "bucket": "user-bkt",
            "root": "alice/",
            "items": [{"kind": "file", "key": "alice/q1.csv"}],
        },
        "recipients": [{"kind": "user", "name": "bob"}],
    }


def test_the_output_keys_are_exactly_what_the_machine_reads():
    """The ASL's `Validated` Pass reads these four by JSONPath, and a Pass state's JSONPath
    HARD-FAILS on an absent key with an uncatchable States.Runtime. Nothing else asserts the
    contract between this verb's return value and the state machine, so a renamed key would
    kill the happy path in production with a green suite."""
    _setup()

    assert set(v.handler(_event(), None)) == {"requestId", "actor", "source", "recipients"}


def test_the_actor_comes_from_the_verified_claim_and_not_the_body():
    """The body cannot name the sender. It has no field for it, and this pins that adding one
    would change nothing."""
    _setup(actor="alice")

    out = v.handler(_event(space={"kind": "personal", "name": "alice"}), None)

    assert out["actor"] == {"username": "alice"}


def test_a_folder_is_a_valid_selection():
    """Sending a folder is the ordinary case; SPEC-165 expands it."""
    _setup()

    out = v.handler(_event(items=[{"kind": "folder", "key": "alice/reports/2026/"}]), None)

    assert out["source"]["items"] == [{"kind": "folder", "key": "alice/reports/2026/"}]


# ── FR-002: the contract ─────────────────────────────────────────────────────


def test_an_unknown_top_level_field_is_rejected_not_ignored():
    _setup()

    _expect_reason(_event(extra={"overwrite": True}), "malformed_event")


def test_a_missing_request_id_is_rejected():
    """Rejecting UNKNOWN fields does not imply requiring the KNOWN ones, and the two are
    different mistakes. SPEC-166 makes this value part of an execution-unique manifest key, so
    a None flowing through here becomes a key collision there."""
    _setup()

    _expect_reason(_event(request_id=None), "malformed_event")


def test_a_request_id_that_is_not_a_string_is_rejected():
    _setup()

    _expect_reason(_event(request_id={"evil": "../.."}), "malformed_event")


def test_a_blank_request_id_is_rejected():
    _setup()

    _expect_reason(_event(request_id="   "), "malformed_event")


def test_an_unparseable_body_fails_before_any_aws_call():
    called = []
    _setup()
    v.reg.load = lambda name: called.append(name)

    _expect_reason([{"body": "{not json"}], "unauthorized")
    assert called == []


def test_an_empty_batch_fails():
    _setup()

    _expect_reason([], "unauthorized")


# ── FR-003: source authorization ─────────────────────────────────────────────


def test_a_personal_source_that_is_not_the_senders_own_is_refused():
    _setup(actor="alice")

    _expect_reason(
        _event(space={"kind": "personal", "name": "bob"}, items=[{"kind": "file", "key": "bob/x.csv"}]),
        "forbidden",
    )


def test_a_shared_source_is_authorized_for_an_active_member():
    _setup(actor="alice", spaces={"sales": _active_space(["alice"])})

    out = v.handler(
        _event(
            space={"kind": "shared", "name": "sales"},
            items=[{"kind": "file", "key": "sales/q1.csv"}],
        ),
        None,
    )

    assert out["source"] == {
        "bucket": "shared-bkt",
        "root": "sales/",
        "items": [{"kind": "file", "key": "sales/q1.csv"}],
    }


def test_a_shared_source_the_sender_is_not_a_member_of_is_refused():
    _setup(actor="alice", spaces={"sales": _active_space(["bob"])})

    _expect_reason(
        _event(space={"kind": "shared", "name": "sales"}, items=[{"kind": "file", "key": "sales/q1.csv"}]),
        "forbidden",
    )


def test_a_shared_source_that_does_not_exist_is_refused():
    _setup(actor="alice", spaces={})

    _expect_reason(
        _event(space={"kind": "shared", "name": "nope"}, items=[{"kind": "file", "key": "nope/q1.csv"}]),
        "forbidden",
    )


def test_a_shared_source_that_is_not_yet_provisioned_is_refused():
    """`provisioning`, `deleting` and `failed` all fail — is_active_member requires
    status == "active". A member whose own join chip reads pending is NOT refused: SPEC-073
    settled that access is granted at add time and the chip is bookkeeping."""
    _setup(actor="alice", spaces={"sales": {"status": "provisioning", "members": ["alice"]}})

    _expect_reason(
        _event(space={"kind": "shared", "name": "sales"}, items=[{"kind": "file", "key": "sales/q1.csv"}]),
        "forbidden",
    )


def test_an_unknown_space_kind_is_refused():
    _setup()

    _expect_reason(_event(space={"kind": "archive", "name": "alice"}), "forbidden")


# ── FR-003: containment — RULE (a), the normalised root ──────────────────────


def test_a_sibling_prefix_does_not_pass_as_inside_the_root():
    """THE alice2/ CASE. `"alice2/x.csv".startswith("alice")` is True, and the two usernames
    need not be related for one to be a prefix of the other. The trailing-slash normalisation
    is the whole of the fix."""
    _setup(actor="alice")

    _expect_reason(_event(items=[{"kind": "file", "key": "alice2/secrets.csv"}]), "forbidden")


def test_another_users_key_is_refused():
    _setup(actor="alice")

    _expect_reason(_event(items=[{"kind": "file", "key": "bob/secrets.csv"}]), "forbidden")


def test_one_bad_key_among_good_ones_fails_the_whole_request():
    """Not a per-item skip: a request naming a key outside the sender's space is not a request
    with one bad row in it."""
    _setup(actor="alice")

    _expect_reason(
        _event(
            items=[
                {"kind": "file", "key": "alice/ok.csv"},
                {"kind": "file", "key": "bob/secrets.csv"},
            ]
        ),
        "forbidden",
    )


# ── FR-003: containment — RULE (b), dot segments ─────────────────────────────


def test_a_parent_dot_segment_is_refused_even_though_it_starts_with_the_root():
    """THE alice/../bob/ CASE, and the reason normalisation alone is not enough:
    `"alice/../bob/secrets.csv".startswith("alice/")` is True. S3 does not resolve `..`, so
    this is not an exploitable read today — it is refused because the same string becomes the
    item name in the destination key, where a dot segment produces a legal-but-nonsense
    destination in somebody's inbox."""
    _setup(actor="alice")

    _expect_reason(_event(items=[{"kind": "file", "key": "alice/../bob/secrets.csv"}]), "forbidden")


def test_a_current_dot_segment_is_refused():
    _setup(actor="alice")

    _expect_reason(_event(items=[{"kind": "file", "key": "alice/./q1.csv"}]), "forbidden")


def test_a_dot_inside_a_name_is_not_a_dot_segment():
    """The rule is about SEGMENTS. A file called `..hidden.csv` or `q1..csv` is an ordinary
    file and must still send, or the rule would refuse real user data."""
    _setup(actor="alice")

    out = v.handler(_event(items=[{"kind": "file", "key": "alice/..hidden.csv"}]), None)

    assert out["source"]["items"] == [{"kind": "file", "key": "alice/..hidden.csv"}]


# ── FR-003: the results folder ───────────────────────────────────────────────


def test_the_spaces_own_results_folder_is_not_sendable():
    _setup(actor="alice")

    _expect_reason(
        _event(items=[{"kind": "folder", "key": "alice/athenaresults/"}]), "results_not_sendable"
    )


def test_a_file_beneath_the_results_folder_is_not_sendable():
    _setup(actor="alice")

    _expect_reason(
        _event(items=[{"kind": "file", "key": "alice/athenaresults/abc123.csv"}]),
        "results_not_sendable",
    )


def test_a_nested_folder_that_merely_shares_the_name_is_sendable():
    """Anchored at the SPACE ROOT, exactly as isUndeletableRootFolder is in the browser, so a
    folder the user made themselves stays theirs to send."""
    _setup(actor="alice")

    out = v.handler(_event(items=[{"kind": "folder", "key": "alice/reports/athenaresults/"}]), None)

    assert out["source"]["items"][0]["key"] == "alice/reports/athenaresults/"


# ── FR-004: recipients ───────────────────────────────────────────────────────


def test_an_unknown_user_fails_that_recipient_not_the_request():
    _setup(users={"alice"})

    out = v.handler(
        _event(recipients=[{"kind": "user", "name": "ghost"}, {"kind": "user", "name": "alice"}]),
        None,
    )

    assert out["recipients"] == [
        {"kind": "user", "name": "ghost", "invalid": "unknown_user"},
        {"kind": "user", "name": "alice"},
    ]


def test_an_unknown_space_fails_that_recipient_not_the_request():
    _setup(spaces={})

    out = v.handler(_event(recipients=[{"kind": "space", "name": "nope"}]), None)

    assert out["recipients"] == [{"kind": "space", "name": "nope", "invalid": "unknown_space"}]


def test_membership_is_not_required_to_send_to_a_space():
    """Any space by name is a valid target — the execution role does the write, and the
    sender's own access question was about the SOURCE. Table-share's recorded decision."""
    _setup(actor="alice", spaces={"finance": _active_space(["bob"])})

    out = v.handler(_event(recipients=[{"kind": "space", "name": "finance"}]), None)

    assert out["recipients"] == [{"kind": "space", "name": "finance"}]


def test_duplicate_recipients_collapse():
    _setup()

    out = v.handler(
        _event(
            recipients=[
                {"kind": "user", "name": "bob"},
                {"kind": "user", "name": "BOB"},
                {"kind": "space", "name": "bob"},
            ]
        ),
        None,
    )

    assert out["recipients"] == [
        {"kind": "user", "name": "bob"},
        {"kind": "space", "name": "bob", "invalid": "unknown_space"},
    ]


def test_sending_to_yourself_is_allowed():
    _setup(actor="alice", users={"alice"})

    out = v.handler(_event(recipients=[{"kind": "user", "name": "alice"}]), None)

    assert out["recipients"] == [{"kind": "user", "name": "alice"}]


def test_the_username_directory_is_never_consulted():
    """SPEC-146: the directory is advisory and never an authorization input. Existence stays
    admin_get_user, which this pins by making the Cognito stub the only oracle — a directory
    read would have to come from somewhere else and there is nowhere else."""
    _setup(users=set())

    out = v.handler(_event(recipients=[{"kind": "user", "name": "bob"}]), None)

    assert out["recipients"] == [{"kind": "user", "name": "bob", "invalid": "unknown_user"}]


# ── Caps ─────────────────────────────────────────────────────────────────────


def test_too_many_recipients_is_a_whole_request_failure():
    _setup()

    _expect_reason(
        _event(recipients=[{"kind": "user", "name": f"u{i}"} for i in range(SEND_MAX_RECIPIENTS + 1)]),
        "too_many_recipients",
    )


def test_exactly_the_recipient_cap_is_allowed():
    _setup(users={f"u{i}" for i in range(SEND_MAX_RECIPIENTS)})

    out = v.handler(
        _event(recipients=[{"kind": "user", "name": f"u{i}"} for i in range(SEND_MAX_RECIPIENTS)]),
        None,
    )

    assert len(out["recipients"]) == SEND_MAX_RECIPIENTS


def test_too_many_items_is_a_whole_request_failure():
    _setup()

    _expect_reason(
        _event(items=[{"kind": "file", "key": f"alice/f{i}.csv"} for i in range(SEND_MAX_ITEMS + 1)]),
        "too_many_items",
    )


def test_a_selection_whose_keys_are_too_large_is_refused_even_under_the_count_cap():
    """The count cap bounds the WORK; this bounds the STATE, and they are different quantities.
    S3 keys are arbitrary UTF-8 and JSON escaping expands a control character to six bytes, so
    a count that fits in ASCII can be several times the payload limit in bytes."""
    _setup()
    fat = [{"kind": "file", "key": "alice/" + ("k" * 1000)} for _ in range(SEND_MAX_ITEMS)]

    _expect_reason(_event(items=fat), "selection_too_large")


def test_an_ordinary_full_selection_is_not_refused_by_the_byte_guard():
    """The other direction: the byte guard must not make the count cap unreachable in practice."""
    _setup()
    ordinary = [{"kind": "file", "key": f"alice/reports/2026/q1/file-{i:04d}.csv"} for i in range(SEND_MAX_ITEMS)]

    out = v.handler(_event(items=ordinary), None)

    assert len(out["source"]["items"]) == SEND_MAX_ITEMS


def test_the_byte_guard_measures_the_serialised_form_and_not_the_character_count():
    """A key of escape-heavy characters costs its REAL size. Measured against the same budget
    the config test models, so the two cannot drift."""
    _setup()
    # Same character COUNT on both sides — only the escaping differs, which is the whole point.
    escaped = [{"kind": "file", "key": "alice/" + ('"' * 300)} for _ in range(SEND_MAX_ITEMS)]
    plain = [{"kind": "file", "key": "alice/" + ("k" * 300)} for _ in range(SEND_MAX_ITEMS)]

    assert len(json.dumps(escaped).encode()) > SEND_MAX_ITEM_BYTES > len(json.dumps(plain).encode())
    _expect_reason(_event(items=escaped), "selection_too_large")
    assert len(v.handler(_event(items=plain), None)["source"]["items"]) == SEND_MAX_ITEMS


def test_selecting_the_space_root_is_refused_because_it_contains_the_results_folder():
    """Through the real handler, not just the helper: selecting a whole space passes both
    containment rules, and SPEC-165 would expand it straight over athenaresults/."""
    _setup(actor="alice")

    _expect_reason(_event(items=[{"kind": "folder", "key": "alice/"}]), "results_not_sendable")


def test_a_folder_key_is_normalised_to_a_trailing_slash():
    """SPEC-165 expands a folder with a prefix listing, so `alice/athenaresult` without a
    trailing slash would match `alice/athenaresults/…` and carry the query results out through
    a door the results rule never sees. Normalising first closes it, and also makes the key the
    expansion will actually use the key this verb checked."""
    _setup(actor="alice")

    out = v.handler(_event(items=[{"kind": "folder", "key": "alice/reports"}]), None)

    assert out["source"]["items"] == [{"kind": "folder", "key": "alice/reports/"}]


def test_normalising_is_what_stops_a_near_miss_folder_reaching_the_results():
    """`alice/athenaresult` is a real, different folder and must send. The danger was never the
    KEY — it was the PREFIX LISTING SPEC-165 will do with it: `ListObjectsV2(Prefix=
    "alice/athenaresult")` matches `alice/athenaresults/…` and would carry the query results out
    through a door the results rule never sees. Normalising to a trailing slash is the fix, and
    this pins that the key handed onward is the one that cannot do it."""
    _setup(actor="alice")

    out = v.handler(_event(items=[{"kind": "folder", "key": "alice/athenaresult"}]), None)

    key = out["source"]["items"][0]["key"]
    assert key == "alice/athenaresult/"
    assert not "alice/athenaresults/".startswith(key), "the normalised prefix still reaches the results folder"


def test_a_file_key_is_left_exactly_as_given():
    """Only folders are normalised. An object key is bytes, and appending to one would name a
    different object."""
    _setup(actor="alice")

    out = v.handler(_event(items=[{"kind": "file", "key": "alice/reports"}]), None)

    assert out["source"]["items"] == [{"kind": "file", "key": "alice/reports"}]


def test_a_recipient_name_longer_than_cognito_allows_is_a_contract_violation():
    """Not a transient fault. AdminGetUser rejects an over-long username as an invalid
    parameter, which the shared lookup classifies as transient — so without this bound the
    machine would retry three times and fail the WHOLE request over one bad recipient."""
    _setup()

    _expect_reason(_event(recipients=[{"kind": "user", "name": "u" * 129}]), "invalid_recipients")


def test_the_item_cap_is_checked_before_any_item_is_examined():
    """The cap exists to bound work proportional to caller-supplied input, so an over-cap
    request must not be walked first. An out-of-root key in the payload proves the order: if
    the loop ran, the reason would be `forbidden`."""
    _setup()
    over = [{"kind": "file", "key": "bob/secrets.csv"} for _ in range(SEND_MAX_ITEMS + 1)]

    _expect_reason(_event(items=over), "too_many_items")


# ── Malformed lists ──────────────────────────────────────────────────────────


def test_an_empty_selection_is_refused():
    _setup()

    _expect_reason(_event(items=[]), "no_items")


def test_a_selection_that_is_not_a_list_is_refused():
    _setup()

    _expect_reason(_event(items={"kind": "file", "key": "alice/q1.csv"}), "invalid_items")


def test_an_unknown_item_kind_is_refused():
    _setup()

    _expect_reason(_event(items=[{"kind": "symlink", "key": "alice/q1.csv"}]), "invalid_items")


def test_an_item_without_a_key_is_refused():
    _setup()

    _expect_reason(_event(items=[{"kind": "file"}]), "invalid_items")


def test_an_empty_recipient_list_is_refused():
    _setup()

    _expect_reason(_event(recipients=[]), "no_recipients")


def test_an_unknown_recipient_kind_is_refused():
    _setup()

    _expect_reason(_event(recipients=[{"kind": "group", "name": "x"}]), "invalid_recipients")


# ── Notification behaviour ───────────────────────────────────────────────────


def test_a_rejection_after_the_sender_is_known_notifies_them():
    _setup(actor="alice")
    sent = []
    v.notify.emit_notification = lambda user, message: sent.append((user, message))

    _expect_reason(_event(items=[{"kind": "file", "key": "bob/secrets.csv"}]), "forbidden")

    assert len(sent) == 1
    assert sent[0][0] == "alice"
    assert "bob/secrets.csv" not in sent[0][1], "the raw key must not reach the user's message"


def test_a_failure_before_the_token_is_verified_notifies_nobody():
    """There is no trusted addressee yet, and the body's own fields are attacker-controlled."""
    _setup()
    sent = []
    v.notify.emit_notification = lambda user, message: sent.append((user, message))

    def _reject(token, **kw):
        raise TerminalError("unauthorized", "bad token")

    v.auth.verified_username = _reject

    _expect_reason(_event(), "unauthorized")

    assert sent == []


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
