"""The object and document routes, driven through the router.

**The load-bearing assertion in this file is a zero, and it counts TWO things.** A route that
resolved the prefix from the request and let IAM refuse would return the same 403 with the same
body as one that refused from claims — nothing outside the process separates them. So a refusal is
asserted by call count against a client that records every call **and** against a spy on the
identity door itself. Counting S3 operations alone is not enough: an `AssumeRole` is an AWS call
and a refusal issued after one has already reached the identity plane. A first draft of this file
stubbed `user_client` with a lambda, which recorded nothing — planting a client build before every
refusal left the whole suite green.

The document assertions are about **bytes**, not about JSON. A route that parses works for every
healthy document and turns an unparseable one into a 500, which puts SPEC-159's quarantine path
out of reach — so the fixture here is deliberately valid UTF-8 that is not valid JSON.
"""

import datetime
import json

import pytest
import router
from apicommon import contract
from conftest import bearer


class _ServiceError(Exception):
    """A botocore-shaped client error, built here rather than imported.

    `botocore` is provided by the Lambda runtime and declared as a dependency nowhere, so importing
    it passes on a laptop with boto3 and fails on the runner. The identity layer classifies by
    reading ``response["Error"]["Code"]``, which is the whole shape this needs.
    """

    def __init__(self, code, message=""):
        """Builds the error.

        Args:
          code: The service error code.
          message: The service's own message, which must reach no response body.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": message}}


class RecordingS3:
    """An S3 client that records every call, so a refusal's cost can be counted.

    Attributes:
      calls: ``(operation, kwargs)`` for every call, in order.
      assumes: How many times the identity door was opened. An `AssumeRole` is an AWS call, so a
        refusal that costs one is not a zero-cost refusal — and it is invisible to ``calls``.
    """

    def __init__(self, listing=None, head=None, body=None, missing=()):
        """Builds the fake.

        Args:
          listing: What ``list_objects_v2`` returns.
          head: What ``head_object`` returns, or None to raise NotFound.
          body: The bytes ``get_object`` returns.
          missing: Operation names that should raise NotFound.

        Returns:
          None.

        Raises:
          None.
        """
        self._listing = listing or {}
        self._head = head
        self._body = body
        self._missing = set(missing)
        self.calls = []
        self.assumes = 0

    def _record(self, operation, kwargs):
        """Records one call and raises when the operation is configured absent.

        Args:
          operation: The operation name.
          kwargs: Its keyword arguments.

        Returns:
          None.

        Raises:
          _ServiceError: When the operation is configured as missing.
        """
        self.calls.append((operation, kwargs))
        if operation in self._missing:
            raise _ServiceError("NoSuchKey")

    def list_objects_v2(self, **kwargs):
        """Returns the configured page.

        Args:
          **kwargs: The listing request.

        Returns:
          The page.

        Raises:
          None.
        """
        self._record("list_objects_v2", kwargs)
        return self._listing

    def head_object(self, **kwargs):
        """Returns the configured head, or raises NotFound.

        Args:
          **kwargs: The head request.

        Returns:
          The head.

        Raises:
          _ServiceError: When no head is configured.
        """
        self._record("head_object", kwargs)
        if self._head is None:
            raise _ServiceError("NotFound")
        return self._head

    def get_object(self, **kwargs):
        """Returns the configured body.

        Args:
          **kwargs: The get request.

        Returns:
          A response carrying a readable body.

        Raises:
          None.
        """
        self._record("get_object", kwargs)
        return {
            "Body": _Readable(self._body or b""),
            "ContentLength": len(self._body or b""),
            "ETag": '"abc"',
        }

    def put_object(self, **kwargs):
        """Records a write.

        Args:
          **kwargs: The put request.

        Returns:
          The new ETag.

        Raises:
          None.
        """
        self._record("put_object", kwargs)
        return {"ETag": '"written"'}

    def copy_object(self, **kwargs):
        """Records a copy.

        Args:
          **kwargs: The copy request.

        Returns:
          The new ETag.

        Raises:
          None.
        """
        self._record("copy_object", kwargs)
        return {"CopyObjectResult": {"ETag": '"copied"'}}

    def delete_object(self, **kwargs):
        """Records a delete.

        Args:
          **kwargs: The delete request.

        Returns:
          An empty response.

        Raises:
          None.
        """
        self._record("delete_object", kwargs)
        return {}


class _Readable:
    """The minimum of a streaming body: something with ``read``."""

    def __init__(self, payload):
        """Builds it.

        Args:
          payload: The bytes.

        Returns:
          None.

        Raises:
          None.
        """
        self._payload = payload

    def read(self):
        """Returns the bytes.

        Args:
          None.

        Returns:
          The bytes.

        Raises:
          None.
        """
        return self._payload


@pytest.fixture(autouse=True)
def _buckets(monkeypatch):
    """Both bucket variables, which every route reads.

    Args:
      monkeypatch: The pytest fixture.

    Yields:
      None.

    Raises:
      None.
    """
    monkeypatch.setenv("USER_SPACE_BUCKET", "user-bucket")
    monkeypatch.setenv("SHARED_SPACE_BUCKET", "shared-bucket")
    yield


@pytest.fixture
def s3(monkeypatch):
    """Installs a recording client on the user plane.

    Args:
      monkeypatch: The pytest fixture.

    Returns:
      A factory taking the fake and returning it.

    Raises:
      None.
    """

    def _install(fake):
        def _door(service, caller):
            fake.assumes += 1
            return fake

        monkeypatch.setattr("apicommon.identity.user_client", _door)
        return fake

    return _install


def _body(payload):
    """Serialises a request body the way the gateway delivers one.

    Args:
      payload: The body.

    Returns:
      The body.

    Raises:
      None.
    """
    return payload


class TestTheRefusalCostsNothing:
    """FR-001 AC7 and FR-013 — the zero is the assertion."""

    def test_a_foreign_personal_space_refuses_with_no_aws_call(self, s3) -> None:
        """The refusal a route that trusted the request would make identically."""
        fake = s3(RecordingS3())
        answer = router.route(
            "GET", "/v1/objects", bearer(), "rq", None, {"spaceKind": "personal", "spaceName": "bob"}
        )
        assert answer["statusCode"] == 403
        assert json.loads(answer["body"])["error"]["code"] == "AccessDenied"
        assert fake.calls == [], "the refusal reached AWS"
        assert fake.assumes == 0, "the refusal cost an AssumeRole"

    def test_a_shared_space_with_no_membership_claim_refuses_with_no_aws_call(self, s3) -> None:
        """The other half of the isolation refusal."""
        fake = s3(RecordingS3())
        answer = router.route(
            "GET", "/v1/objects", bearer(), "rq", None, {"spaceKind": "shared", "spaceName": "legal"}
        )
        assert answer["statusCode"] == 403
        assert fake.calls == []
        assert fake.assumes == 0

    def test_a_key_escaping_the_root_refuses_with_no_aws_call(self, s3) -> None:
        """The key is the caller's even when the space is theirs."""
        fake = s3(RecordingS3())
        answer = router.route(
            "GET",
            "/v1/objects/metadata",
            bearer(),
            "rq",
            None,
            {"spaceKind": "personal", "spaceName": "alice", "key": "alice/../bob/secret"},
        )
        assert answer["statusCode"] == 403
        assert json.loads(answer["body"])["error"]["code"] == "AccessDenied"
        assert fake.calls == []
        assert fake.assumes == 0

    def test_the_control_a_permitted_request_DOES_reach_aws(self, s3) -> None:
        """Without this, every assertion above passes against a broken route."""
        fake = s3(RecordingS3(listing={"Contents": [], "CommonPrefixes": []}))
        answer = router.route(
            "GET",
            "/v1/objects",
            bearer(),
            "rq",
            None,
            {"spaceKind": "personal", "spaceName": "alice"},
        )
        assert answer["statusCode"] == 200
        assert [call[0] for call in fake.calls] == ["list_objects_v2"]
        assert fake.assumes == 1, "the control must open the door the refusals must not"


class TestListing:
    """FR-001 AC2 — one page, folders and files together."""

    def test_folders_and_files_travel_in_one_array_with_a_kind(self, s3) -> None:
        """The shape the browser's FileListPage mapping already expects."""
        s3(
            RecordingS3(
                listing={
                    "CommonPrefixes": [{"Prefix": "alice/reports/"}],
                    "Contents": [
                        {
                            "Key": "alice/q1.csv",
                            "Size": 12,
                            "LastModified": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
                        }
                    ],
                }
            )
        )
        answer = router.route(
            "GET", "/v1/objects", bearer(), "rq", None, {"spaceKind": "personal", "spaceName": "alice"}
        )
        items = json.loads(answer["body"])["items"]
        assert [item["kind"] for item in items] == ["folder", "file"]
        assert items[0]["size"] is None

    def test_the_folder_marker_is_not_a_row(self, s3) -> None:
        """It is an implementation detail of a folder, not a file anybody put there."""
        s3(
            RecordingS3(
                listing={
                    "Contents": [
                        {"Key": "alice/DO_NOT_DELETE.txt", "Size": 0, "LastModified": None},
                        {"Key": "alice/real.csv", "Size": 5, "LastModified": None},
                    ]
                }
            )
        )
        answer = router.route(
            "GET", "/v1/objects", bearer(), "rq", None, {"spaceKind": "personal", "spaceName": "alice"}
        )
        keys = [item["key"] for item in json.loads(answer["body"])["items"]]
        assert keys == ["alice/real.csv"]

    def test_the_route_neither_re_encodes_nor_rewrites_the_continuation_token(self, s3) -> None:
        """Over the three characters that break a re-encoder.

        A token carrying `+`, `/` or `=` that anything re-encodes stops resolving to the page it
        named, and the next page silently repeats the first. This proves the ROUTE is transparent;
        the browser half of the round trip — `URLSearchParams`, which percent-encodes all three —
        is asserted in the client's own suite.
        """
        awkward = "a+b/c=="
        fake = s3(RecordingS3(listing={"Contents": [], "NextContinuationToken": awkward}))
        answer = router.route(
            "GET",
            "/v1/objects",
            bearer(),
            "rq",
            None,
            {"spaceKind": "personal", "spaceName": "alice", "nextToken": awkward},
        )
        assert json.loads(answer["body"])["nextToken"] == awkward
        assert fake.calls[0][1]["ContinuationToken"] == awkward

    def test_the_listing_is_delimited_and_bounded(self, s3) -> None:
        """The thinness rule, asserted on the request the route actually sends."""
        fake = s3(RecordingS3(listing={"Contents": []}))
        router.route(
            "GET", "/v1/objects", bearer(), "rq", None, {"spaceKind": "personal", "spaceName": "alice"}
        )
        request = fake.calls[0][1]
        assert request["Delimiter"] == "/"
        assert request["MaxKeys"] == 25


class TestExistsAnswers200EitherWay:
    """FR-001 AC3 — absence is a value, not an error."""

    def test_a_present_object_is_true(self, s3) -> None:
        """The affirmative."""
        s3(RecordingS3(head={"ContentLength": 1}))
        answer = router.route(
            "GET",
            "/v1/objects/exists",
            bearer(),
            "rq",
            None,
            {"spaceKind": "personal", "spaceName": "alice", "key": "alice/x"},
        )
        assert answer["statusCode"] == 200
        assert json.loads(answer["body"])["exists"] is True

    def test_an_absent_object_is_200_FALSE_not_404(self, s3) -> None:
        """Mapping absence onto the error arm breaks every free-name and collision check."""
        s3(RecordingS3(head=None))
        answer = router.route(
            "GET",
            "/v1/objects/exists",
            bearer(),
            "rq",
            None,
            {"spaceKind": "personal", "spaceName": "alice", "key": "alice/gone"},
        )
        assert answer["statusCode"] == 200
        assert json.loads(answer["body"])["exists"] is False


    def test_a_prefix_holding_only_its_own_marker_still_EXISTS(self, s3) -> None:
        """The listing route cannot answer this, which is why the question came here.

        ``objects_list`` drops the prefix's own key and every ``DO_NOT_DELETE.txt`` — right for a
        listing, and fatal for "is this folder still there": a folder made with New folder holds
        exactly the key the listing hides. Answered through the raw page instead.
        """
        fake = s3(RecordingS3(listing={"Contents": [{"Key": "alice/reports/DO_NOT_DELETE.txt"}]}))
        answer = router.route(
            "GET",
            "/v1/objects/exists",
            bearer(),
            "rq",
            None,
            {
                "spaceKind": "personal",
                "spaceName": "alice",
                "key": "alice/reports/",
                "target": "prefix",
            },
        )
        assert json.loads(answer["body"])["exists"] is True
        assert [call[0] for call in fake.calls] == ["list_objects_v2"]
        assert fake.calls[0][1]["MaxKeys"] == 1
        assert fake.calls[0][1]["Delimiter"] == "/"

    def test_a_prefix_whose_only_child_is_a_SUBFOLDER_still_exists(self, s3) -> None:
        """The delimiter costs the answer nothing: a nested-only folder answers through CommonPrefixes."""
        s3(RecordingS3(listing={"CommonPrefixes": [{"Prefix": "alice/reports/q1/"}]}))
        answer = router.route(
            "GET",
            "/v1/objects/exists",
            bearer(),
            "rq",
            None,
            {
                "spaceKind": "personal",
                "spaceName": "alice",
                "key": "alice/reports/",
                "target": "prefix",
            },
        )
        assert json.loads(answer["body"])["exists"] is True

    def test_an_empty_prefix_page_is_FALSE(self, s3) -> None:
        """The negative, and the one the panel renders a message from."""
        s3(RecordingS3(listing={}))
        answer = router.route(
            "GET",
            "/v1/objects/exists",
            bearer(),
            "rq",
            None,
            {
                "spaceKind": "personal",
                "spaceName": "alice",
                "key": "alice/gone/",
                "target": "prefix",
            },
        )
        assert json.loads(answer["body"])["exists"] is False

    def test_a_prefix_question_about_a_FOREIGN_space_refuses_with_no_aws_call(self, s3) -> None:
        """The refusal is the space resolution's, and it happens before the client is built."""
        fake = s3(RecordingS3(listing={"Contents": [{"Key": "bob/x"}]}))
        answer = router.route(
            "GET",
            "/v1/objects/exists",
            bearer(),
            "rq",
            None,
            {"spaceKind": "personal", "spaceName": "bob", "key": "bob/", "target": "prefix"},
        )
        assert answer["statusCode"] == 403
        assert json.loads(answer["body"])["error"]["code"] == "AccessDenied"
        assert fake.calls == []
        assert fake.assumes == 0


class TestMetadataCarriesEverythingThePanelRenders:
    """FR-009 — the details panel shows storage class and the object's own metadata.

    A port that returned only size and content type would have emptied two fields silently, which
    is the erosion FR-009 exists to catch.
    """

    def test_storage_class_and_user_metadata_travel(self, s3) -> None:
        """Both fields, and the pairs as rows because the vocabulary has no map."""
        s3(
            RecordingS3(
                head={
                    "ContentLength": 12,
                    "ContentType": "text/csv",
                    "ETag": '"e"',
                    "StorageClass": "INTELLIGENT_TIERING",
                    "Metadata": {"owner": "alice", "batch": "7"},
                }
            )
        )
        answer = router.route(
            "GET",
            "/v1/objects/metadata",
            bearer(),
            "rq",
            None,
            {"spaceKind": "personal", "spaceName": "alice", "key": "alice/x.csv"},
        )
        body = json.loads(answer["body"])
        assert body["storageClass"] == "INTELLIGENT_TIERING"
        assert body["userMetadata"] == [
            {"name": "batch", "value": "7"},
            {"name": "owner", "value": "alice"},
        ]

    def test_an_omitted_storage_class_reads_STANDARD_and_no_metadata_is_an_empty_list(self, s3) -> None:
        """S3 omits StorageClass for every ordinary object, which is the common case."""
        s3(RecordingS3(head={"ContentLength": 1, "ETag": '"e"'}))
        answer = router.route(
            "GET",
            "/v1/objects/metadata",
            bearer(),
            "rq",
            None,
            {"spaceKind": "personal", "spaceName": "alice", "key": "alice/x"},
        )
        body = json.loads(answer["body"])
        assert body["storageClass"] == "STANDARD"
        assert body["userMetadata"] == []


class TestDocumentsAreBytes:
    """FR-003 — never parsed on the way out, never re-serialised on the way in."""

    def test_a_body_that_is_not_JSON_arrives_intact(self, s3) -> None:
        """The fixture is valid UTF-8 that is not valid JSON — SPEC-159's actual subject.

        A route that parsed would answer 500 here, and `classifyDocument` would never see the
        body it must classify as unreadable.
        """
        broken = '{"version": 1, "entries": [ THIS IS NOT JSON'
        s3(RecordingS3(body=broken.encode("utf-8")))
        answer = router.route(
            "GET",
            "/v1/objects/content",
            bearer(),
            "rq",
            None,
            {"spaceKind": "personal", "spaceName": "alice", "key": "alice/user_settings/x.json"},
        )
        assert answer["statusCode"] == 200
        assert json.loads(answer["body"])["body"] == broken

    def test_a_write_stores_the_bytes_it_was_given(self, s3) -> None:
        """Key order and whitespace survive: re-serialising breaks byte-identity and nothing else."""
        unusual = '{"zebra": 1,   "apple": 2}'
        fake = s3(RecordingS3(head=None))
        router.route(
            "PUT",
            "/v1/objects/content",
            bearer(),
            "rq",
            _body(
                {
                    "space": {"kind": "personal", "name": "alice"},
                    "key": "alice/user_settings/x.json",
                    "body": unusual,
                    "contentType": "application/json",
                    "overwrite": True,
                }
            ),
            None,
        )
        put = next(call for call in fake.calls if call[0] == "put_object")[1]
        assert put["Body"] == unusual.encode("utf-8")

    def test_an_oversized_write_is_refused_BEFORE_any_s3_call(self, s3) -> None:
        """A refusal that first pays for the thing it refuses is not a cap."""
        from apicommon import s3_config

        fake = s3(RecordingS3())
        answer = router.route(
            "PUT",
            "/v1/objects/content",
            bearer(),
            "rq",
            _body(
                {
                    "space": {"kind": "personal", "name": "alice"},
                    "key": "alice/user_settings/x.json",
                    "body": "x" * (s3_config.MAX_DOCUMENT_BYTES + 1),
                    "contentType": "application/json",
                    "overwrite": True,
                }
            ),
            None,
        )
        assert answer["statusCode"] == 413
        error = json.loads(answer["body"])["error"]
        assert error["code"] == "PayloadTooLarge"
        assert error["params"]["limit"] == s3_config.MAX_DOCUMENT_BYTES
        assert fake.calls == []

    def test_a_write_onto_an_occupied_key_conflicts_and_NAMES_the_leaf(self, s3) -> None:
        """FR-001 AC5's typed params, which is why the transport carries them."""
        s3(RecordingS3(head={"ContentLength": 1}))
        answer = router.route(
            "PUT",
            "/v1/objects/content",
            bearer(),
            "rq",
            _body(
                {
                    "space": {"kind": "personal", "name": "alice"},
                    "key": "alice/reports/q1.json",
                    "body": "{}",
                    "contentType": "application/json",
                    "overwrite": False,
                }
            ),
            None,
        )
        assert answer["statusCode"] == 409
        error = json.loads(answer["body"])["error"]
        assert error["code"] == "Conflict"
        assert error["params"] == {"name": "q1.json"}


class TestMutations:
    """FR-001 AC4 and AC6 — one move, and a dict copy source."""

    def test_the_copy_source_is_a_DICT(self, s3) -> None:
        """A hand-built string is wrong for `+` and `%` and copies the wrong object or none."""
        fake = s3(RecordingS3(head=None))
        router.route(
            "POST",
            "/v1/objects/copy",
            bearer(),
            "rq",
            _body(
                {
                    "source": {"kind": "personal", "name": "alice"},
                    "sourceKey": "alice/a+b %.csv",
                    "destination": {"kind": "personal", "name": "alice"},
                    "destinationKey": "alice/copy.csv",
                    "overwrite": True,
                }
            ),
            None,
        )
        copy = next(call for call in fake.calls if call[0] == "copy_object")[1]
        assert copy["CopySource"] == {"Bucket": "user-bucket", "Key": "alice/a+b %.csv"}

    def test_move_is_one_route_that_copies_then_deletes(self, s3) -> None:
        """Two browser calls would put a closed tab between them, and versioning is off."""
        fake = s3(RecordingS3(head=None))
        router.route(
            "POST",
            "/v1/objects/move",
            bearer(),
            "rq",
            _body(
                {
                    "source": {"kind": "personal", "name": "alice"},
                    "sourceKey": "alice/a.csv",
                    "destination": {"kind": "personal", "name": "alice"},
                    "destinationKey": "alice/b.csv",
                    "overwrite": True,
                }
            ),
            None,
        )
        assert [call[0] for call in fake.calls] == ["copy_object", "delete_object"]

    def test_a_move_whose_SOURCE_is_write_locked_refuses_before_copying(self, s3) -> None:
        """A move deletes its source, so an undeletable source is not a movable one.

        Checked before the copy: otherwise the object is duplicated and then the move fails, and
        the user asked for one of it.
        """
        fake = s3(RecordingS3(head=None))
        answer = router.route(
            "POST",
            "/v1/objects/move",
            bearer(),
            "rq",
            _body(
                {
                    "source": {"kind": "personal", "name": "alice"},
                    "sourceKey": "alice/archive/receipt.json",
                    "destination": {"kind": "personal", "name": "alice"},
                    "destinationKey": "alice/receipt.json",
                    "overwrite": True,
                }
            ),
            None,
        )
        assert answer["statusCode"] == 403
        assert fake.calls == []

    def test_deleting_a_marker_is_refused_server_side(self, s3) -> None:
        """The browser refuses it as an affordance; a disabled button is not a permission."""
        fake = s3(RecordingS3())
        answer = router.route(
            "DELETE",
            "/v1/objects",
            bearer(),
            "rq",
            _body(
                {"space": {"kind": "personal", "name": "alice"}, "key": "alice/DO_NOT_DELETE.txt"}
            ),
            None,
        )
        assert answer["statusCode"] == 403
        assert fake.calls == []
        assert fake.assumes == 0


class TestEveryObjectRouteIsOnTheUserPlane:
    """FR-001 AC1 — the caller's own session authorizes every call."""

    def test_no_object_route_declares_the_api_plane(self) -> None:
        """The API's execution role must not sign anything reaching these buckets."""
        offenders = [
            route.id
            for route in contract.ROUTES
            if route.id.startswith("objects.") and route.plane != "user"
        ]
        assert offenders == []

    def test_the_reads_are_idempotent_and_the_writes_are_not(self) -> None:
        """Declared per route, never derived from the method."""
        by_id = {route.id: route.idempotent for route in contract.ROUTES}
        assert by_id["objects.list"] is True
        assert by_id["objects.metadata"] is True
        assert by_id["objects.exists"] is True
        assert by_id["objects.readContent"] is True
        assert by_id["objects.writeContent"] is False
        assert by_id["objects.copy"] is False
        assert by_id["objects.move"] is False
        assert by_id["objects.delete"] is False
