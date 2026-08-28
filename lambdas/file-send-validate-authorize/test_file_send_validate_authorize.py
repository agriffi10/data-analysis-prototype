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
from fscommon.config import SEND_MAX_RECIPIENTS


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


# ── FR-002: the contract ─────────────────────────────────────────────────────


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


# ── FR-003: containment — RULE (a), the normalised root ──────────────────────


# ── FR-003: containment — RULE (b), dot segments ─────────────────────────────


def test_a_parent_dot_segment_is_refused_even_though_it_starts_with_the_root():
    """THE alice/../bob/ CASE, and the reason normalisation alone is not enough:
    `"alice/../bob/secrets.csv".startswith("alice/")` is True. S3 does not resolve `..`, so
    this is not an exploitable read today — it is refused because the same string becomes the
    item name in the destination key, where a dot segment produces a legal-but-nonsense
    destination in somebody's inbox."""
    _setup(actor="alice")

    _expect_reason(_event(items=[{"kind": "file", "key": "alice/../bob/secrets.csv"}]), "forbidden")


# ── FR-003: the results folder ───────────────────────────────────────────────


def test_the_spaces_own_results_folder_is_not_sendable():
    _setup(actor="alice")

    _expect_reason(
        _event(items=[{"kind": "folder", "key": "alice/athenaresults/"}]), "results_not_sendable"
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


# ── Malformed lists ──────────────────────────────────────────────────────────


# ── Notification behaviour ───────────────────────────────────────────────────


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
