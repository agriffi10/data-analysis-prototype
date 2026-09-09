"""Unit tests for the table-share validate-authorize Lambda (SPEC-089).

Pure logic, AWS stubbed: registry.load and
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
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import table_share_validate_authorize as v
from cpcommon.errors import TerminalError
from token_shapes import JWT_SHAPED


def _setup(spaces=None, users=None):
    """Stub the boundary helpers: known registry spaces + known Cognito users."""
    spaces = spaces or {}
    users = users if users is not None else {"alice", "bob"}
    v.reg.load = lambda name: spaces.get(name)
    v.cog.user_exists = lambda name: name in users


def _event(source=None, table_name="orders_copy", recipients=None, actor="alice"):
    body = {
        "identity": {"actor": actor, "delegated_by": None, "assurance": "interactive"},
        "source": source if source is not None else {"database": "alice", "table": "orders"},
        "tableName": table_name,
        "recipients": recipients if recipients is not None else [{"kind": "user", "name": "bob"}],
    }
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


def test_valid_personal_source_passes():
    _setup()
    out = v.handler(_event(), None)
    # Minted per invocation; popped so the rest stays an exact equality. table-share carries no
    # requestId at all, so this is the ONLY value joining its verbs to their run.
    assert out.pop("traceparent").startswith("00-")
    assert out == {
        "actor": "alice",
        "source": {"database": "alice", "table": "orders"},
        "tableName": "orders_copy",
        "recipients": [{"kind": "user", "name": "bob", "valid": True}],
    }


def test_shared_source_non_member_is_forbidden():
    _setup(spaces={"salesteam": _active_space(["carol"])})
    _expect_reason(_event(source={"database": "salesteam", "table": "orders"}), "forbidden")


def test_invalid_table_name_is_terminal():
    _setup()
    for bad in ["Orders", "1orders", "or", "", None, "a" * 64]:
        _expect_reason(_event(table_name=bad), "invalid_table_name")


def test_a_message_with_no_identity_block_is_refused():
    """Fail closed on the pre-cutover envelope, where the flat ``actor`` IS the raw token.

    This plane is the one where a fallback is most tempting and most dangerous: its flat field
    is named ``actor`` and holds a JWT, so a reader preferring it resolves a 900-character
    string as a Glue database name. The registry read must not happen at all.
    """
    _setup()
    v.reg.load = lambda name: (_ for _ in ()).throw(AssertionError("AWS CALL: registry read"))

    body = {
        "actor": JWT_SHAPED,
        "source": {"database": "alice", "table": "orders"},
        "tableName": "orders_copy",
        "recipients": [{"kind": "user", "name": "bob"}],
    }
    _expect_reason([{"body": json.dumps(body)}], "unauthorized")


def test_a_share_into_an_EMPTIED_space_is_refused_even_from_a_former_member():
    # A deleted space keeps `status: "active"` — nothing about its database changed — and what
    # ends is its membership. Status alone would let a former member who remembers the name
    # create a table in the retained catalog of a workspace every surface says is gone, and be
    # told it succeeded, with no owner left to notify.
    emptied = {"status": "active", "members": [], "previousOwner": "alice", "emptiedAt": "t1"}
    _setup(spaces={"salesteam": emptied})

    out = v.handler(_event(recipients=[{"kind": "space", "name": "salesteam"}]), None)

    assert out["recipients"] == [
        {"kind": "space", "name": "salesteam", "valid": False, "reason": "unknown_space"}
    ]


def test_an_unhashable_recipient_kind_reaches_this_plane_s_own_refusal():
    """A list HASHES on the way into the membership test, so before the type check it raised
    TypeError there — reported as an unexpected error, with this plane's own reason code never
    rendered onto the execution."""
    _setup()

    _expect_reason(_event(recipients=[{"kind": ["user"], "name": "bob"}]), "invalid_recipients")


def test_recipient_space_membership_not_required():
    """A space the sender does not belong to is a valid RECIPIENT, and that is deliberate.

    The asymmetry is the point, and it is the half a reader is most likely to get backwards:
    the SOURCE requires active membership — ``test_shared_source_non_member_is_forbidden``
    above — while a recipient does not, because sending someone a table is not reading their
    data. Both dialogs' unlisted-name notes and the identity register cite this by name to
    explain why an unlisted space is not a mistake, so it is pinned here rather than inferred
    from the absence of a membership call.

    Membership is what this asserts and the ONLY thing: an active space still has to name an
    owner, which ``test_a_share_into_an_EMPTIED_space_is_refused_even_from_a_former_member``
    pins from the other side. Read as "any active space is a target" this becomes the
    disclosure ``may_receive_share`` exists to refuse.
    """
    salesteam = _active_space(["carol"])
    assert "alice" not in salesteam["members"], "the fixture stopped being a non-member"
    _setup(spaces={"salesteam": salesteam})

    out = v.handler(
        _event(actor="alice", recipients=[{"kind": "space", "name": "salesteam"}]), None
    )

    assert out["recipients"] == [{"kind": "space", "name": "salesteam", "valid": True}]


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
