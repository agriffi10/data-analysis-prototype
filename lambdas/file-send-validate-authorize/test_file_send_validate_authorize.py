"""Unit tests for the file-send validate-authorize Lambda (SPEC-164).

Pure logic, AWS stubbed: ``registry.load`` and
``cognito.user_exists`` are patched per case. Asserts the validated payload shape, the
containment rules, recipient annotation and every terminal reason.

**The containment cases are the point of this file.** FR-003 requires two independent rules
with a test each, because either alone leaves a hole a cross-tenant read fits through:
``alice2/`` passes a raw ``startswith`` against root ``alice/``, and
``"alice/../bob/secrets.csv".startswith("alice/")`` is ``True``.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-send-common"))

# Direct-run baseline (pytest gets these from lambdas/conftest.py): the config module
# fail-fasts at import when the required vars are unset.
os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_validate_authorize as v
import pytest
from cpcommon.errors import TerminalError
from fscommon.config import SEND_MAX_RECIPIENTS
from token_shapes import JWT_SHAPED


def _setup(spaces=None, users=None):
    """Stub the boundary helpers: known registry spaces + known Cognito users."""
    spaces = spaces or {}
    users = users if users is not None else {"alice", "bob"}
    v.reg.load = lambda name: spaces.get(name)
    v.cognito.user_exists = lambda name: name in users


_JWT = JWT_SHAPED


def _event(
    space=None,
    items=None,
    recipients=None,
    actor="alice",
    identity=True,
    extra=None,
    request_id="req-1",
):
    body = {
        "requestId": request_id,
        "source": {
            "space": space if space is not None else {"kind": "personal", "name": "alice"},
            "items": items if items is not None else [{"kind": "file", "key": "alice/q1.csv"}],
        },
        "recipients": recipients if recipients is not None else [{"kind": "user", "name": "bob"}],
    }
    if identity:
        body["identity"] = {
            "actor": actor,
            "delegated_by": None,
            "assurance": "interactive",
        }
    body.update(extra or {})
    return [{"body": json.dumps(body)}]


def _active_space(members):
    return {"status": "active", "owner": "owner_of_space", "members": members}


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

    # Minted per invocation, so it cannot sit in an equality against a literal. Popped and
    # asserted for its shape, leaving the rest of the return pinned exactly as before.
    assert out.pop("traceparent").startswith("00-")
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


# ── FR-003: source authorization ─────────────────────────────────────────────


def test_a_personal_source_that_is_not_the_senders_own_is_refused():
    _setup()

    _expect_reason(
        _event(space={"kind": "personal", "name": "bob"}, items=[{"kind": "file", "key": "bob/x.csv"}]),
        "forbidden",
    )


def test_a_shared_source_is_authorized_for_an_active_member():
    _setup(spaces={"sales": _active_space(["alice"])})

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


# ── FR-003: containment — RULE (b), dot segments ─────────────────────────────


def test_a_parent_dot_segment_is_refused_even_though_it_starts_with_the_root():
    """THE alice/../bob/ CASE, and the reason normalisation alone is not enough:
    `"alice/../bob/secrets.csv".startswith("alice/")` is True. S3 does not resolve `..`, so
    this is not an exploitable read today — it is refused because the same string becomes the
    item name in the destination key, where a dot segment produces a legal-but-nonsense
    destination in somebody's inbox."""
    _setup()

    _expect_reason(_event(items=[{"kind": "file", "key": "alice/../bob/secrets.csv"}]), "forbidden")


# ── FR-003: the results folder ───────────────────────────────────────────────


def test_the_spaces_own_results_folder_is_not_sendable():
    _setup()

    _expect_reason(
        _event(items=[{"kind": "folder", "key": "alice/system_settings/athenaresults/"}]), "results_not_sendable"
    )


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


# ── Caps ─────────────────────────────────────────────────────────────────────


def test_too_many_recipients_is_a_whole_request_failure():
    _setup()

    _expect_reason(
        _event(recipients=[{"kind": "user", "name": f"u{i}"} for i in range(SEND_MAX_RECIPIENTS + 1)]),
        "too_many_recipients",
    )


# ── Notification behaviour ───────────────────────────────────────────────────


def test_the_block_decides_the_actor_and_the_flat_field_beside_it_does_not():
    """The block wins, and the flat field must not — it holds a raw token until the cutover.

    This was SPEC-200's "the block rides along and is ignored". Inverted rather than deleted:
    the property worth asserting is the opposite one now, and the flat field is still admitted
    by ``_ALLOWED_FIELDS``, so a reader preferring it would pass every other test in this file.
    """
    _setup(spaces={})

    result = v.handler(_event(extra={"actor": _JWT}), None)

    assert result["requestId"] == "req-1"
    assert result["actor"] == {"username": "alice"}


def test_the_verb_refuses_a_message_with_no_identity_block():
    """Fail closed on the pre-cutover envelope: a flat token, and no block at all."""
    _setup(spaces={})

    with pytest.raises(TerminalError) as raised:
        v.handler(_event(identity=False, extra={"actor": _JWT}), None)

    assert raised.value.reason == "unauthorized"
    assert "identity block" in raised.value.detail


def test_a_send_into_an_EMPTIED_space_is_refused_even_from_a_former_member():
    # A deleted space keeps `status: "active"` — nothing about its objects changed — and what
    # ends is its membership. A former member remembers the name and the name is typeable, so
    # status alone would let them send files into a workspace every surface says is gone, under
    # a prefix nobody holds a claim to, with no owner left to notify.
    emptied = {"status": "active", "members": [], "previousOwner": "alice", "emptiedAt": "t1"}
    _setup(spaces={"sales": emptied})

    out = v.handler(_event(recipients=[{"kind": "space", "name": "sales"}]), None)

    assert out["recipients"] == [{"kind": "space", "name": "sales", "invalid": "unknown_space"}]


@pytest.mark.parametrize("kind", ["admin", "", None, 1, ["personal"]], ids=["unknown", "empty", "null", "int", "list"])
def test_the_source_space_kind_vocabulary_is_closed(kind):
    """Every unknown kind must reach the plane's own refusal, an UNHASHABLE one included.

    A frozenset membership test hashes its left operand, so a request naming a list raised
    TypeError out of the check itself — reported as an unexpected fault, with the file-send
    plane's named refusal never rendered.
    """
    _setup()
    with pytest.raises(TerminalError) as caught:
        v.handler(_event(space={"kind": kind, "name": "alice"}), None)

    assert caught.value.reason == "forbidden"
    assert caught.value.detail == f"unknown source space kind {kind!r}"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"items": [{"kind": ["file"], "key": "alice/q1.csv"}]}, "invalid_items"),
        ({"recipients": [{"kind": ["user"], "name": "bob"}]}, "invalid_recipients"),
    ],
    ids=["item-kind", "recipient-kind"],
)
def test_an_unhashable_vocabulary_field_reaches_this_plane_s_own_refusal(kwargs, reason):
    """A list in either field HASHES on the way into its membership test, so before the type check
    each raised TypeError there — reported as an unexpected error, with this plane's own reason
    code never rendered onto the execution."""
    _setup()

    _expect_reason(_event(**kwargs), reason)
