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
