"""In-memory AWS test doubles plus an install() helper for the common and verb suites.

Not packaged into the Lambda layer — the layer build copies only the production
modules by name, so this file and the ``test_*.py`` files never ship. Token
verification (PyJWT/JWKS) is faked by patching ``auth.verified_username``; the AWS
clients are faked here and installed onto ``clients._<name>``.
"""

import types

import config
from cpcommon import clients
from cpcommon import config as cpconfig


def raises(fn, exc_type, match=None):
    """Assert that ``fn()`` raises ``exc_type`` (optionally with ``match`` in the message)."""
    try:
        fn()
    except exc_type as exc:
        if match is not None:
            assert match in str(exc), f"expected {match!r} in {str(exc)!r}"
        return
    raise AssertionError(f"expected {exc_type.__name__}, none raised")


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeNoSuchKey(Exception):
    pass


class FakeAlreadyExists(Exception):
    pass


class FakeEntityNotFound(Exception):
    pass


class FakeUserNotFound(Exception):
    pass


class _Body:
    def __init__(self, data):
        self._d = data

    def read(self):
        return self._d


class FakeS3:
    def __init__(self):
        self.store = {}
        self.etags = {}  # (Bucket, Key) -> ETag, for conditional-write (CAS) tests
        self._seq = 0
        self.exceptions = types.SimpleNamespace(
            NoSuchKey=FakeNoSuchKey, ClientError=FakeClientError
        )

    def _next_etag(self):
        self._seq += 1
        return f'"etag-{self._seq}"'

    def get_object(self, Bucket, Key):
        if (Bucket, Key) in self.store:
            # Lazily stamp an ETag so objects seeded directly via ``store[...] = ...``
            # (not through put_object) still participate in If-Match writes.
            if (Bucket, Key) not in self.etags:
                self.etags[(Bucket, Key)] = self._next_etag()
            return {"Body": _Body(self.store[(Bucket, Key)]), "ETag": self.etags[(Bucket, Key)]}
        raise FakeNoSuchKey()

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
        exists = (Bucket, Key) in self.store
        if IfNoneMatch == "*" and exists:
            raise FakeClientError("PreconditionFailed")
        if IfMatch is not None and self.etags.get((Bucket, Key)) != IfMatch:
            raise FakeClientError("PreconditionFailed")
        self.store[(Bucket, Key)] = Body if isinstance(Body, (bytes, bytearray)) else Body.encode()
        self.etags[(Bucket, Key)] = self._next_etag()
        return {}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for (b, k) in self.store if b == Bucket and k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def delete_objects(self, Bucket, Delete):
        for obj in Delete.get("Objects", []):
            self.store.pop((Bucket, obj["Key"]), None)
            self.etags.pop((Bucket, obj["Key"]), None)
        return {}

    def delete_object(self, Bucket, Key):
        self.store.pop((Bucket, Key), None)
        self.etags.pop((Bucket, Key), None)
        return {}


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
        self.lf_tags = []
        self.tag_failures = []

    def grant_permissions(self, Principal, Resource, Permissions):
        self.grants.append((Resource, Permissions))

    def revoke_permissions(self, Principal, Resource, Permissions):
        self.revokes.append((Resource, Permissions))

    def add_lf_tags_to_resource(self, Resource, LFTags):
        self.lf_tags.append((Resource, LFTags))
        return {"Failures": list(self.tag_failures)}


class FakeCognito:
    """Fake Cognito with two modes.

    Single-user (create tests): pass ``attrs`` — every Username maps to that one
    attribute bag, exposed as ``.attrs``. Multi-user (add/remove tests): set
    ``.users = {username: {attr: val}}`` — any Username not listed raises
    UserNotFoundException.
    """

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


class FakeSqs:
    def __init__(self):
        self.sent = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "m-fake"}


def install(cognito_attrs=None, max_memberships=10):
    """Install fresh fakes and canonical config onto the cached client/config globals.

    Returns ``(s3, glue, lf, cognito)`` for assertions.
    """
    clients._s3 = FakeS3()
    clients._glue = FakeGlue()
    clients._lf = FakeLF()
    clients._cognito = FakeCognito(cognito_attrs)
    clients._sqs = FakeSqs()
    config.MAX_SHARED_MEMBERSHIPS = max_memberships
    config.PORTAL_ROLE_ARN = "arn:aws:iam::1:role/portal"
    # SPEC-125: the buckets, the pool and the queue URL now live in cpcommon.config —
    # ONE definition, so this is the one place they are patched. The conftest's
    # snapshot/restore fixture undoes it after each test, which it could not do while
    # this layer kept its own copies.
    cpconfig.ADMIN_BUCKET = "admin-bkt"
    cpconfig.SHARED_SPACE_BUCKET = "shared-bkt"
    cpconfig.USER_SPACE_BUCKET = "user-bkt"
    cpconfig.USER_POOL_ID = "pool"
    cpconfig.NOTIFICATIONS_QUEUE_URL = ""  # unset -> notify is a no-op
    return clients._s3, clients._glue, clients._lf, clients._cognito
