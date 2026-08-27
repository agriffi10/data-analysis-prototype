"""The ported route, and the four assertions that moved here from the browser.

The measure of a good port is that no assertion is quietly lost on the way. Four of the ten that
covered `userDirectory.service.ts` moved into this file with their reasoning carried over, three
are kept on BOTH sides, and three stayed in the browser because they are about the transport
rather than about the document. The disposition table is reproduced in the delivery doc, because
"we moved the tests" is exactly the claim nobody can check a year later.

The four here:
  reads the key the builder publishes, from the user-space bucket
  a corrupt document is the empty state
  an unsupported version is the empty state, and names the version it saw
  a non-array ``usernames`` field is the empty state
"""

import json

import router
from apicommon import identity
from conftest import StubS3, bearer, directory_document


class _ServiceError(Exception):
    """A botocore-shaped client error, built here rather than imported.

    `botocore` is provided by the Lambda runtime and is declared as a dependency nowhere, so it is
    absent in CI — importing it passes on a laptop that happens to have boto3 and fails on the
    runner. The identity layer classifies by reading `response["Error"]["Code"]`, which is all the
    shape any of this needs.
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



def _get(headers=None):
    """Runs one authenticated request against the route.

    Args:
      headers: The request headers; an authenticated set by default.

    Returns:
      The response.

    Raises:
      None.
    """
    return router.route("GET", "/v1/user-directory", bearer() if headers is None else headers, "r1")


def _body(response):
    """The response's parsed body.

    Args:
      response: The router's response.

    Returns:
      The parsed body.

    Raises:
      None.
    """
    return json.loads(response["body"])


def test_it_reads_the_key_the_builder_publishes_from_the_user_space_bucket(
    monkeypatch, stub_directory
) -> None:
    """MOVED from the browser. The route and the builder must name one object.

    Args:
      monkeypatch: Pytest's patcher.
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If it reads a different bucket or key.
    """
    monkeypatch.setenv("USER_SPACE_BUCKET", "dat-prod-user-space")
    stub = stub_directory(StubS3(payload=directory_document()))

    response = _get()

    assert response["statusCode"] == 200
    assert stub.calls == [{"Bucket": "dat-prod-user-space", "Key": "_directory/usernames.json"}]


def test_a_missing_document_is_the_empty_state_and_never_a_404(stub_directory) -> None:
    """BOTH SIDES. The ordinary state of the bucket until the builder's first run.

    This deliberately inverts the usual S3-404-to-API-404 mapping. An unavailable suggestion list
    means no suggestions, not an error banner — the feature's whole promise is that it stays out
    of the way, and every consumer accepts a name that is not in the list anyway.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If a missing object produces anything but the empty success.
    """
    stub_directory(StubS3(error=_ServiceError("NoSuchKey", "does not exist")))

    response = _get()

    assert response["statusCode"] == 200
    assert _body(response) == {"usernames": [], "generatedAt": None}


def test_a_corrupt_document_is_the_empty_state(stub_directory) -> None:
    """MOVED. A body that is not JSON is as empty as one that is JSON of the wrong shape.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If an unparseable body is not the empty success.
    """
    stub_directory(StubS3(payload=b"{not json"))

    response = _get()

    assert response["statusCode"] == 200
    assert _body(response) == {"usernames": [], "generatedAt": None}


def test_an_unsupported_version_is_refused_and_NAMED(captured_events, stub_directory) -> None:
    """MOVED, as a warning rather than a console line.

    A shape this reader does not understand is not a shape it should guess at. Named rather than
    silent, because the fix is a code change and somebody has to know that — the browser's
    ``console.warn`` moved here, it was not deleted.

    Args:
      captured_events: The capturing sink.
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If the document is read, or the version is not recorded.
    """
    stub_directory(StubS3(payload=directory_document(version=2)))

    response = _get()

    assert _body(response) == {"usernames": [], "generatedAt": None}
    serialised = json.dumps(captured_events.events)
    assert "unsupported version" in serialised
    assert '"found_version": "2"' in serialised
    assert '"supported_version": 1' in serialised


def test_a_non_array_usernames_field_is_the_empty_state(stub_directory) -> None:
    """MOVED. The document is one ``aws s3 cp`` away from holding anything at all.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If a non-array field is read as a list.
    """
    stub_directory(
        StubS3(payload=json.dumps({"version": 1, "usernames": {"alice": True}}).encode())
    )

    response = _get()

    assert _body(response) == {"usernames": [], "generatedAt": None}


def test_every_entry_is_re_checked_against_the_catalog_safe_rule(stub_directory) -> None:
    """BOTH SIDES. A producer guarantee is not a runtime guarantee.

    The builder already promises this. The API re-checks because it is now a SECOND producer, and
    the browser re-checks because the array is rendered into the DOM and used to build keys.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If an unsafe entry survives.
    """
    stub_directory(
        StubS3(
            payload=json.dumps(
                {
                    "version": 1,
                    "usernames": ["alice", "Bob", "../etc/passwd", 42, "", "cara"],
                    "generatedAt": "2026-08-05T04:00:11Z",
                }
            ).encode()
        )
    )

    response = _get()

    assert _body(response)["usernames"] == ["alice", "cara"]


def test_a_non_string_generated_at_is_dropped_and_the_usernames_survive(stub_directory) -> None:
    """BOTH SIDES.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If a non-string timestamp reaches the wire.
    """
    stub_directory(
        StubS3(payload=json.dumps({"version": 1, "usernames": ["alice"], "generatedAt": 12345}).encode())
    )

    response = _get()

    assert _body(response) == {"usernames": ["alice"], "generatedAt": None}


def test_the_wire_shape_carries_no_version_and_no_count(stub_directory) -> None:
    """The document's shape is the server's business now.

    A field the browser does not read is a field a later change has to keep true.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If the stored document's own fields reach the wire.
    """
    stub_directory(StubS3(payload=directory_document()))

    body = _body(_get())

    assert set(body) == {"usernames", "generatedAt"}


def test_a_DENIAL_is_a_real_fault_and_not_an_empty_directory(stub_directory) -> None:
    """The forgiving path is for an unavailable DOCUMENT, never for an unreadable BUCKET.

    Swallowing a denial here would report an empty directory for a bucket nobody could read — the
    one failure that looks exactly like the ordinary pre-builder state.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If a denial is reported as an empty success.
    """
    stub_directory(StubS3(error=_ServiceError("AccessDenied", "denied")))

    response = _get()

    assert response["statusCode"] == 403


def test_an_unauthenticated_request_makes_ZERO_aws_calls(monkeypatch) -> None:
    """The negative control this route CAN carry.

    Asserted by call count, because a 401 issued *after* a successful downstream read looks
    identical from the outside — and the whole point of refusing early is that the refusal costs
    nothing and reaches no service.

    Args:
      monkeypatch: Pytest's patcher.

    Returns:
      None.

    Raises:
      AssertionError: If any AWS call is made for a refused request.
    """
    reached = []

    monkeypatch.setattr(
        identity, "user_client", lambda service, acting_as: reached.append(service)
    )
    monkeypatch.setattr(
        identity, "for_request", lambda caller: reached.append("assume") or None
    )

    for headers in ({}, {"authorization": "Bearer not-a-token"}):
        assert _get(headers)["statusCode"] == 401

    assert reached == [], "a refused request reached AWS"


def test_the_route_answers_no_store_like_every_other(stub_directory) -> None:
    """The rule is per-API, not per-route, and a per-route exception is how the next one gets it wrong.

    The document is identical for every user, which is exactly the argument someone will make for
    caching it — and the reason the rule is stated at the transport rather than per route.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If the response is cacheable.
    """
    response = _get()

    assert response["headers"]["cache-control"] == "no-store"


def test_the_route_does_not_truncate(stub_directory) -> None:
    """Truncating server-side would silence the browser's cap warning.

    That warning is the only signal the directory has outgrown its index, and the response is
    sized for the whole list: the cap's worth of maximum-length catalog names, JSON-encoded, is
    about 1.3 MB against a 6 MB synchronous payload limit.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If the route drops entries.
    """
    many = [f"user{index:06d}" for index in range(5000)]
    stub_directory(StubS3(payload=directory_document(usernames=many)))

    body = _body(_get())

    assert len(body["usernames"]) == 5000
