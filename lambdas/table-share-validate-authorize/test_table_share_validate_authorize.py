"""Unit tests for the table-share validate-authorize Lambda (SPEC-089).

Pure logic, AWS stubbed: auth.verified_username, registry.load, and
cognito.user_exists are patched per case. Asserts the validated payload shape,
recipient annotation, and every terminal reason. Runnable under pytest or directly:
python3 test_validate_authorize.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-common"))

# Direct-run baseline (pytest gets these from lambdas/conftest.py): the config
# module fail-fasts at import when the required vars are unset.
os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

from tscommon.config import SHARE_MAX_RECIPIENTS  # noqa: E402

import table_share_validate_authorize as v  # noqa: E402
from cpcommon.errors import TerminalError  # noqa: E402


def _setup(actor="alice", spaces=None, users=None):
    """Stub the boundary helpers: known registry spaces + known Cognito users."""
    spaces = spaces or {}
    users = users if users is not None else {"alice", "bob"}
    v.auth.verified_username = lambda token, **kw: actor
    v.reg.load = lambda name: spaces.get(name)
    v.cog.user_exists = lambda name: name in users


def _event(source=None, table_name="orders_copy", recipients=None, token="tok"):
    body = {
        "actor": token,
        "source": source if source is not None else {"database": "alice", "table": "orders"},
        "tableName": table_name,
        "recipients": recipients if recipients is not None else [{"kind": "user", "name": "bob"}],
    }
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


def test_valid_personal_source_passes():
    _setup()
    out = v.handler(_event(), None)
    assert out == {
        "actor": "alice",
        "source": {"database": "alice", "table": "orders"},
        "tableName": "orders_copy",
        "recipients": [{"kind": "user", "name": "bob", "valid": True}],
    }


def test_shared_source_requires_active_membership():
    _setup(spaces={"salesteam": _active_space(["alice", "carol"])})
    out = v.handler(_event(source={"database": "salesteam", "table": "orders"}), None)
    assert out["source"] == {"database": "salesteam", "table": "orders"}


def test_shared_source_non_member_is_forbidden():
    _setup(spaces={"salesteam": _active_space(["carol"])})
    _expect_reason(_event(source={"database": "salesteam", "table": "orders"}), "forbidden")


def test_unknown_source_database_is_forbidden():
    _setup()
    _expect_reason(_event(source={"database": "someoneelse", "table": "orders"}), "forbidden")


def test_inactive_source_space_is_forbidden():
    _setup(spaces={"salesteam": {"status": "deleting", "members": ["alice"]}})
    _expect_reason(_event(source={"database": "salesteam", "table": "orders"}), "forbidden")


def test_malformed_source_is_forbidden():
    _setup()
    _expect_reason(_event(source={"database": "alice"}), "forbidden")
    _expect_reason(_event(source="alice.orders"), "forbidden")


def _raise_unauthorized(token, **kw):
    raise TerminalError("unauthorized", "stub")


def test_missing_token_is_unauthorized():
    _setup()
    v.auth.verified_username = _raise_unauthorized
    _expect_reason(_event(token=""), "unauthorized")


def test_bad_json_body_is_unauthorized():
    _setup()
    _expect_reason([{"body": "{nope"}], "unauthorized")
    _expect_reason([], "unauthorized")
    _expect_reason([{}], "unauthorized")


def test_invalid_table_name_is_terminal():
    _setup()
    for bad in ["Orders", "1orders", "or", "", None, "a" * 64]:
        _expect_reason(_event(table_name=bad), "invalid_table_name")


def test_empty_or_missing_recipients_is_terminal():
    _setup()
    _expect_reason(_event(recipients=[]), "no_recipients")
    event = [{"body": json.dumps({"actor": "tok", "source": {"database": "alice", "table": "t1"},
                                  "tableName": "copy_t1"})}]
    _expect_reason(event, "no_recipients")


def test_malformed_recipient_is_terminal():
    _setup()
    _expect_reason(_event(recipients=[{"kind": "group", "name": "x"}]), "invalid_recipients")
    _expect_reason(_event(recipients=[{"kind": "user"}]), "invalid_recipients")
    _expect_reason(_event(recipients=["bob"]), "invalid_recipients")
    _expect_reason(_event(recipients={"kind": "user", "name": "bob"}), "invalid_recipients")


def test_a_recipient_list_over_the_cap_is_terminal():
    """The cap exists for the MAP'S RESULT, not the fan-out.

    Each recipient contributes a summary entry to `$.recipientResults`, and a failed one
    carries the raw {Error, Cause}. Unbounded, a broadly-failing share breaches Step
    Functions' 256 KB state payload — States.DataLimitExceeded fires on the Map and
    destroys every per-recipient outcome the Map exists to preserve.
    """
    _setup()
    over = [{"kind": "user", "name": f"user{i:04d}"} for i in range(SHARE_MAX_RECIPIENTS + 1)]

    _expect_reason(_event(recipients=over), "too_many_recipients")


def test_a_recipient_list_exactly_at_the_cap_is_accepted():
    """The boundary, both sides — an off-by-one here rejects a legitimate share."""
    _setup()
    at_cap = [{"kind": "user", "name": f"user{i:04d}"} for i in range(SHARE_MAX_RECIPIENTS)]

    out = v.handler(_event(recipients=at_cap), None)

    assert len(out["recipients"]) == SHARE_MAX_RECIPIENTS


def test_the_cap_is_checked_before_dedupe_collapses_the_list():
    """A caller cannot smuggle 10,000 entries past the cap by repeating one name.

    Dedupe only ever shrinks the list, so checking after it would let an arbitrarily large
    raw list through the O(n) normalisation loop first — the work the cap exists to avoid.
    """
    _setup()
    duplicates = [{"kind": "user", "name": "bob"}] * (SHARE_MAX_RECIPIENTS + 50)

    _expect_reason(_event(recipients=duplicates), "too_many_recipients")


def test_duplicate_recipients_collapse():
    _setup()
    out = v.handler(
        _event(recipients=[
            {"kind": "user", "name": "bob"},
            {"kind": "user", "name": " Bob "},
            {"kind": "space", "name": "bob"},
        ]),
        None,
    )
    assert [r["name"] for r in out["recipients"]] == ["bob", "bob"]
    assert [r["kind"] for r in out["recipients"]] == ["user", "space"]


def test_unknown_user_recipient_is_annotated_not_fatal():
    _setup(users={"alice"})
    out = v.handler(
        _event(recipients=[{"kind": "user", "name": "ghost"}, {"kind": "user", "name": "alice"}]),
        None,
    )
    assert out["recipients"] == [
        {"kind": "user", "name": "ghost", "valid": False, "reason": "unknown_user"},
        {"kind": "user", "name": "alice", "valid": True},
    ]


def test_space_recipient_must_be_active():
    _setup(spaces={"live": _active_space(["carol"]), "half": {"status": "provisioning"}})
    out = v.handler(
        _event(recipients=[
            {"kind": "space", "name": "live"},
            {"kind": "space", "name": "half"},
            {"kind": "space", "name": "gone"},
        ]),
        None,
    )
    assert out["recipients"] == [
        {"kind": "space", "name": "live", "valid": True},
        {"kind": "space", "name": "half", "valid": False, "reason": "unknown_space"},
        {"kind": "space", "name": "gone", "valid": False, "reason": "unknown_space"},
    ]


def test_recipient_space_membership_not_required():
    # Any ACTIVE space is a valid target even though the actor isn't a member
    # (docs/table-share-architecture.md §3, user decision).
    _setup(spaces={"otherteam": _active_space(["carol", "dan"])})
    out = v.handler(_event(recipients=[{"kind": "space", "name": "otherteam"}]), None)
    assert out["recipients"] == [{"kind": "space", "name": "otherteam", "valid": True}]


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if failures else 0)
