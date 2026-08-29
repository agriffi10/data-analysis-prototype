"""Every object route, driven with the keys the browser really sends.

**The gap this closes is the one that shipped.** The generated contract pins the request *types* on
both sides and ``tsc -b`` checks the browser against them — so a shape mismatch cannot survive. What
neither side checks is a **value**: a route whose guard refuses a key the app legitimately writes
answers 403 with a perfectly conformant request, and every browser test mocks ``apiRequest`` and so
asserts one half of a conversation the server was refusing.

That is not hypothetical. ``assert_writable`` refused every ``DO_NOT_DELETE.txt`` key, which made
the write route refuse the two paths that CREATE one — both best-effort background writes that log
and carry on, so a brand-new user's prefix would silently never exist.

So the keys below are the app's own, taken from the constants and key builders the browser uses:
the root marker, the saved-queries folder and its marker, a `.sql` file, the settings documents, a
quarantine key, an Athena result, and an ordinary user file.
"""

import json

import pytest
import router
from conftest import bearer

# The keys this app writes, as the browser builds them.
ROOT_MARKER = "alice/DO_NOT_DELETE.txt"
SAVED_QUERIES_MARKER = "alice/saved_queries/DO_NOT_DELETE.txt"
SAVED_QUERY = "alice/saved_queries/report.sql"
QUERY_HISTORY = "alice/user_settings/query-history.json"
QUARANTINE = "alice/user_settings/query-history.json.unreadable-20260829T090000Z-a1b2c3d4.json"
NOTIFICATIONS = "alice/user_settings/notifications.json"
SHARED_CONNECTIONS = "alice/user_settings/shared-connections.json"
DQ_REPORT = "alice/data_quality_reports/req-1/report.json"
ATHENA_RESULT = "alice/athenaresults/abc-123.csv"
ORDINARY_FILE = "alice/reports/q1.csv"
NEW_FOLDER = "alice/reports/drafts/"

PERSONAL = {"kind": "personal", "name": "alice"}


class _Recording:
    """An S3 client that answers everything plausibly and records what it was asked.

    Attributes:
      calls: ``(operation, kwargs)`` for every call, so a refusal shows up as an empty list.
    """

    def __init__(self, present=False):
        """Builds the fake.

        Args:
          present: Whether ``head_object`` reports the key as already there.

        Returns:
          None.

        Raises:
          None.
        """
        self._present = present
        self.calls = []

    def _note(self, operation, kwargs):
        """Records one call.

        Args:
          operation: The operation name.
          kwargs: Its keyword arguments.

        Returns:
          None.

        Raises:
          None.
        """
        self.calls.append((operation, kwargs))

    def head_object(self, **kwargs):
        """Reports the key present or absent, as configured.

        Args:
          **kwargs: The head request.

        Returns:
          A head response.

        Raises:
          _Absent: When the fake is configured with nothing there.
        """
        self._note("head_object", kwargs)
        if not self._present:
            raise _Absent()
        return {"ContentLength": 4, "ETag": '"e"', "ContentType": "text/plain"}

    def put_object(self, **kwargs):
        """Records a write.

        Args:
          **kwargs: The put request.

        Returns:
          The new ETag.

        Raises:
          None.
        """
        self._note("put_object", kwargs)
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
        self._note("copy_object", kwargs)
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
        self._note("delete_object", kwargs)
        return {}

    def list_objects_v2(self, **kwargs):
        """Records a listing and returns an empty page.

        Args:
          **kwargs: The listing request.

        Returns:
          An empty page.

        Raises:
          None.
        """
        self._note("list_objects_v2", kwargs)
        return {}

    def get_object(self, **kwargs):
        """Records a read and returns a tiny body.

        Args:
          **kwargs: The get request.

        Returns:
          A response carrying a readable body.

        Raises:
          None.
        """
        self._note("get_object", kwargs)
        return {"Body": _Body(b"{}"), "ContentLength": 2, "ETag": '"e"'}

    def generate_presigned_url(self, *_args, **_kwargs):
        """Returns a URL-shaped string.

        Args:
          *_args: Ignored.
          **_kwargs: Ignored.

        Returns:
          A signed-looking URL.

        Raises:
          None.
        """
        return "https://signed.example/put?X-Amz-Signature=deadbeef"


class _Absent(Exception):
    """A botocore-shaped 404, built here because botocore is the runtime's, not a dependency."""

    def __init__(self):
        """Builds the error.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__("NoSuchKey")
        self.response = {"Error": {"Code": "NoSuchKey", "Message": ""}}


class _Body:
    """The minimum of a streaming body."""

    def __init__(self, payload):
        """Builds it.

        Args:
          payload: The bytes to serve.

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
          The payload.

        Raises:
          None.
        """
        return self._payload


@pytest.fixture
def s3_and_signer(monkeypatch):
    """Points BOTH identity doors at one recording client.

    Args:
      monkeypatch: Pytest's patcher.

    Yields:
      A function installing a client and returning it.

    Raises:
      None.
    """
    from apicommon import identity

    def _install(client):
        """Installs one client behind both accessors.

        Args:
          client: The client to serve.

        Returns:
          The client.

        Raises:
          None.
        """
        monkeypatch.setattr(identity, "user_client", lambda service, acting_as: client)
        monkeypatch.setattr(
            identity,
            "signing_client",
            lambda service, acting_as, *, covering: (client, _Credentials()),
        )
        return client

    yield _install


class _Credentials:
    """Credentials with an hour left, which is what a fresh assumed session has."""

    @property
    def expires_at(self):
        """When the session dies.

        Args:
          None.

        Returns:
          An hour from a fixed instant, so the clamp has something to clamp to.

        Raises:
          None.
        """
        import datetime

        return datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)


WRITES = [
    ("the user's root marker", ROOT_MARKER),
    ("the saved-queries folder marker", SAVED_QUERIES_MARKER),
    ("a saved query", SAVED_QUERY),
    ("the query-history document", QUERY_HISTORY),
    ("the notifications document", NOTIFICATIONS),
    ("the shared-connections document", SHARED_CONNECTIONS),
    ("a new folder's placeholder", NEW_FOLDER),
]


@pytest.mark.parametrize("what,key", WRITES, ids=[w for w, _ in WRITES])
def test_every_document_the_app_writes_is_accepted_by_the_write_route(what, key, s3_and_signer) -> None:
    """A conformant request refused for its VALUE is invisible to the contract and to `tsc`.

    Args:
      what: What the key is, for the failure message.
      key: The key the browser builds.
      s3_and_signer: The stubbed identity doors.

    Returns:
      None.

    Raises:
      AssertionError: If a shipped write is refused.
    """
    client = s3_and_signer(_Recording(present=False))

    answer = router.route(
        "PUT",
        "/v1/objects/content",
        bearer(),
        "rq",
        {"space": PERSONAL, "key": key, "body": "{}", "contentType": "text/plain", "overwrite": False},
    )

    assert answer["statusCode"] == 200, f"{what} was refused: {answer['body']}"
    assert any(call[0] == "put_object" for call in client.calls)


READS = [
    ("a saved query", SAVED_QUERY),
    ("the query-history document", QUERY_HISTORY),
    ("the notifications document", NOTIFICATIONS),
    ("the shared-connections document", SHARED_CONNECTIONS),
    ("a data-quality report", DQ_REPORT),
]


@pytest.mark.parametrize("what,key", READS, ids=[w for w, _ in READS])
def test_every_document_the_app_reads_is_accepted_by_the_read_route(what, key, s3_and_signer) -> None:
    """The read side of the same question.

    Args:
      what: What the key is, for the failure message.
      key: The key the browser builds.
      s3_and_signer: The stubbed identity doors.

    Returns:
      None.

    Raises:
      AssertionError: If a shipped read is refused.
    """
    s3_and_signer(_Recording())

    answer = router.route(
        "GET",
        "/v1/objects/content",
        bearer(),
        "rq",
        None,
        {"spaceKind": "personal", "spaceName": "alice", "key": key},
    )

    assert answer["statusCode"] == 200, f"{what} was refused: {answer['body']}"


def test_the_quarantine_copy_the_settings_path_makes_is_accepted(s3_and_signer) -> None:
    """SPEC-159's recovery is a copy aside, and it is the one write nobody would think to check.

    It happens only after a document has already failed to parse, so a route refusing it leaves
    that user unable to save anything, ever, with no way out that the app offers.

    Args:
      s3_and_signer: The stubbed identity doors.

    Returns:
      None.

    Raises:
      AssertionError: If the quarantine copy is refused.
    """
    client = s3_and_signer(_Recording(present=False))

    answer = router.route(
        "POST",
        "/v1/objects/copy",
        bearer(),
        "rq",
        {
            "source": PERSONAL,
            "sourceKey": QUERY_HISTORY,
            "destination": PERSONAL,
            "destinationKey": QUARANTINE,
            "overwrite": False,
        },
    )

    assert answer["statusCode"] == 200, answer["body"]
    assert any(call[0] == "copy_object" for call in client.calls)


def test_saving_an_athena_result_into_the_users_own_space_is_accepted(s3_and_signer) -> None:
    """`useSaveResults` is a single-object copy out of `athenaresults/`, which is a managed folder.

    Managed means the browser will not delete or move the FOLDER; reading an object out of it is
    ordinary, and a guard that inherited the listing exclusions would refuse this.

    Args:
      s3_and_signer: The stubbed identity doors.

    Returns:
      None.

    Raises:
      AssertionError: If the save is refused.
    """
    s3_and_signer(_Recording(present=False))

    answer = router.route(
        "POST",
        "/v1/objects/copy",
        bearer(),
        "rq",
        {
            "source": PERSONAL,
            "sourceKey": ATHENA_RESULT,
            "destination": PERSONAL,
            "destinationKey": ORDINARY_FILE,
            "overwrite": False,
        },
    )

    assert answer["statusCode"] == 200, answer["body"]


def test_an_upload_and_a_download_of_an_ordinary_file_both_mint(s3_and_signer) -> None:
    """The two presign routes, on the path every upload and download takes.

    Args:
      s3_and_signer: The stubbed identity doors.

    Returns:
      None.

    Raises:
      AssertionError: If either refuses.
    """
    s3_and_signer(_Recording(present=False))

    up = router.route(
        "POST",
        "/v1/objects/upload-url",
        bearer(),
        "rq",
        {"space": PERSONAL, "key": ORDINARY_FILE, "contentType": "text/csv", "overwrite": False},
    )
    down = router.route(
        "POST",
        "/v1/objects/download-url",
        bearer(),
        "rq",
        {"space": PERSONAL, "key": ORDINARY_FILE, "fileName": 'q1 "final".csv'},
    )

    assert up["statusCode"] == 200, up["body"]
    assert down["statusCode"] == 200, down["body"]
    assert json.loads(up["body"])["url"].startswith("https://")


def test_the_file_browsers_FIRST_listing_request_is_accepted(s3_and_signer) -> None:
    """The space root, with the prefix the browser sends for it.

    `assert_inside_root(root, "")` raises, so a listing prefix and an object key need different
    containment rules — and the very first request the file browser makes is the one that would
    trip it.

    Args:
      s3_and_signer: The stubbed identity doors.

    Returns:
      None.

    Raises:
      AssertionError: If the root listing is refused.
    """
    s3_and_signer(_Recording())

    at_root = router.route(
        "GET", "/v1/objects", bearer(), "rq", None, {"spaceKind": "personal", "spaceName": "alice"}
    )
    in_a_folder = router.route(
        "GET",
        "/v1/objects",
        bearer(),
        "rq",
        None,
        {"spaceKind": "personal", "spaceName": "alice", "prefix": "alice/reports/"},
    )

    assert at_root["statusCode"] == 200, at_root["body"]
    assert in_a_folder["statusCode"] == 200, in_a_folder["body"]


def test_the_free_name_request_a_same_folder_copy_sends_is_accepted(s3_and_signer) -> None:
    """One route call per gesture, with the prefix and leaf `useCopy` builds.

    Args:
      s3_and_signer: The stubbed identity doors.

    Returns:
      None.

    Raises:
      AssertionError: If the free-name request is refused.
    """
    s3_and_signer(_Recording(present=False))

    answer = router.route(
        "POST",
        "/v1/objects/free-name",
        bearer(),
        "rq",
        {"space": PERSONAL, "prefix": "alice/reports/", "baseName": "q1.csv", "kind": "file"},
    )

    assert answer["statusCode"] == 200, answer["body"]
    assert json.loads(answer["body"])["name"] == "q1 (1).csv"
