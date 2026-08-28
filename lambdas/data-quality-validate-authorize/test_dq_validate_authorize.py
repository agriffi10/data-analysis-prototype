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

import dq_validate_authorize as v
from cpcommon.errors import TerminalError

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


# ── personal authorization (FR-005) ──────────────────────────────────────────


def test_personal_space_of_another_user_is_forbidden():
    _setup(actor="alice")
    _expect_reason(_event(space={"kind": "personal", "bucket": USER_BUCKET, "prefix": "bob/"}), "forbidden")


def test_path_traversal_cannot_escape_the_space():
    _setup(actor="alice")
    # Normalizes to "bob/secrets" — outside alice/ — so it fails the space-prefix check.
    _expect_reason(_event(location="alice/../bob/secrets"), "forbidden")


# ── shared authorization (FR-005) ────────────────────────────────────────────


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


