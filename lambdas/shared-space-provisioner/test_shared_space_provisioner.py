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


class FakeUserNotFound(Exception):
    pass


class FakeCognito:
    """Two modes. Single-user (create tests): pass ``attrs`` — every Username maps to
    that one attribute bag, exposed as ``.attrs``. Multi-user (add/remove tests): set
    ``.users = {username: {attr: val}}`` — any Username not listed is unknown and
    raises UserNotFoundException."""

    def __init__(self, attrs=None):
        self._default = dict(attrs or {})
        self.users = {}
        self.updates = []
        self.exceptions = types.SimpleNamespace(UserNotFoundException=FakeUserNotFound)

    @property
    def attrs(self):
        return self._default

    def _bucket(self, username):
        if self.users:  # multi-user mode: only listed users exist
            return self.users.get(username)
        return self._default  # single-user (create) mode

    def admin_get_user(self, UserPoolId, Username):
        bucket = self._bucket(Username)
        if bucket is None:
            raise FakeUserNotFound()
        return {"UserAttributes": [{"Name": n, "Value": v} for n, v in bucket.items()]}

    def admin_update_user_attributes(self, UserPoolId, Username, UserAttributes):
        bucket = self._bucket(Username)
        if bucket is None:
            raise FakeUserNotFound()
        for a in UserAttributes:
            bucket[a["Name"]] = a["Value"]
        self.updates.append((Username, UserAttributes))


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
    assert cache["connections"] == [
        {"name": "sales", "role": "owner", "status": "active", "members": ["alice"]}
    ]


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


# ── add_members / remove_members verbs (SPEC-053) ────────────────────────────
def _active_reg(name="sales", owner="alice", members=None):
    return {
        "name": name,
        "owner": owner,
        "members": members if members is not None else [owner],
        "status": "active",
        "createdAt": "t0",
        "lastRequestId": "r0",
    }


def _seed_reg(s3, reg):
    s3.store[("admin-bkt", f"shared-spaces/{reg['name']}.json")] = json.dumps(reg).encode()


def test_add_members_assigns_slot_registry_cache_and_owner_projection():
    s3, glue, lf, cognito = _install()
    cognito.users = {"bob": {}}  # bob exists with a free slot
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = p.add_members("sales", ["bob"], "req-2", reg)
    assert out["added"] == ["bob"]
    assert out["ignoredUnknown"] == [] and out["skippedAtLimit"] == []
    # bob got a slot + a member cache entry.
    assert cognito.users["bob"]["custom:shared_space_1"] == "sales"
    bob_cache = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])
    assert bob_cache["connections"] == [{"name": "sales", "role": "member", "status": "active"}]
    # registry members updated; owner projection carries the full member list.
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert set(reg2["members"]) == {"alice", "bob"} and reg2["owner"] == "alice"
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert owner_cache["connections"][0]["members"] == ["alice", "bob"]


def test_add_members_ignores_unknown_users_silently():
    s3, glue, lf, cognito = _install()
    cognito.users = {"bob": {}}  # "ghost" is not in the pool
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = p.add_members("sales", ["bob", "ghost"], "req-2", reg)
    assert out["added"] == ["bob"] and out["ignoredUnknown"] == ["ghost"]
    assert ("user-bkt", "ghost/user_settings/shared-connections.json") not in s3.store


def test_add_members_skips_at_limit_target_and_still_adds_others():
    s3, glue, lf, cognito = _install(max_memberships=2)
    cognito.users = {
        "full": {"custom:shared_space_1": "x", "custom:shared_space_2": "y"},
        "bob": {},
    }
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = p.add_members("sales", ["full", "bob"], "req-2", reg)
    assert out["skippedAtLimit"] == ["full"] and out["added"] == ["bob"]
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert set(reg2["members"]) == {"alice", "bob"}  # full not added


def test_add_members_idempotent_for_existing_member():
    s3, glue, lf, cognito = _install()
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}}
    reg = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg)

    out = p.add_members("sales", ["bob"], "req-2", reg)
    assert out["added"] == []  # already a member -> no-op
    assert cognito.updates == []  # no slot reassignment


def test_add_members_never_adds_the_owner():
    s3, glue, lf, cognito = _install()
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = p.add_members("sales", ["alice"], "req-2", reg)
    assert out["added"] == [] and out["ignoredUnknown"] == []


def test_remove_members_clears_slot_registry_and_cache_leaves_data():
    s3, glue, lf, cognito = _install()
    cognito.users = {"bob": {"custom:shared_space_1": "sales"}}
    reg = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg)
    s3.store[("user-bkt", "bob/user_settings/shared-connections.json")] = json.dumps(
        {"version": 1, "connections": [{"name": "sales", "role": "member", "status": "active"}]}
    ).encode()

    out = p.remove_members("sales", ["bob"], "req-3", reg)
    assert out["removed"] == ["bob"]
    assert cognito.users["bob"]["custom:shared_space_1"] == ""  # slot cleared
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg2["members"] == ["alice"]
    bob_cache = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])
    assert bob_cache["connections"] == []
    # owner projection reflects the removal; shared DB/marker untouched.
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert owner_cache["connections"][0]["members"] == ["alice"]
    assert glue.created == []


def test_remove_members_idempotent_for_non_member():
    s3, glue, lf, cognito = _install()
    cognito.users = {"bob": {}}
    reg = _active_reg(members=["alice"])
    _seed_reg(s3, reg)

    out = p.remove_members("sales", ["bob"], "req-3", reg)
    assert out["removed"] == []


def test_remove_members_never_removes_the_owner():
    s3, glue, lf, cognito = _install()
    reg = _active_reg(members=["alice", "bob"])
    _seed_reg(s3, reg)

    out = p.remove_members("sales", ["alice"], "req-3", reg)
    assert out["removed"] == []
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert "alice" in reg2["members"]


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


def _members_event(action, space, members, request_id="r1"):
    body = {
        "schemaVersion": 1,
        "requestId": request_id,
        "action": action,
        "actor": "x",
        "space": space,
        "idToken": "tok",
        "payload": {"members": members},
    }
    return [{"body": json.dumps(body)}]


def test_handler_add_members_runs_verb_for_owner():
    s3, glue, lf, cognito = _install()
    cognito.users = {"bob": {}}
    _seed_reg(s3, _active_reg(members=["alice"]))
    orig = p.verified_username
    try:
        p.verified_username = lambda tok: "alice"  # the owner
        out = p.handler(_members_event("add_members", "sales", ["bob"]), None)
        assert out["added"] == ["bob"]
    finally:
        p.verified_username = orig


def test_handler_add_members_non_owner_fails_with_no_effect():
    s3, glue, lf, cognito = _install()
    cognito.users = {"bob": {}}
    _seed_reg(s3, _active_reg(owner="alice", members=["alice"]))
    orig = p.verified_username
    try:
        p.verified_username = lambda tok: "mallory"  # not the owner
        _raises(
            lambda: p.handler(_members_event("add_members", "sales", ["bob"]), None),
            p.AuthorizationError,
            "owner-only",
        )
    finally:
        p.verified_username = orig
    # No slot assigned, registry unchanged.
    assert cognito.users["bob"] == {}
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg["members"] == ["alice"]


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
