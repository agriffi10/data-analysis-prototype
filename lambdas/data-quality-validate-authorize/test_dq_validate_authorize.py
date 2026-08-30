"""Unit tests for the data-quality validate-authorize Lambda (SPEC-109).

Pure logic, AWS stubbed: registry.load is replaced on the
verb module, so no token is minted and no S3 is touched. Runnable under pytest or
directly: python3 test_dq_validate_authorize.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import dq_validate_authorize as v
from cpcommon.errors import TerminalError
from token_shapes import JWT_SHAPED

USER_BUCKET = "dq-user-bkt"
SHARED_BUCKET = "dq-shared-bkt"


def _setup(spaces=None):
    spaces = spaces or {}
    v.config.USER_SPACE_BUCKET = USER_BUCKET
    v.config.SHARED_SPACE_BUCKET = SHARED_BUCKET
    v.reg.load = lambda name: spaces.get(name)


def _event(actor="alice", **over):
    body = {
        "requestId": "11111111-2222-4333-8444-555555555555",
        "identity": {"actor": actor, "delegated_by": None, "assurance": "interactive"},
        "space": {"kind": "personal", "bucket": USER_BUCKET, "prefix": "alice/"},
        "location": "alice/sales/",
    }
    body.update(over)
    return [{"body": json.dumps(body)}]


def _expect_reason(event, reason, detail=None):
    """Asserts the refusal, and — where given — WHICH refusal.

    Six of this verb's authorization branches raise `forbidden`, so a test asserting only the
    code cannot tell the branch it names from the neighbour that catches the same request.
    """
    try:
        v.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        if detail is not None:
            assert detail in exc.detail, f"expected detail {detail!r}, got {exc.detail!r}"
        return exc
    raise AssertionError(f"expected TerminalError({reason!r}), but the handler succeeded")


# ── identity (FR-004) ────────────────────────────────────────────────────────


def test_valid_personal_request_binds_the_verified_actor():
    _setup()
    out = v.handler(_event(), None)
    assert out["actor"] == "alice"
    assert out["requestId"] == "11111111-2222-4333-8444-555555555555"
    assert out["location"] == "alice/sales"
    assert out["reportPrefix"] == "alice/_data-quality-reports/11111111-2222-4333-8444-555555555555/"


# ── personal authorization (FR-005) ──────────────────────────────────────────


def test_personal_space_of_another_user_is_forbidden():
    _setup()
    _expect_reason(
        _event(space={"kind": "personal", "bucket": USER_BUCKET, "prefix": "bob/"}),
        "forbidden",
        "personal space must be the actor's own",
    )


def test_path_traversal_cannot_escape_the_space():
    _setup()
    # Normalizes to "bob/secrets" — outside alice/ — so it fails the space-prefix check.
    _expect_reason(_event(location="alice/../bob/secrets"), "forbidden", "location escapes")


# ── shared authorization (FR-005) ────────────────────────────────────────────


def test_a_shared_space_the_actor_is_not_an_active_member_of_is_forbidden():
    """The branch this section is named for, and it had no test at all.

    Found by deleting the membership check and watching the suite stay green: this plane's only
    authorization negatives were personal-space ones, so the shared-space half — the branch that
    decides whether one user may run a quality check over another team's data — was asserted
    nowhere. The detail is asserted because six branches here raise `forbidden`.
    """
    _setup(spaces={"salesteam": {"status": "active", "owner": "bob", "members": ["bob"]}})

    _expect_reason(
        _event(
            space={"kind": "shared", "bucket": SHARED_BUCKET, "prefix": "salesteam/"},
            location="salesteam/q1/",
        ),
        "forbidden",
        "is not an active member",
    )


def test_a_shared_space_the_actor_IS_a_member_of_passes():
    """The paired positive, so the refusal above cannot be passing because the fixture is broken."""
    _setup(spaces={"salesteam": {"status": "active", "owner": "bob", "members": ["bob", "alice"]}})

    out = v.handler(
        _event(
            space={"kind": "shared", "bucket": SHARED_BUCKET, "prefix": "salesteam/"},
            location="salesteam/q1/",
        ),
        None,
    )

    assert out["actor"] == "alice"


def test_a_message_with_no_identity_block_is_refused():
    """Fail closed on the pre-cutover envelope: a flat token, no block, no S3 read.

    The refusal must land BEFORE the registry load. A plane that refuses after listing has
    already used the caller's non-identity as an existence oracle, and paid for the call.
    """
    _setup()
    v.reg.load = lambda name: (_ for _ in ()).throw(AssertionError("AWS CALL: registry read"))

    body = {
        "requestId": "11111111-2222-4333-8444-555555555555",
        "actor": JWT_SHAPED,
        "space": {"kind": "personal", "bucket": USER_BUCKET, "prefix": "alice/"},
        "location": "alice/sales/",
    }
    _expect_reason([{"body": json.dumps(body)}], "unauthorized")


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
