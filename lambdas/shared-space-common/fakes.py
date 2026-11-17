"""In-memory AWS test doubles plus an install helper for the common and verb suites.

Not packaged into the Lambda layer — the layer build copies only the production modules by
name, so this file and the test modules never ship. Token verification is faked by patching the
auth module's entry point; the AWS clients are faked here and installed onto the cached client
globals.
"""

import types
import urllib.parse

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


class FakeParamValidation(Exception):
    """Stands in for botocore's ``ParamValidationError``.

    Raised before a request leaves the process, so it is not a service error and carries no code —
    which is why it fails a whole call rather than one item of a batch.
    """


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
      operations: Copies and single-object deletes, in the order they happened. Ordering is a
        requirement somewhere a snapshot of the store cannot show it: a copy confirmed before a
        delete and a delete that ran first leave identical stores and lose the file in one case.
      undeletable: Keys the batch delete reports as failed instead of deleting.
      storage_class: Per key, the storage class S3 would report. Absent means ``STANDARD``.
      content_type: Per key, the content type. Carried by a copy at ``MetadataDirective=COPY``.
      metadata: Per key, the user metadata. Carried by the same directive.
      tags: Per key, the tag set. Carried by ``TaggingDirective=COPY``.
      last_modified: Per key, the modification stamp a listing and a HEAD both report.
      sizes: Per key, an override for the reported size, so a test can plant an object larger
        than the multipart threshold without holding gigabytes of bytes in memory.
      uploads: In-flight multipart uploads, keyed by upload id.
      delete_identifiers: Every identifier a batch delete was handed, in order, so a test can
        assert the per-object ETag a conditional delete is supposed to send.
      copy_parameters: The keyword arguments of the most recent copy, so the directives a caller
        passed are assertable rather than inferred from the result.
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
        self.operations = []
        self.undeletable = set()
        self.page_size = 2
        self.storage_class = {}
        self.content_type = {}
        self.metadata = {}
        self.tags = {}
        self.last_modified = {}
        self.sizes = {}
        self.uploads = {}
        self.delete_identifiers = []
        self.copy_parameters = {}
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

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None, Delimiter=None, MaxKeys=None):
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
        if Delimiter:
            common = sorted(
                {
                    Prefix + k[len(Prefix) :].split(Delimiter, 1)[0] + Delimiter
                    for k in keys
                    if Delimiter in k[len(Prefix) :]
                }
            )
            flat = [k for k in keys if Delimiter not in k[len(Prefix) :]]
            return {
                "CommonPrefixes": [{"Prefix": p} for p in common],
                "Contents": [self._listed(Bucket, k) for k in flat],
                "IsTruncated": False,
            }
        limit = self.page_size if MaxKeys is None else min(self.page_size, MaxKeys)
        page, truncated = keys[:limit], len(keys) > limit
        # `Size` rides along because S3 always sends it and a caller may refuse an object on it
        # WITHOUT fetching it. A fake omitting it lets such a guard be written against a default
        # that real S3 never supplies, so the guard would be tested against a fiction.
        response = {
            "Contents": [self._listed(Bucket, k) for k in page],
            "IsTruncated": truncated,
        }
        if truncated:
            response["NextContinuationToken"] = page[-1]
        return response

    def _listed(self, Bucket, Key):
        """Renders one object the way a listing and a HEAD both describe it.

        ``ETag``, ``Size``, ``StorageClass`` and ``LastModified`` ride along because S3 always
        sends them, and a caller may decide something about an object WITHOUT fetching it — a
        copy that must preserve the storage class reads it here, and a guard that refuses an
        oversize object never fetches at all. A fake omitting them lets such code be written
        against defaults real S3 never supplies.

        Args:
          Bucket: The bucket.
          Key: The object key.

        Returns:
          The object's listing entry.

        Raises:
          None.
        """
        if (Bucket, Key) not in self.etags:
            self.etags[(Bucket, Key)] = self._next_etag()
        return {
            "Key": Key,
            "ETag": self.etags[(Bucket, Key)],
            "Size": self.sizes.get((Bucket, Key), len(self.store[(Bucket, Key)])),
            "StorageClass": self.storage_class.get((Bucket, Key), "STANDARD"),
            "LastModified": self.last_modified.get((Bucket, Key), "1970-01-01T00:00:00+00:00"),
        }

    def head_object(self, Bucket, Key):
        """Reads one object's metadata without its bytes.

        Args:
          Bucket: The bucket.
          Key: The object key.

        Returns:
          The metadata S3 reports — ``ETag``, ``ContentLength``, ``ContentType``, ``Metadata`` and
          the storage class, but NOT ``Key`` or ``Size``, neither of which a real HEAD returns.

        Raises:
          FakeClientError: Code ``404`` when the object is absent, which is what S3 raises here.
            It is deliberately NOT ``NoSuchKey`` — that is the ``GetObject`` shape, and a caller
            catching it would silently re-raise on every absent object. A fake raising whatever
            its caller catches agrees with the caller and with nothing else.
        """
        if (Bucket, Key) not in self.store:
            raise FakeClientError("404")
        listed = self._listed(Bucket, Key)
        return {
            "ETag": listed["ETag"],
            "ContentLength": listed["Size"],
            "StorageClass": listed["StorageClass"],
            "LastModified": listed["LastModified"],
            "ContentType": self.content_type.get((Bucket, Key), "binary/octet-stream"),
            "Metadata": dict(self.metadata.get((Bucket, Key), {})),
        }

    def get_object_tagging(self, Bucket, Key):
        """Reads one object's tag set.

        Args:
          Bucket: The bucket.
          Key: The object key.

        Returns:
          The tag set, empty when the object carries none.

        Raises:
          FakeClientError: Code ``404`` when the object is absent, as S3 answers.
        """
        if (Bucket, Key) not in self.store:
            raise FakeClientError("404")
        return {"TagSet": list(self.tags.get((Bucket, Key), []))}

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
            self.delete_identifiers.append(dict(obj))
            key = obj["Key"]
            if key in self.undeletable:
                errors.append({"Key": key, "Code": "AccessDenied", "Message": "denied"})
                continue
            self.store.pop((Bucket, key), None)
            self.etags.pop((Bucket, key), None)
        return {"Errors": errors} if errors else {}

    def copy_object(self, Bucket, Key, CopySource, **kw):
        """Copies one object, recording the order copies and deletes happened in.

        The order is the point of recording it. A reader that deleted its source before confirming
        the copy would lose an operator's file with nothing to recover it from, and the loss is
        silent — the next sweep simply finds an empty inbox. A test can only see that by watching
        the sequence, so the sequence is what this keeps.

        Args:
          Bucket: The destination bucket.
          Key: The destination key.
          CopySource: The source, as the mapping boto3 accepts.
          **kw: ``StorageClass`` and the two directives, which decide what the copy carries. S3
            preserves NOTHING by default here: a copy that omits ``StorageClass`` lands in
            ``STANDARD`` whatever the source was, and naming ``ContentType`` would force
            ``MetadataDirective=REPLACE`` and drop the user metadata. Modelling that is the point —
            a fake that copied everything unconditionally would pass a caller that preserves none
            of it. The parameters are also kept on ``copy_parameters`` so a test can assert them.

        Returns:
          The ``CopyObjectResult`` carrying the destination's new ETag. It is never equal to a
          multipart source's ``…-N`` ETag, which is why a caller records this value rather than
          comparing the two sides.

        Raises:
          FakeNoSuchKey: When the source is absent.
        """
        source = (CopySource["Bucket"], CopySource["Key"])
        if source not in self.store:
            raise FakeNoSuchKey()
        destination = (Bucket, Key)
        self.store[destination] = self.store[source]
        self.etags[destination] = self._next_etag()
        if source in self.sizes:
            self.sizes[destination] = self.sizes[source]
        self.storage_class[destination] = kw.get("StorageClass", "STANDARD")
        if kw.get("MetadataDirective", "COPY") == "COPY":
            self.content_type[destination] = self.content_type.get(
                source, "binary/octet-stream"
            )
            self.metadata[destination] = dict(self.metadata.get(source, {}))
        if kw.get("TaggingDirective", "COPY") == "COPY":
            self.tags[destination] = list(self.tags.get(source, []))
        self.copy_parameters = dict(kw)
        self.operations.append(("copy", CopySource["Key"], Key))
        return {"CopyObjectResult": {"ETag": self.etags[destination]}}

    def create_multipart_upload(self, Bucket, Key, **kw):
        """Opens a multipart upload, which is how an object above 5 GiB is copied.

        Args:
          Bucket: The destination bucket.
          Key: The destination key.
          **kw: ``StorageClass`` and anything else, recorded on the upload.

        Returns:
          The upload id later calls carry.

        Raises:
          None.
        """
        self._seq += 1
        upload_id = f"upload-{self._seq}"
        self.uploads[upload_id] = {"Bucket": Bucket, "Key": Key, "parts": [], "kw": dict(kw)}
        return {"UploadId": upload_id}

    def upload_part_copy(self, Bucket, Key, UploadId, PartNumber, CopySource, CopySourceRange):
        """Copies one ranged part of a source into an open multipart upload.

        Args:
          Bucket: The destination bucket.
          Key: The destination key.
          UploadId: The open upload.
          PartNumber: Which part this is, one-based.
          CopySource: The source, as the mapping boto3 accepts.
          CopySourceRange: The byte range, ``bytes=start-end``.

        Returns:
          The part's ETag, under ``CopyPartResult`` as S3 nests it.

        Raises:
          FakeNoSuchKey: When the source is absent.
        """
        source = (CopySource["Bucket"], CopySource["Key"])
        if source not in self.store:
            raise FakeNoSuchKey()
        self._seq += 1
        etag = f'"part-{self._seq}"'
        self.uploads[UploadId]["parts"].append(
            {"PartNumber": PartNumber, "ETag": etag, "Range": CopySourceRange}
        )
        return {"CopyPartResult": {"ETag": etag}}

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload):
        """Finishes a multipart upload, materialising the destination.

        The completed ETag carries the ``-N`` suffix real S3 gives a multipart object, because that
        suffix is exactly why a caller must record the copy's own ETag rather than compare the two
        sides: a single ``CopyObject`` of the same bytes would never produce it.

        The destination's content type, user metadata and tags come from whatever
        ``create_multipart_upload`` was given and from NOWHERE else — ``UploadPartCopy`` moves bytes
        only, and there is no ``MetadataDirective`` on this path. Modelling that is the point: a
        caller that forgets them ships an object stripped of all three, and a fake that quietly
        inherited them from the source would pass it.

        Args:
          Bucket: The destination bucket.
          Key: The destination key.
          UploadId: The upload being completed.
          MultipartUpload: The parts, as the caller assembled them.

        Returns:
          The destination's ETag.

        Raises:
          None.
        """
        upload = self.uploads.pop(UploadId)
        self.store[(Bucket, Key)] = b""
        parts = len(MultipartUpload.get("Parts", []))
        self._seq += 1
        self.etags[(Bucket, Key)] = f'"multipart-{self._seq}-{parts}"'
        opened = upload["kw"]
        self.storage_class[(Bucket, Key)] = opened.get("StorageClass", "STANDARD")
        self.content_type[(Bucket, Key)] = opened.get("ContentType", "binary/octet-stream")
        self.metadata[(Bucket, Key)] = dict(opened.get("Metadata", {}))
        self.tags[(Bucket, Key)] = [
            {"Key": k, "Value": v}
            for k, v in urllib.parse.parse_qsl(opened.get("Tagging", ""))
        ]
        self.operations.append(("complete", UploadId, Key))
        return {"ETag": self.etags[(Bucket, Key)]}

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
        self.operations.append(("delete", Key, None))
        return {}


#: The members ``GetTable`` returns that ``TableInput`` will not accept. Named here so a caller
#: rebuilding a table definition meets them, because Glue always sends them and rejecting them is
#: what makes an allowlist the only correct shape.
_GLUE_READ_ONLY_MEMBERS = {
    "CreateTime": "2026-01-01T00:00:00+00:00",
    "UpdateTime": "2026-01-01T00:00:00+00:00",
    "CreatedBy": "arn:aws:sts::1:assumed-role/x/y",
    "IsRegisteredWithLakeFormation": False,
    "CatalogId": "1",
    "VersionId": "1",
    "Status": {"State": "SUCCEEDED"},
    "IsMultiDialectView": False,
    "DatabaseName": "",
}


class FakeGlue:
    """An in-memory Glue client supporting paginated listing and partial-failure drops.

    Attributes:
      created: Database names in creation order.
      databases: The live database names.
      parameters: Each database's parameters as it was created with them — what a shared-space
        database's marker is read from. A database added straight to ``databases`` carries none,
        which is what a user's personal database looks like.
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
        self.parameters = {}
        self.tables = {}
        self.definitions = {}
        self.archived = {}
        self.update_calls = []
        self.undroppable = set()
        self.page_size = 2
        self.exceptions = types.SimpleNamespace(
            AlreadyExistsException=FakeAlreadyExists, EntityNotFoundException=FakeEntityNotFound
        )

    def create_database(self, DatabaseInput):
        """Creates a database, refusing a name that exists the way the real API does.

        Args:
          DatabaseInput: The input, carrying the name and optionally its parameters.

        Returns:
          None.

        Raises:
          FakeAlreadyExists: When a database of that name exists, whoever made it.
        """
        name = DatabaseInput["Name"]
        if name in self.databases:
            raise FakeAlreadyExists(f"database {name} already exists")
        self.created.append(name)
        self.databases.add(name)
        self.parameters[name] = dict(DatabaseInput.get("Parameters") or {})
        self.tables.setdefault(name, [])

    def seed_space_database(self, name, tables=()):
        """Puts a database there as the create verb makes one, marker and all.

        Args:
          name: The space name, which is also the database name.
          tables: The tables it already holds.

        Returns:
          None.

        Raises:
          None.
        """
        self.databases.add(name)
        self.parameters[name] = {config.DATABASE_MARKER_KEY: name}
        self.tables[name] = list(tables)

    def get_database(self, Name):
        """Reports whether a database exists, raising the way the real client does.

        Args:
          Name: The database name.

        Returns:
          The database description, carrying its name and parameters.

        Raises:
          FakeEntityNotFound: When no such database exists, which is how the real API answers
            and therefore what a caller reading absence has to catch.
        """
        if Name not in self.databases:
            raise FakeEntityNotFound(f"no such database {Name}")
        return {"Database": {"Name": Name, "Parameters": dict(self.parameters.get(Name) or {})}}

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
        response = {
            "TableList": [
                {"Name": t, **self.definitions.get((DatabaseName, t), {})} for t in page
            ]
        }
        if start + self.page_size < len(tables):
            response["NextToken"] = str(start + self.page_size)
        return response

    def get_table(self, DatabaseName, Name):
        """Reads one table's definition.

        Args:
          DatabaseName: The database.
          Name: The table.

        Returns:
          The table, wrapped under ``Table`` as Glue nests it — the seeded definition PLUS the
          read-only members Glue always populates. Those are the point: ``GetTable`` returns 24
          members and ``TableInput`` accepts 14, so a caller that rebuilds an update by removing
          the fields it happens to know about ships one Glue rejects. A fake returning only what a
          test seeded lets that caller pass, which is the same shape as a fake raising the
          exception its caller catches.

        Raises:
          FakeEntityNotFound: When the database or the table is absent.
        """
        if Name not in self.tables.get(DatabaseName, []):
            raise FakeEntityNotFound()
        return {
            "Table": {
                "Name": Name,
                **_GLUE_READ_ONLY_MEMBERS,
                "DatabaseName": DatabaseName,
                **self.definitions.get((DatabaseName, Name), {}),
            }
        }

    def update_table(self, DatabaseName, TableInput, SkipArchive=True):
        """Replaces one table's definition, recording whether a version was retained.

        ``SkipArchive`` is recorded rather than ignored because the retained version IS the
        rollback for a re-pointed ``LOCATION``: a caller that skipped the archive would leave
        nothing to read the previous location back from, and no other observable distinguishes
        the two.

        Args:
          DatabaseName: The database.
          TableInput: The new definition.
          SkipArchive: Whether Glue should skip retaining the previous version.

        Returns:
          An empty response.

        Raises:
          FakeParamValidation: When the input carries a member ``TableInput`` does not accept.
            Real botocore refuses these before the request leaves the process, and modelling that
            is the point: a caller that rebuilds a definition by REMOVING the read-only fields it
            knows about ships one Glue rejects, and a fake that accepted anything would pass it.
          FakeEntityNotFound: When the database or the table is absent.
        """
        name = TableInput["Name"]
        rejected = sorted(set(TableInput) & set(_GLUE_READ_ONLY_MEMBERS))
        if rejected:
            raise FakeParamValidation(
                f"Unknown parameter in TableInput: {', '.join(rejected)}"
            )
        if name not in self.tables.get(DatabaseName, []):
            raise FakeEntityNotFound()
        if not SkipArchive:
            self.archived.setdefault(f"{DatabaseName}.{name}", []).append(
                dict(self.definitions.get((DatabaseName, name), {}))
            )
        self.definitions[(DatabaseName, name)] = dict(TableInput)
        self.update_calls.append(
            {"DatabaseName": DatabaseName, "Name": name, "SkipArchive": SkipArchive}
        )
        return {}

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
          Principal: The principal granted to. Recorded: a grant's principal is the whole of
            what makes it a shared-role union grant rather than a per-member one.
          Resource: The resource granted on.
          Permissions: The permissions granted.

        Returns:
          None.

        Raises:
          None.
        """
        self.grants.append(
            {"Principal": Principal, "Resource": Resource, "Permissions": Permissions}
        )

    def revoke_permissions(self, Principal, Resource, Permissions):
        """Records a revoke.

        Args:
          Principal: The principal revoked from. Recorded for the same reason a grant's is.
          Resource: The resource revoked on.
          Permissions: The permissions revoked.

        Returns:
          None.

        Raises:
          None.
        """
        self.revokes.append(
            {"Principal": Principal, "Resource": Resource, "Permissions": Permissions}
        )

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

    Single-user mode, for the create tests, maps every username to one attribute bag, or only the
    names in ``pool`` when one is given. The create asks the pool about the SPACE name too, so a
    create test names its pool, or every space name answers as a user and is refused. Multi-user
    mode, for the add and remove tests, only recognises the usernames listed.

    Attributes:
      users: Attribute bags by username. Non-empty selects multi-user mode.
      pool: In single-user mode, the usernames that exist, or None for every name.
      statuses: A ``UserStatus`` to report per username; absent reads as ``CONFIRMED``.
      get_user_faults: An exception ``admin_get_user`` raises per username, before anything else.
      updates: The attribute updates applied, in order.
      calls: Every call made, as ``(operation, username)``, in order.
      exceptions: The exception namespace production code catches on.
    """

    def __init__(self, attrs=None, pool=None):
        """Creates a client in single-user mode with the given attribute bag.

        Args:
          attrs: The single-user attribute bag, or None for an empty one.
          pool: The usernames that exist in single-user mode, or None for every name.

        Returns:
          None.

        Raises:
          None.
        """
        self._default = dict(attrs or {})
        self.users = {}
        self.pool = None if pool is None else set(pool)
        self.statuses = {}
        self.get_user_faults = {}
        self.updates = []
        self.calls = []
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
        if self.pool is not None and username not in self.pool:
            return None
        return self._default

    def admin_get_user(self, UserPoolId, Username):
        """Reads one user's attributes.

        Args:
          UserPoolId: The pool, unused.
          Username: The user to read.

        Returns:
          A response carrying the attribute list and the user's status.

        Raises:
          FakeUserNotFound: When the user does not exist.
          Exception: The fault planted for this username in ``get_user_faults``.
        """
        self.calls.append(("AdminGetUser", Username))
        if Username in self.get_user_faults:
            raise self.get_user_faults[Username]
        bucket = self._bucket(Username)
        if bucket is None:
            raise FakeUserNotFound()
        return {
            "UserAttributes": [{"Name": n, "Value": v} for n, v in bucket.items()],
            "UserStatus": self.statuses.get(Username, "CONFIRMED"),
        }

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
        self.calls.append(("AdminUpdateUserAttributes", Username))
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


def install(cognito_attrs=None, max_memberships=10, pool=None):
    """Installs fresh fakes and canonical configuration onto the cached globals.

    The buckets, the pool and the queue URL live in the shared config — one definition, so this
    is the one place they are patched. The conftest's snapshot fixture undoes it after each test,
    which it could not do while this layer kept its own copies. The queue URL is left unset, so
    notifications are a no-op by default.

    Args:
      cognito_attrs: The single-user attribute bag for the fake Cognito client.
      max_memberships: The membership cap to install.
      pool: The usernames the single-user Cognito fake recognises, or None for every name.

    Returns:
      The S3, Glue, Lake Formation and Cognito fakes, for assertions.

    Raises:
      None.
    """
    clients._s3 = FakeS3()
    clients._glue = FakeGlue()
    clients._lf = FakeLF()
    clients._cognito = FakeCognito(cognito_attrs, pool)
    clients._sqs = FakeSqs()
    clients._sqs_bounded = clients._sqs
    config.MAX_SHARED_MEMBERSHIPS = max_memberships
    config.PORTAL_ROLE_ARN = "arn:aws:iam::1:role/portal"
    cpconfig.ADMIN_BUCKET = "admin-bkt"
    cpconfig.SHARED_SPACE_BUCKET = "shared-bkt"
    cpconfig.USER_SPACE_BUCKET = "user-bkt"
    cpconfig.NOTIFICATIONS_QUEUE_URL = ""
    return clients._s3, clients._glue, clients._lf, clients._cognito
