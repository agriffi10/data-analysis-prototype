"""Unit tests for the shared-space provisioner (SPEC-056 validate + actor binding).

Runs under pytest *or* as a plain script (`python3 test_shared_space_provisioner.py`);
the JS CI does not run Python. Token signature verification (PyJWT/JWKS) is mocked —
these tests cover the security CORE: the pure `authorize()` rules and the handler's
trusted-actor-binding flow (forged token rejected, verb only runs when authorized).
"""

import json

import shared_space_provisioner as p


def _raises(fn, match=None):
    try:
        fn()
    except p.AuthorizationError as exc:
        if match is not None:
            assert match in str(exc), f"expected {match!r} in {str(exc)!r}"
        return
    raise AssertionError("expected AuthorizationError, none raised")


# ── authorize(): owner/membership rules ──────────────────────────────────────
REG = {"name": "sales", "owner": "alice", "members": ["alice", "bob"], "status": "active"}


def test_create_allowed_for_any_actor_no_registry():
    assert p.authorize("create", "sales", "zoe", None) is None


def test_owner_only_actions_allow_owner():
    for action in ("add_members", "remove_members", "delete"):
        assert p.authorize(action, "sales", "alice", REG) is None


def test_owner_only_actions_deny_non_owner():
    for action in ("add_members", "remove_members", "delete"):
        _raises(lambda a=action: p.authorize(a, "sales", "bob", REG), "owner-only")


def test_owner_only_actions_deny_when_space_missing():
    _raises(lambda: p.authorize("delete", "ghost", "alice", None), "does not exist")


def test_leave_allowed_for_member():
    assert p.authorize("leave", "sales", "bob", REG) is None


def test_leave_denied_for_owner():
    _raises(lambda: p.authorize("leave", "sales", "alice", REG), "owner cannot leave")


def test_leave_denied_for_non_member():
    _raises(lambda: p.authorize("leave", "sales", "mallory", REG), "not a member")


def test_unknown_action_rejected():
    _raises(lambda: p.authorize("nuke", "sales", "alice", REG), "unknown action")


# ── handler(): trusted-actor binding flow ────────────────────────────────────
def _event(action="create", space="sales", token="tok", actor_body="anyone", extra=None):
    body = {"schemaVersion": 1, "requestId": "r1", "action": action,
            "actor": actor_body, "space": space, "idToken": token}
    if extra:
        body.update(extra)
    return [{"body": json.dumps(body)}]


def _patch(monkey_user=None, registry=None):
    p.verified_username = lambda tok: monkey_user
    p.load_registry = lambda space: registry


def test_handler_create_authorized_binds_token_actor(monkeypatch=None):
    # Body claims actor "anyone"; the verified token says "alice" -> actor is alice.
    orig_v, orig_r = p.verified_username, p.load_registry
    try:
        p.verified_username = lambda tok: "alice"
        p.load_registry = lambda space: None
        out = p.handler(_event(action="create", actor_body="anyone"), None)
        assert out == {"status": "authorized", "action": "create", "space": "sales", "actor": "alice"}
    finally:
        p.verified_username, p.load_registry = orig_v, orig_r


def test_handler_forged_token_rejected_before_any_verb():
    orig_v, orig_r = p.verified_username, p.load_registry
    calls = []
    try:
        def boom(tok):
            raise p.AuthorizationError("token verification failed")
        p.verified_username = boom
        p.load_registry = lambda space: calls.append(space)  # must NOT be called
        _raises(lambda: p.handler(_event(action="delete"), None), "verification failed")
        assert calls == [], "registry/verb must not run when the token is forged"
    finally:
        p.verified_username, p.load_registry = orig_v, orig_r


def test_handler_owner_action_by_non_owner_rejected():
    orig_v, orig_r = p.verified_username, p.load_registry
    try:
        p.verified_username = lambda tok: "bob"   # bob is a member, not owner
        p.load_registry = lambda space: REG
        _raises(lambda: p.handler(_event(action="delete"), None), "owner-only")
    finally:
        p.verified_username, p.load_registry = orig_v, orig_r


def test_handler_bad_schema_version_rejected():
    _raises(lambda: p.handler([{"body": json.dumps({"schemaVersion": 99, "action": "create"})}], None),
            "schemaVersion")


def test_handler_missing_body_rejected():
    _raises(lambda: p.handler([{}], None), "missing message body")


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} shared_space_provisioner tests passed.")
    sys.exit(0)
