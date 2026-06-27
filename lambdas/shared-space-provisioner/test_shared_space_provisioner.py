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

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for (b, k) in self.store if b == Bucket and k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def delete_objects(self, Bucket, Delete):
        for obj in Delete.get("Objects", []):
            self.store.pop((Bucket, obj["Key"]), None)
        return {}

    def delete_object(self, Bucket, Key):
        self.store.pop((Bucket, Key), None)
        return {}


class FakeEntityNotFound(Exception):
    pass


class FakeGlue:
    def __init__(self):
        self.created = []
        self.databases = set()
        self.tables = {}  # db name -> [table names]
        self.exceptions = types.SimpleNamespace(
            AlreadyExistsException=FakeAlreadyExists, EntityNotFoundException=FakeEntityNotFound
        )

    def create_database(self, DatabaseInput):
        name = DatabaseInput["Name"]
        self.created.append(name)
        self.databases.add(name)
        self.tables.setdefault(name, [])

    def get_tables(self, DatabaseName, NextToken=None):
        if DatabaseName not in self.databases:
            raise FakeEntityNotFound()
        return {"TableList": [{"Name": t} for t in self.tables.get(DatabaseName, [])]}

    def batch_delete_table(self, DatabaseName, TablesToDelete):
        remaining = [t for t in self.tables.get(DatabaseName, []) if t not in TablesToDelete]
        self.tables[DatabaseName] = remaining

    def delete_database(self, Name):
        if Name not in self.databases:
            raise FakeEntityNotFound()
        self.databases.discard(Name)
        self.tables.pop(Name, None)


class FakeLF:
    def __init__(self):
        self.grants = []
        self.revokes = []

    def grant_permissions(self, Principal, Resource, Permissions):
        self.grants.append((Resource, Permissions))

    def revoke_permissions(self, Principal, Resource, Permissions):
        self.revokes.append((Resource, Permissions))


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


# ── leave / delete verbs (SPEC-054) ──────────────────────────────────────────
def _seed_full_space(s3, glue, cognito, name="sales", members=("alice", "bob")):
    """Seed a fully-provisioned shared space: registry, shared objects (marker +
    data + an athenaresults entry), Glue DB + tables, and each member's slot +
    cache entry. The first member is the owner."""
    owner = members[0]
    _seed_reg(s3, _active_reg(name=name, owner=owner, members=list(members)))
    s3.store[("shared-bkt", f"{name}/DO_NOT_DELETE.txt")] = b"marker"
    s3.store[("shared-bkt", f"{name}/data/file.csv")] = b"data"
    s3.store[("shared-bkt", f"{name}/athenaresults/alice/q.csv")] = b"result"
    glue.databases.add(name)
    glue.tables[name] = ["t1", "t2"]
    cognito.users = {}
    for m in members:
        cognito.users[m] = {"custom:shared_space_1": name}
        role = "owner" if m == owner else "member"
        s3.store[("user-bkt", f"{m}/user_settings/shared-connections.json")] = json.dumps(
            {"version": 1, "connections": [{"name": name, "role": role, "status": "active"}]}
        ).encode()


def test_leave_clears_slot_cache_registry_and_owner_projection_leaves_data():
    s3, glue, lf, cognito = _install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    out = p.leave_space("sales", "bob", "req-l", reg)
    assert out["left"] is True
    # bob's slot + cache cleared; registry membership + owner projection updated.
    assert cognito.users["bob"]["custom:shared_space_1"] == ""
    bob_cache = json.loads(s3.store[("user-bkt", "bob/user_settings/shared-connections.json")])
    assert bob_cache["connections"] == []
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg2["members"] == ["alice"]
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert owner_cache["connections"][0]["members"] == ["alice"]
    # shared objects, DB + tables, and the owner are untouched.
    assert ("shared-bkt", "sales/DO_NOT_DELETE.txt") in s3.store
    assert ("shared-bkt", "sales/data/file.csv") in s3.store
    assert "sales" in glue.databases and glue.tables["sales"] == ["t1", "t2"]


def test_leave_idempotent_for_non_member():
    s3, glue, lf, cognito = _install()
    _seed_full_space(s3, glue, cognito, members=("alice",))  # only the owner
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    out = p.leave_space("sales", "carol", "req-l", reg)  # carol never joined
    assert out["left"] is False
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg2["members"] == ["alice"]  # unchanged


def test_leave_defensive_owner_guard():
    s3, glue, lf, cognito = _install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    _raises(lambda: p.leave_space("sales", "alice", "req-l", reg), p.AuthorizationError, "owner cannot leave")


def test_delete_cascades_files_tables_db_members_and_registry_frees_name():
    s3, glue, lf, cognito = _install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    out = p.delete_space("sales", "alice", "req-d", reg)
    assert out["status"] == "ok" and set(out["revokedMembers"]) == {"alice", "bob"}
    # All shared objects gone.
    assert not any(b == "shared-bkt" and k.startswith("sales/") for (b, k) in s3.store)
    # DB + tables dropped; LF grant revoked (DB + table wildcard).
    assert "sales" not in glue.databases and "sales" not in glue.tables
    assert len(lf.revokes) == 2
    # Every member's slot + cache entry cleared.
    for m in ("alice", "bob"):
        assert cognito.users[m]["custom:shared_space_1"] == ""
        cache = json.loads(s3.store[("user-bkt", f"{m}/user_settings/shared-connections.json")])
        assert cache["connections"] == []
    # Registry object removed LAST -> the name is free to reuse.
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store


def test_delete_idempotent_tolerant_of_partial_prior_progress():
    s3, glue, lf, cognito = _install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    # Simulate a prior partial run: DB already dropped, shared objects already gone.
    glue.databases.discard("sales")
    glue.tables.pop("sales", None)
    for key in [k for (b, k) in list(s3.store) if b == "shared-bkt"]:
        s3.store.pop(("shared-bkt", key), None)

    out = p.delete_space("sales", "alice", "req-d", reg)  # completes without error
    assert out["status"] == "ok"
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store
    for m in ("alice", "bob"):
        assert cognito.users[m]["custom:shared_space_1"] == ""


def test_delete_records_failure_and_reraises_without_deleting_registry():
    s3, glue, lf, cognito = _install()
    _seed_full_space(s3, glue, cognito)
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    orig = p._drop_database
    try:
        def boom(name):
            raise RuntimeError("glue throttled")

        p._drop_database = boom
        _raises(lambda: p.delete_space("sales", "alice", "req-d", reg), RuntimeError, "throttled")
    finally:
        p._drop_database = orig
    # Registry survives with a terminal failed status + reason (recoverable retry).
    saved = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert saved["status"] == "failed" and "throttled" in saved["reason"]
    owner_cache = json.loads(s3.store[("user-bkt", "alice/user_settings/shared-connections.json")])
    assert owner_cache["connections"][0]["status"] == "failed"


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


def _simple_event(action, space, request_id="r1"):
    body = {
        "schemaVersion": 1,
        "requestId": request_id,
        "action": action,
        "actor": "x",
        "space": space,
        "idToken": "tok",
    }
    return [{"body": json.dumps(body)}]


def test_handler_leave_runs_verb_for_member():
    s3, glue, lf, cognito = _install()
    _seed_full_space(s3, glue, cognito)
    orig = p.verified_username
    try:
        p.verified_username = lambda tok: "bob"  # a member, not the owner
        out = p.handler(_simple_event("leave", "sales"), None)
        assert out["left"] is True
    finally:
        p.verified_username = orig
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg["members"] == ["alice"]
    assert ("shared-bkt", "sales/DO_NOT_DELETE.txt") in s3.store  # data intact


def test_handler_owner_leave_fails_with_no_effect():
    s3, glue, lf, cognito = _install()
    _seed_full_space(s3, glue, cognito)
    orig = p.verified_username
    try:
        p.verified_username = lambda tok: "alice"  # the owner
        _raises(
            lambda: p.handler(_simple_event("leave", "sales"), None),
            p.AuthorizationError,
            "owner cannot leave",
        )
    finally:
        p.verified_username = orig
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert set(reg["members"]) == {"alice", "bob"}  # unchanged


def test_handler_delete_runs_verb_for_owner():
    s3, glue, lf, cognito = _install()
    _seed_full_space(s3, glue, cognito)
    orig = p.verified_username
    try:
        p.verified_username = lambda tok: "alice"  # the owner
        out = p.handler(_simple_event("delete", "sales"), None)
        assert out["status"] == "ok"
    finally:
        p.verified_username = orig
    assert ("admin-bkt", "shared-spaces/sales.json") not in s3.store
    assert "sales" not in glue.databases


def test_handler_non_owner_delete_fails_with_no_effect():
    s3, glue, lf, cognito = _install()
    _seed_full_space(s3, glue, cognito)
    orig = p.verified_username
    try:
        p.verified_username = lambda tok: "bob"  # a member, not the owner
        _raises(
            lambda: p.handler(_simple_event("delete", "sales"), None),
            p.AuthorizationError,
            "owner-only",
        )
    finally:
        p.verified_username = orig
    # Nothing torn down: registry, DB, and shared objects intact.
    assert ("admin-bkt", "shared-spaces/sales.json") in s3.store
    assert "sales" in glue.databases
    assert ("shared-bkt", "sales/DO_NOT_DELETE.txt") in s3.store


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
