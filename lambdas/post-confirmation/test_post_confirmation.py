"""Unit tests for the post-confirmation trigger (SPEC-033 FR-002) and the backfill
reuse (FR-004). Runs under pytest *or* as a plain script (`python3
test_post_confirmation.py`).

boto3 is provided by the Lambda runtime, not installed in CI, so before importing the
handler we inject a tiny fake `boto3` into sys.modules that records Glue/Lake Formation
calls and lets us simulate "already exists". PORTAL_ROLE_ARN is likewise set first
because the handler reads it at import time.
"""

import os
import sys
import types

os.environ.setdefault("PORTAL_ROLE_ARN", "arn:aws:iam::123456789012:role/test-portal-role")
PORTAL_ROLE_ARN = os.environ["PORTAL_ROLE_ARN"]


class _AlreadyExistsException(Exception):
    pass


class _FakeGlue:
    def __init__(self):
        self.create_calls = []
        self.raise_already_exists = False
        self.exceptions = types.SimpleNamespace(
            AlreadyExistsException=_AlreadyExistsException
        )

    def create_database(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.raise_already_exists:
            raise self.exceptions.AlreadyExistsException("Database already exists.")


class _FakeLakeFormation:
    def __init__(self):
        self.grant_calls = []
        self.tag_calls = []
        self.raise_error = None
        self.tag_failures = []

    def grant_permissions(self, **kwargs):
        self.grant_calls.append(kwargs)
        if self.raise_error is not None:
            raise self.raise_error

    def add_lf_tags_to_resource(self, **kwargs):
        self.tag_calls.append(kwargs)
        return {"Failures": list(self.tag_failures)}


_fake_glue = _FakeGlue()
_fake_lf = _FakeLakeFormation()

_fake_boto3 = types.ModuleType("boto3")
_fake_boto3.client = lambda name, *a, **k: {
    "glue": _fake_glue,
    "lakeformation": _fake_lf,
}[name]
sys.modules["boto3"] = _fake_boto3

import backfill
import post_confirmation


def _reset():
    _fake_glue.create_calls.clear()
    _fake_glue.raise_already_exists = False
    _fake_lf.grant_calls.clear()
    _fake_lf.tag_calls.clear()
    _fake_lf.raise_error = None
    _fake_lf.tag_failures = []


def _event(username="alice", trigger="PostConfirmation_ConfirmSignUp"):
    return {"userName": username, "triggerSource": trigger, "request": {}}


def test_ignores_forgot_password_confirmation():
    _reset()
    event = _event(trigger="PostConfirmation_ConfirmForgotPassword")
    assert post_confirmation.handler(event, None) is event
    assert _fake_glue.create_calls == []
    assert _fake_lf.grant_calls == []
    assert _fake_lf.tag_calls == []


def test_signup_creates_database_named_as_username_verbatim():
    _reset()
    post_confirmation.handler(_event(username="alice_42"), None)
    assert len(_fake_glue.create_calls) == 1
    assert _fake_glue.create_calls[0]["DatabaseInput"]["Name"] == "alice_42"


def test_signup_grants_portal_role_db_and_table_permissions():
    _reset()
    post_confirmation.handler(_event(username="alice"), None)
    assert len(_fake_lf.grant_calls) == 2

    db_grant, table_grant = _fake_lf.grant_calls
    # Both grants target the shared portal role.
    for grant in (db_grant, table_grant):
        assert grant["Principal"]["DataLakePrincipalIdentifier"] == PORTAL_ROLE_ARN

    assert db_grant["Resource"]["Database"]["Name"] == "alice"
    assert db_grant["Permissions"] == ["DESCRIBE", "CREATE_TABLE", "ALTER", "DROP"]

    assert table_grant["Resource"]["Table"]["DatabaseName"] == "alice"
    assert table_grant["Resource"]["Table"]["TableWildcard"] == {}
    # Writes (INSERT) included; row-level DELETE deliberately not granted in v1.
    assert table_grant["Permissions"] == ["SELECT", "INSERT", "DESCRIBE", "ALTER", "DROP"]
    assert "DELETE" not in table_grant["Permissions"]


def test_signup_tags_database_portal_managed():
    _reset()
    post_confirmation.handler(_event(username="alice"), None)
    assert len(_fake_lf.tag_calls) == 1
    call = _fake_lf.tag_calls[0]
    assert call["Resource"]["Database"]["Name"] == "alice"
    assert call["LFTags"] == [{"TagKey": "portal-managed", "TagValues": ["true"]}]


def test_tag_failure_surfaces_but_after_the_portal_grant():
    _reset()
    _fake_lf.tag_failures = [{"LFTag": {"TagKey": "portal-managed"}, "Error": {"ErrorCode": "x"}}]
    # provision_user raises so the operator/backfill sees it (the trigger swallows it).
    try:
        post_confirmation.provision_user("alice")
        assert False, "expected provision_user to raise on a tag failure"
    except RuntimeError as exc:
        assert "portal-managed" in str(exc)
    # Tagging runs LAST, so the user's own portal-role grant already happened — a tag
    # failure costs only control-plane access (which backfill reconciles), never the
    # user's workspace grant.
    assert len(_fake_lf.grant_calls) == 2


def test_handler_never_blocks_signup_on_tag_failure():
    _reset()
    _fake_lf.tag_failures = [{"LFTag": {"TagKey": "portal-managed"}, "Error": {"ErrorCode": "x"}}]
    event = _event(username="alice")
    assert post_confirmation.handler(event, None) is event


def test_already_existing_database_is_tolerated_and_still_grants():
    _reset()
    _fake_glue.raise_already_exists = True
    # Must not raise; grants still issued (idempotent re-provision).
    post_confirmation.handler(_event(username="alice"), None)
    assert len(_fake_lf.grant_calls) == 2


def test_handler_never_blocks_signup_on_aws_error():
    _reset()
    _fake_lf.raise_error = RuntimeError("transient LF failure")
    event = _event(username="alice")
    # Handler swallows the error and returns the event so sign-up completes.
    assert post_confirmation.handler(event, None) is event


def test_backfill_reuses_provision_user():
    _reset()
    rc = backfill.main(["backfill.py", "alice", "bob"])
    assert rc == 0
    created = [c["DatabaseInput"]["Name"] for c in _fake_glue.create_calls]
    assert created == ["alice", "bob"]
    assert len(_fake_lf.grant_calls) == 4  # 2 grants per user


def test_backfill_requires_a_username():
    _reset()
    assert backfill.main(["backfill.py"]) == 2


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok - {fn.__name__}")
    print(f"\n{len(fns)} passed")
