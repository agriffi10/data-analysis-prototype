"""In-memory AWS test doubles plus an install helper for the common and verb suites.

Not packaged into the Lambda layer — the layer build copies only the production modules by
name, so this file and the test modules never ship. Token verification is faked by patching the
auth module's entry point; the AWS clients are faked here and installed onto the cached client
globals.
"""

import types

from cpcommon import clients
from cpcommon import config as cpconfig

import config


def raises(fn, exc_type, match=None):
    """Asserts that calling a function raises the expected exception.

    Args:
      fn: The zero-argument callable to invoke.
      exc_type: The exception type expected.
      match: Optional substring the message must contain.

    Returns:
      None.

    Raises:
      AssertionError: When nothing was raised, or the message does not contain the substring.
    """
    try:
        fn()
    except exc_type as exc:
        if match is not None:
            assert match in str(exc), f"expected {match!r} in {str(exc)!r}"
        return
    raise AssertionError(f"expected {exc_type.__name__}, none raised")


class FakeClientError(Exception):
    """A botocore-shaped client error carrying a code the production classifiers read.

    Attributes:
      response: The error envelope, shaped like botocore's.
    """

    def __init__(self, code):
        """Wraps one error code in the botocore response shape.

        Args:
          code: The error code.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeNoSuchKey(Exception):
    """Stands in for S3's missing-key exception."""


class FakeAlreadyExists(Exception):
    """Stands in for Glue's already-exists exception."""


class FakeEntityNotFound(Exception):
    """Stands in for Glue's entity-not-found exception."""


class FakeUserNotFound(Exception):
    """Stands in for Cognito's user-not-found exception."""


class _Body:
    """A minimal streaming-body stand-in returned by the fake S3 client."""

    def __init__(self, data):
        """Holds the bytes this body will yield.

        Args:
          data: The body bytes.

        Returns:
          None.

        Raises:
          None.
        """
        self._d = data

    def read(self):
        """Returns the whole body.

        Args:
          None.

        Returns:
          The body bytes.

        Raises:
          None.
        """
        return self._d


class FakeS3:
    """An in-memory S3 client supporting conditional writes and paginated listing.

    Attributes:
      store: Object bytes keyed by bucket and key.
      etags: Entity tags keyed the same way, for conditional-write tests.
      undeletable: Keys the batch delete reports as failed instead of deleting.
      page_size: Keys per listing page. Deliberately tiny so ordinary fixtures paginate and the
        continuation branches in the teardown helpers execute in every test that tears a space
        down, not only in the purpose-built multi-page ones.
      exceptions: The exception namespace production code catches on.
    """

    def __init__(self):
        """Creates an empty store.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.store = {}
        self.etags = {}
        self.undeletable = set()
        self.page_size = 2
        self._seq = 0
        self.exceptions = types.SimpleNamespace(
            NoSuchKey=FakeNoSuchKey, ClientError=FakeClientError
        )

    def _next_etag(self):
        """Mints a monotonically increasing entity tag.

        Args:
          None.

        Returns:
          The new tag.

        Raises:
          None.
        """
        self._seq += 1
        return f'"etag-{self._seq}"'

    def get_object(self, Bucket, Key):
        """Reads one object, stamping a tag lazily for directly-seeded objects.

        Lazy stamping means objects seeded straight into the store, rather than through a write,
        still participate in conditional writes.

        Args:
          Bucket: The bucket.
          Key: The object key.

        Returns:
          A response carrying the body and its tag.

        Raises:
          FakeNoSuchKey: When the object is absent.
        """
        if (Bucket, Key) in self.store:
            if (Bucket, Key) not in self.etags:
                self.etags[(Bucket, Key)] = self._next_etag()
            return {"Body": _Body(self.store[(Bucket, Key)]), "ETag": self.etags[(Bucket, Key)]}
        raise FakeNoSuchKey()

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
        """Writes one object, enforcing either conditional-write precondition.

        Args:
          Bucket: The bucket.
          Key: The object key.
          Body: The bytes or string to store.
          IfNoneMatch: Write only if the object is absent.
          IfMatch: Write only if the tag matches.
          **kw: Other parameters, accepted and ignored.

        Returns:
          An empty response.

        Raises:
          FakeClientError: On a precondition failure.
        """
        exists = (Bucket, Key) in self.store
        if IfNoneMatch == "*" and exists:
            raise FakeClientError("PreconditionFailed")
        if IfMatch is not None and self.etags.get((Bucket, Key)) != IfMatch:
            raise FakeClientError("PreconditionFailed")
        self.store[(Bucket, Key)] = Body if isinstance(Body, (bytes, bytearray)) else Body.encode()
        self.etags[(Bucket, Key)] = self._next_etag()
        return {}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        """Lists a prefix one page at a time.

        The token is the last key of the page returned — a start-after marker over lexicographic
        order rather than an offset. That matters because the only caller deletes each page
        before asking for the next one, so an offset-based token would skip the keys that
        shifted down, which is precisely the bug a fake ignoring the token could never surface.

        Args:
          Bucket: The bucket.
          Prefix: The prefix to list.
          ContinuationToken: The last key of the previous page.

        Returns:
          A response with the page's keys, a truncation flag, and the next token when truncated.

        Raises:
          None.
        """
        keys = sorted(k for (b, k) in self.store if b == Bucket and k.startswith(Prefix))
        if ContinuationToken is not None:
            keys = [k for k in keys if k > ContinuationToken]
        page, truncated = keys[: self.page_size], len(keys) > self.page_size
        response = {"Contents": [{"Key": k} for k in page], "IsTruncated": truncated}
        if truncated:
            response["NextContinuationToken"] = page[-1]
        return response

    def delete_objects(self, Bucket, Delete):
        """Deletes a batch of objects, reporting the undeletable ones as per-key errors.

        S3 returns success with a per-key error array rather than raising, which is the whole
        reason this behaviour is modelled: the real failure mode is a teardown that looks like it
        worked. A fake that could only fully succeed cannot express it, and a test written
        against that fake would pass against the bug.

        Args:
          Bucket: The bucket.
          Delete: The delete request, carrying the objects.

        Returns:
          A response carrying the errors, or an empty one — mirroring S3, where the key is absent
          unless something failed.

        Raises:
          None.
        """
        errors = []
        for obj in Delete.get("Objects", []):
            key = obj["Key"]
            if key in self.undeletable:
                errors.append({"Key": key, "Code": "AccessDenied", "Message": "denied"})
                continue
            self.store.pop((Bucket, key), None)
            self.etags.pop((Bucket, key), None)
        return {"Errors": errors} if errors else {}

    def delete_object(self, Bucket, Key):
        """Deletes one object.

        Args:
          Bucket: The bucket.
          Key: The object key.

        Returns:
          An empty response.

        Raises:
          None.
        """
        self.store.pop((Bucket, Key), None)
        self.etags.pop((Bucket, Key), None)
        return {}


class FakeGlue:
    """An in-memory Glue client supporting paginated listing and partial-failure drops.

    Attributes:
      created: Database names in creation order.
      databases: The live database names.
      tables: Table names by database.
      undroppable: Tables the batch drop reports as failed instead of dropping.
      page_size: Tables per listing page, tiny for the same reason as the S3 fake's.
      exceptions: The exception namespace production code catches on.
    """

    def __init__(self):
        """Creates an empty catalog.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.created = []
        self.databases = set()
        self.tables = {}
        self.undroppable = set()
        self.page_size = 2
        self.exceptions = types.SimpleNamespace(
            AlreadyExistsException=FakeAlreadyExists, EntityNotFoundException=FakeEntityNotFound
        )

    def create_database(self, DatabaseInput):
        """Creates a database.

        Args:
          DatabaseInput: The input, carrying the name.

        Returns:
          None.

        Raises:
          None.
        """
        name = DatabaseInput["Name"]
        self.created.append(name)
        self.databases.add(name)
        self.tables.setdefault(name, [])

    def get_tables(self, DatabaseName, NextToken=None):
        """Lists a database's tables one page at a time.

        The token is an offset into the catalog's own order, which is faithful here where it
        would not be for S3: the caller collects every page before deleting anything, so nothing
        shifts underneath the walk. The token is omitted from the last page, which is what the
        caller's loop exit depends on.

        Args:
          DatabaseName: The database to list.
          NextToken: The offset from the previous page.

        Returns:
          A response with the page's tables, and the next token when more remain.

        Raises:
          FakeEntityNotFound: When the database does not exist.
        """
        if DatabaseName not in self.databases:
            raise FakeEntityNotFound()
        tables = self.tables.get(DatabaseName, [])
        start = int(NextToken or 0)
        page = tables[start : start + self.page_size]
        response = {"TableList": [{"Name": t} for t in page]}
        if start + self.page_size < len(tables):
            response["NextToken"] = str(start + self.page_size)
        return response

    def batch_delete_table(self, DatabaseName, TablesToDelete):
        """Drops a batch of tables, reporting the undroppable ones as per-table errors.

        The same partial-failure shape as the S3 batch delete: success with an error array.

        Args:
          DatabaseName: The database.
          TablesToDelete: The table names to drop.

        Returns:
          A response carrying the errors, or an empty one.

        Raises:
          None.
        """
        errors = [
            {"TableName": t, "ErrorDetail": {"ErrorCode": "AccessDeniedException"}}
            for t in TablesToDelete
            if t in self.undroppable
        ]
        remaining = [
            t
            for t in self.tables.get(DatabaseName, [])
            if t not in TablesToDelete or t in self.undroppable
        ]
        self.tables[DatabaseName] = remaining
        return {"Errors": errors} if errors else {}

    def delete_database(self, Name):
        """Deletes a database and forgets its tables.

        Args:
          Name: The database name.

        Returns:
          None.

        Raises:
          FakeEntityNotFound: When the database does not exist.
        """
        if Name not in self.databases:
            raise FakeEntityNotFound()
        self.databases.discard(Name)
        self.tables.pop(Name, None)


class FakeLF:
    """An in-memory Lake Formation client recording grants, revokes and tag assignments.

    Attributes:
      grants: The resource and permission pairs granted.
      revokes: The resource and permission pairs revoked.
      lf_tags: The resource and tag pairs assigned.
      tag_failures: Failures the tag assignment reports back, for partial-failure tests.
    """

    def __init__(self):
        """Creates an empty recorder.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.grants = []
        self.revokes = []
        self.lf_tags = []
        self.tag_failures = []

    def grant_permissions(self, Principal, Resource, Permissions):
        """Records a grant.

        Args:
          Principal: The principal, unused.
          Resource: The resource granted on.
          Permissions: The permissions granted.

        Returns:
          None.

        Raises:
          None.
        """
        self.grants.append((Resource, Permissions))

    def revoke_permissions(self, Principal, Resource, Permissions):
        """Records a revoke.

        Args:
          Principal: The principal, unused.
          Resource: The resource revoked on.
          Permissions: The permissions revoked.

        Returns:
          None.

        Raises:
          None.
        """
        self.revokes.append((Resource, Permissions))

    def add_lf_tags_to_resource(self, Resource, LFTags):
        """Records a tag assignment and reports the configured failures.

        Args:
          Resource: The resource tagged.
          LFTags: The tags assigned.

        Returns:
          A response carrying the configured failures.

        Raises:
          None.
        """
        self.lf_tags.append((Resource, LFTags))
        return {"Failures": list(self.tag_failures)}


class FakeCognito:
    """An in-memory Cognito client with two modes.

    Single-user mode, for the create tests, maps every username to one attribute bag. Multi-user
    mode, for the add and remove tests, only recognises the usernames listed.

    Attributes:
      users: Attribute bags by username. Non-empty selects multi-user mode.
      updates: The attribute updates applied, in order.
      exceptions: The exception namespace production code catches on.
    """

    def __init__(self, attrs=None):
        """Creates a client in single-user mode with the given attribute bag.

        Args:
          attrs: The single-user attribute bag, or None for an empty one.

        Returns:
          None.

        Raises:
          None.
        """
        self._default = dict(attrs or {})
        self.users = {}
        self.updates = []
        self.exceptions = types.SimpleNamespace(UserNotFoundException=FakeUserNotFound)

    @property
    def attrs(self):
        """Returns the single-user attribute bag.

        Args:
          None.

        Returns:
          The attribute bag.

        Raises:
          None.
        """
        return self._default

    def _bucket(self, username):
        """Selects the attribute bag for one username, honouring the current mode.

        Args:
          username: The user to look up.

        Returns:
          The attribute bag, or None when multi-user mode does not list the user.

        Raises:
          None.
        """
        if self.users:
            return self.users.get(username)
        return self._default

    def admin_get_user(self, UserPoolId, Username):
        """Reads one user's attributes.

        Args:
          UserPoolId: The pool, unused.
          Username: The user to read.

        Returns:
          A response carrying the attribute list.

        Raises:
          FakeUserNotFound: When the user does not exist.
        """
        bucket = self._bucket(Username)
        if bucket is None:
            raise FakeUserNotFound()
        return {"UserAttributes": [{"Name": n, "Value": v} for n, v in bucket.items()]}

    def admin_update_user_attributes(self, UserPoolId, Username, UserAttributes):
        """Applies attribute updates to one user and records them.

        Args:
          UserPoolId: The pool, unused.
          Username: The user to update.
          UserAttributes: The attributes to set.

        Returns:
          None.

        Raises:
          FakeUserNotFound: When the user does not exist.
        """
        bucket = self._bucket(Username)
        if bucket is None:
            raise FakeUserNotFound()
        for a in UserAttributes:
            bucket[a["Name"]] = a["Value"]
        self.updates.append((Username, UserAttributes))


class FakeSqs:
    """An in-memory SQS client recording every send.

    Attributes:
      sent: The send arguments, in order.
    """

    def __init__(self):
        """Creates an empty recorder.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.sent = []

    def send_message(self, **kwargs):
        """Records one send.

        Args:
          **kwargs: The send arguments.

        Returns:
          A response carrying a fixed message id.

        Raises:
          None.
        """
        self.sent.append(kwargs)
        return {"MessageId": "m-fake"}


def install(cognito_attrs=None, max_memberships=10):
    """Installs fresh fakes and canonical configuration onto the cached globals.

    The buckets, the pool and the queue URL live in the shared config — one definition, so this
    is the one place they are patched. The conftest's snapshot fixture undoes it after each test,
    which it could not do while this layer kept its own copies. The queue URL is left unset, so
    notifications are a no-op by default.

    Args:
      cognito_attrs: The single-user attribute bag for the fake Cognito client.
      max_memberships: The membership cap to install.

    Returns:
      The S3, Glue, Lake Formation and Cognito fakes, for assertions.

    Raises:
      None.
    """
    clients._s3 = FakeS3()
    clients._glue = FakeGlue()
    clients._lf = FakeLF()
    clients._cognito = FakeCognito(cognito_attrs)
    clients._sqs = FakeSqs()
    config.MAX_SHARED_MEMBERSHIPS = max_memberships
    config.PORTAL_ROLE_ARN = "arn:aws:iam::1:role/portal"
    cpconfig.ADMIN_BUCKET = "admin-bkt"
    cpconfig.SHARED_SPACE_BUCKET = "shared-bkt"
    cpconfig.USER_SPACE_BUCKET = "user-bkt"
    cpconfig.NOTIFICATIONS_QUEUE_URL = ""
    return clients._s3, clients._glue, clients._lf, clients._cognito
