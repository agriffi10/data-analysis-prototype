"""The flag document's own route, and why it is its own route.

The browser read this document through the same helper as its settings documents, and the port
could not carry it: ``_config/`` belongs to no user and to no shared space, so the space resolver
refuses it — correctly. Routing it through the object surface would have meant teaching that
resolver about a prefix nobody owns, and every other object route would have inherited the
exemption. The username directory hit the same wall first and was solved the same way.

**The failure this file exists to catch is silent.** A flag document that cannot be read resolves
to the compiled-in defaults, which are all-on — indistinguishable from a healthy environment. So a
route that read the wrong key, or answered an empty body, would look exactly like one that worked.
"""

import json

import pytest
import router
from conftest import StubS3, bearer

FLAG_DOCUMENT = json.dumps(
    {"version": 1, "defaults": {"files": True}, "environments": {"prod": {}}}
).encode("utf-8")


class _ServiceError(Exception):
    """A botocore-shaped client error, built here rather than imported.

    ``botocore`` is provided by the Lambda runtime and declared as a dependency nowhere, so
    importing it passes on a laptop with boto3 and fails on the runner.
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


def _get():
    """Runs one authenticated request against the route.

    Args:
      None.

    Returns:
      The response.

    Raises:
      None.
    """
    return router.route("GET", "/v1/feature-flags", bearer(), "r1")


def test_it_reads_the_key_the_publish_workflow_writes(monkeypatch, stub_directory) -> None:
    """The route and the workflow must name one object, or every flag falls back in silence.

    Args:
      monkeypatch: Pytest's patcher.
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If it reads a different bucket or key.
    """
    monkeypatch.setenv("USER_SPACE_BUCKET", "dat-prod-user-space")
    stub = stub_directory(StubS3(payload=FLAG_DOCUMENT))

    response = _get()

    assert response["statusCode"] == 200
    assert stub.calls == [
        {"Bucket": "dat-prod-user-space", "Key": "_config/feature-flags.json"}
    ]


def test_the_bytes_leave_UNPARSED(stub_directory) -> None:
    """The browser's reader is three-way, and parsing here would collapse two of its arms.

    A document of an unsupported version is refused rather than guessed at, and "read but unusable"
    is what lets the app report that it is running on compiled-in defaults. Parsed server-side,
    both become a 500 and the fallback becomes unreportable.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If the route returns anything but the stored bytes.
    """
    malformed = b'{"version": 1, "defaults": {'
    stub_directory(StubS3(payload=malformed))

    response = _get()

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["body"] == malformed.decode("utf-8")


def test_a_document_that_was_never_published_is_a_404(stub_directory) -> None:
    """A missing document is a DEPLOY defect, not the ordinary starting state.

    The opposite of the directory's choice, and deliberately so: no directory means no suggestions,
    which is honest, while no flag document means the publish workflow has never run here.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If absence is reported as anything but a 404.
    """
    stub_directory(StubS3(error=_ServiceError("NoSuchKey")))

    response = _get()

    assert response["statusCode"] == 404
    assert json.loads(response["body"])["error"]["code"] == "NotFound"


def test_a_DENIAL_is_a_real_fault_and_not_an_absent_document(stub_directory) -> None:
    """Folding a denial into the missing arm would answer 404 for a bucket nobody could read.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If a denial is reported as absence.
    """
    stub_directory(StubS3(error=_ServiceError("AccessDenied", "denied")))

    response = _get()

    assert response["statusCode"] == 403


def test_an_unauthenticated_request_makes_ZERO_aws_calls(stub_directory) -> None:
    """Asserted by call count: a 401 issued after a successful read looks identical from outside.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If the route reached AWS before refusing.
    """
    stub = stub_directory(StubS3(payload=FLAG_DOCUMENT))

    response = router.route("GET", "/v1/feature-flags", {}, "r1")

    assert response["statusCode"] == 401
    assert stub.calls == []


@pytest.mark.parametrize("field", ["idempotent", "plane"])
def test_the_route_declares_what_every_route_must(field) -> None:
    """A read on the caller's own session, safely retried above the transport.

    Args:
      field: The declaration under test.

    Returns:
      None.

    Raises:
      AssertionError: If the declaration is not the one this route needs.
    """
    from apicommon import contract

    route = next(r for r in contract.ROUTES if r.id == "featureFlags.get")

    assert {"idempotent": True, "plane": "user"}[field] == getattr(route, field)
