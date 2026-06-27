"""Unit tests for the shared-space provisioner (SPEC-056 validate + SPEC-051 create).

Runs under pytest *or* as a plain script (`python3 test_shared_space_provisioner.py`);
the JS CI does not run Python. Token verification (PyJWT/JWKS) and the AWS clients are
faked — these cover the security core (authorize() + actor binding) and the create
verb (uniqueness, slot allocation, grants, cache, idempotency, failure recording).
"""

import json
import types

import shared_space_provisioner as p


def _raises(fn, exc_type, match=None):
    try:
        fn()
    except exc_type as exc:
        if match is not None:
            assert match in str(exc), f"expected {match!r} in {str(exc)!r}"
        return
    raise AssertionError(f"expected {exc_type.__name__}, none raised")


# ── Fakes ────────────────────────────────────────────────────────────────────
class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeNoSuchKey(Exception):
    pass


class FakeAlreadyExists(Exception):
    pass


class _Body:
    def __init__(self, data):
        self._d = data

    def read(self):
        return self._d


class FakeS3:
    def __init__(self):
        self.store = {}
        self.exceptions = types.SimpleNamespace(
            NoSuchKey=FakeNoSuchKey, ClientError=FakeClientError
        )

    def get_object(self, Bucket, Key):
        if (Bucket, Key) in self.store:
            return {"Body": _Body(self.store[(Bucket, Key)])}
        raise FakeNoSuchKey()

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, **kw):
        if IfNoneMatch == "*" and (Bucket, Key) in self.store:
            raise FakeClientError("PreconditionFailed")
        self.store[(Bucket, Key)] = Body if isinstance(Body, (bytes, bytearray)) else Body.encode()
        return {}


class FakeGlue:
    def __init__(self):
        self.created = []
        self.exceptions = types.SimpleNamespace(AlreadyExistsException=FakeAlreadyExists)

    def create_database(self, DatabaseInput):
        self.created.append(DatabaseInput["Name"])


class FakeLF:
    def __init__(self):
        self.grants = []

    def grant_permissions(self, Principal, Resource, Permissions):
        self.grants.append((Resource, Permissions))


class FakeCognito:
    def __init__(self, attrs=None):
        self.attrs = dict(attrs or {})
        self.updates = []

    def admin_get_user(self, UserPoolId, Username):
        return {"UserAttributes": [{"Name": n, "Value": v} for n, v in self.attrs.items()]}

    def admin_update_user_attributes(self, UserPoolId, Username, UserAttributes):
        for a in UserAttributes:
            self.attrs[a["Name"]] = a["Value"]
        self.updates.append(UserAttributes)


def _install(cognito_attrs=None, max_memberships=10):
    p._s3 = FakeS3()
    p._glue = FakeGlue()
    p._lf = FakeLF()
    p._cognito = FakeCognito(cognito_attrs)
    p.MAX_SHARED_MEMBERSHIPS = max_memberships
    p.ADMIN_BUCKET = "admin-bkt"
    p.SHARED_SPACE_BUCKET = "shared-bkt"
    p.USER_SPACE_BUCKET = "user-bkt"
    p.PORTAL_ROLE_ARN = "arn:aws:iam::1:role/portal"
    p.USER_POOL_ID = "pool"
    return p._s3, p._glue, p._lf, p._cognito


# ── authorize() (SPEC-056) ───────────────────────────────────────────────────
REG = {"name": "sales", "owner": "alice", "members": ["alice", "bob"], "status": "active"}


def test_create_allowed_for_any_actor():
    assert p.authorize("create", "sales", "zoe", None) is None


def test_owner_only_denies_non_owner():
    _raises(lambda: p.authorize("delete", "sales", "bob", REG), p.AuthorizationError, "owner-only")


def test_leave_denied_for_owner_and_non_member():
    _raises(lambda: p.authorize("leave", "sales", "alice", REG), p.AuthorizationError, "owner cannot leave")
    _raises(lambda: p.authorize("leave", "sales", "mallory", REG), p.AuthorizationError, "not a member")


def test_leave_allowed_for_member():
    assert p.authorize("leave", "sales", "bob", REG) is None


def test_unknown_action_rejected():
    _raises(lambda: p.authorize("nuke", "sales", "alice", REG), p.AuthorizationError, "unknown action")


# ── create verb (SPEC-051) ───────────────────────────────────────────────────
def test_create_happy_path_provisions_everything():
    s3, glue, lf, cognito = _install()
    out = p.create_space("sales", "alice", "req-1")
    assert out["status"] == "active"
    # Glue DB created, LF granted (DB + tables), creator slot assigned.
    assert glue.created == ["sales"]
    assert len(lf.grants) == 2
    assert cognito.attrs["custom:shared_space_1"] == "sales"
    # Registry finalized active.
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg["status"] == "active" and reg["owner"] == "alice"
    # Marker written + per-user cache entry active.
    assert ("shared-bkt", "sales/DO_NOT_DELETE.txt") in s3.store
    cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert cache["connections"] == [{"name": "sales", "role": "owner", "status": "active"}]


def test_create_name_collision_fails():
    s3, *_ = _install()
    # A different request already owns the name.
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "bob", "lastRequestId": "other", "status": "active"}
    ).encode()
    _raises(lambda: p.create_space("sales", "alice", "req-1"), p.ProvisioningError, "name already taken")


def test_create_replay_same_request_is_idempotent():
    s3, glue, *_ = _install()
    # Prior successful run wrote an active registry with this requestId.
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "alice", "lastRequestId": "req-1", "status": "active"}
    ).encode()
    out = p.create_space("sales", "alice", "req-1")
    assert out["status"] == "active" and out.get("replay") is True
    assert glue.created == []  # no double-provision


def test_create_slot_full_fails_and_records_failure():
    s3, glue, lf, cognito = _install(
        cognito_attrs={"custom:shared_space_1": "a", "custom:shared_space_2": "b"},
        max_memberships=2,
    )
    _raises(lambda: p.create_space("sales", "alice", "req-1"), p.ProvisioningError, "membership limit reached")
    # Registry + cache record the failure with a reason; no DB/grant happened.
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg["status"] == "failed" and "membership limit" in reg["reason"]
    cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert cache["connections"][0]["status"] == "failed"
    assert glue.created == []


def test_create_slot_assignment_is_replay_safe():
    # Creator already holds this space in slot 2 (a prior run) -> reuse it.
    _install(cognito_attrs={"custom:shared_space_2": "sales"})
    s3 = p._s3
    s3.store[("admin-bkt", "shared-spaces/sales.json")] = json.dumps(
        {"name": "sales", "owner": "alice", "lastRequestId": "req-1", "status": "provisioning"}
    ).encode()
    out = p.create_space("sales", "alice", "req-1")  # replay (provisioning -> re-run steps)
    assert out["status"] == "active"
    assert p._cognito.attrs["custom:shared_space_2"] == "sales"
    assert "custom:shared_space_1" not in p._cognito.attrs  # didn't grab a new slot


# ── handler() flow ───────────────────────────────────────────────────────────
def _event(action="create", space="sales", token="tok"):
    body = {"schemaVersion": 1, "requestId": "r1", "action": action, "actor": "x", "space": space, "idToken": token}
    return [{"body": json.dumps(body)}]


def test_handler_create_runs_verb_with_token_actor():
    _install()
    orig = p.verified_username
    try:
        p.verified_username = lambda tok: "alice"
        out = p.handler(_event(action="create", space="sales"), None)
        assert out["status"] == "active" and out["owner"] == "alice"
    finally:
        p.verified_username = orig


def test_handler_forged_token_rejected_before_any_verb():
    s3, glue, *_ = _install()
    orig = p.verified_username
    try:
        def boom(tok):
            raise p.AuthorizationError("token verification failed")
        p.verified_username = boom
        _raises(lambda: p.handler(_event(action="create"), None), p.AuthorizationError, "verification failed")
        assert glue.created == [] and s3.store == {}  # nothing provisioned
    finally:
        p.verified_username = orig


def test_handler_bad_schema_version_rejected():
    _raises(
        lambda: p.handler([{"body": json.dumps({"schemaVersion": 99, "action": "create"})}], None),
        p.AuthorizationError,
        "schemaVersion",
    )


if __name__ == "__main__":
    import sys

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} shared_space_provisioner tests passed.")
    sys.exit(0)
