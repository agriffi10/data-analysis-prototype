"""The wire's shape: one success form, one failure form, and a closed set of statuses.

The assertions here are the ones five later ports copy without re-deciding, so each is about the
contract rather than about the one route that exists today.
"""

import json

import pytest
import router
from apicommon import contract, envelope, errors
from conftest import bearer, declare_route


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


_FAULT_ROUTE = contract.Route(
    id="envelope.fault",
    method="GET",
    path="/v1/envelope-fault",
    idempotent=True,
    plane="user",
    request=None,
    response=contract.UserDirectoryResponse,
)


def _drive(handler, method="GET", path="/v1/envelope-fault", headers=None):
    """Runs one request against a temporary route.

    Args:
      handler: The route handler.
      method: The request method.
      path: The request path.
      headers: The request headers; an authenticated set by default.

    Returns:
      The response.

    Raises:
      Exception: Whatever the handler raised and the router did not classify.
    """
    with declare_route(_FAULT_ROUTE, handler):
        return router.route(method, path, bearer() if headers is None else headers, "req-1")


def test_every_response_is_json_with_a_charset_and_is_never_cached(stub_directory) -> None:
    """A caching layer between the browser and an authorized read is a cross-user disclosure.

    Silent, too: the first user sees exactly the right answer, and only the second one is wrong.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If any response omits either header.
    """
    responses = [
        router.route("GET", "/healthz", {}),
        router.route("GET", "/v1/user-directory", bearer()),
        router.route("GET", "/v1/nope", bearer()),
        router.route("GET", "/v1/user-directory", {}),
        router.route("OPTIONS", "/v1/user-directory", {}),
    ]

    for response in responses:
        assert response["headers"]["content-type"] == "application/json; charset=utf-8"
        assert response["headers"]["cache-control"] == "no-store"


def test_no_response_is_body_less_and_none_is_a_204_or_a_redirect(stub_directory) -> None:
    """One parse path for the client, so a body is never conditionally present.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If any response omits a body or answers outside the closed set.
    """
    responses = [
        router.route("GET", "/healthz", {}),
        router.route("GET", "/v1/user-directory", bearer()),
        router.route("GET", "/v1/nope", bearer()),
        router.route("GET", "/v1/user-directory", {}),
        router.route("OPTIONS", "/v1/anything", {}),
    ]

    for response in responses:
        assert response["body"], "a body-less response gives the client a second parse path"
        assert json.loads(response["body"]) is not None
        assert response["statusCode"] in contract.ROUTE_STATUSES
        assert response["statusCode"] != 204
        assert not 300 <= response["statusCode"] < 400


def test_a_success_body_is_the_payload_itself_and_is_always_an_object(stub_directory) -> None:
    """No wrapper. A ``{data: …}`` level is one every ported service would strip forever.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If a success body is wrapped or is not an object.
    """
    body = json.loads(router.route("GET", "/v1/user-directory", bearer())["body"])

    assert isinstance(body, dict)
    assert "data" not in body
    assert set(body) == {"usernames", "generatedAt"}


def test_a_failure_body_is_the_only_wrapped_shape_and_its_keys_are_the_DECLARED_ones() -> None:
    """Asserted against the contract's own error type, never against a literal written here.

    A frozen literal would make a later spec's typed ``params`` object a contradiction rather than
    an addition. What is frozen is the CHARACTER of the fields — no key the browser renders as
    prose — and that is upheld by the client-side disjointness guard, not by this assertion.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the emitted key set is not the declared one.
    """
    declared = contract.walk(contract.ApiErrorDetail)
    declared_keys = {name for name, _, _ in declared.fields}
    required = {name for name, _, required in declared.fields if required}

    body = json.loads(router.route("GET", "/v1/nope", bearer())["body"])

    assert set(body) == {"error"}
    assert required <= set(body["error"]) <= declared_keys


def test_an_unregistered_pair_is_a_404_including_the_case_a_reader_assumes_is_a_405() -> None:
    """One rule. A 405 would advertise which paths exist to a caller who may not use them.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either answers anything but 404.
    """
    unknown_path = router.route("GET", "/v1/no-such-thing", bearer())
    wrong_method = router.route("POST", "/v1/user-directory", bearer())

    assert unknown_path["statusCode"] == 404
    assert wrong_method["statusCode"] == 404, (
        "a registered path with an unregistered method must not answer 405"
    )
    assert json.loads(wrong_method["body"])["error"]["code"] == errors.NOT_FOUND_CODE


def test_a_preflight_is_answered_before_authentication_and_discloses_nothing() -> None:
    """``$default`` matches OPTIONS, so the gateway's own CORS responder never sees one.

    A preflight refused as unauthenticated fails the browser's CORS check, and every
    bearer-carrying request then fails as an opaque network error with nothing on the wire to
    explain it. Driven for a path that exists and one that does not, because an answer that
    differed between them would be an inventory.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a preflight is refused, or if it distinguishes the two.
    """
    existing = router.route("OPTIONS", "/v1/user-directory", {})
    absent = router.route("OPTIONS", "/v1/no-such-thing", {})

    assert existing["statusCode"] == 200
    assert absent["statusCode"] == 200
    assert existing == absent, "a preflight that varies by path is an inventory of the routes"
    assert json.loads(existing["body"]) == {}


def test_no_response_carries_a_cors_header_of_its_own(stub_directory) -> None:
    """Two sources able to answer one question is how they come to disagree.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If any response emits one.
    """
    responses = [
        router.route("OPTIONS", "/v1/user-directory", {}),
        router.route("GET", "/v1/user-directory", bearer()),
        router.route("GET", "/v1/nope", bearer()),
        router.route("GET", "/healthz", {}),
    ]

    for response in responses:
        for name in response["headers"]:
            assert not name.lower().startswith("access-control-")


def test_an_unhandled_exception_becomes_InternalError_and_carries_only_the_TYPE() -> None:
    """The outermost mapping, and the reason it names a type rather than a message.

    A message is where a bucket name, a key, a role ARN or a caller's own value ends up.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the message survives into the body, or the code escapes the enum.
    """
    import handler as api_handler

    def _explode(context):
        raise RuntimeError("secret value")

    with declare_route(_FAULT_ROUTE, _explode):
        response = api_handler.handler(
            {
                "requestContext": {
                    "http": {"method": "GET", "path": "/v1/envelope-fault"},
                    "requestId": "req-1",
                },
                "headers": bearer(),
            },
            None,
        )

    assert response["statusCode"] == 500
    body = json.loads(response["body"])
    assert body["error"]["code"] == "InternalError"
    assert body["error"]["detail"] == "RuntimeError"
    assert "secret value" not in response["body"]


def test_raw_aws_text_never_reaches_the_body() -> None:
    """A denial's own message names a role ARN and an account id. Neither is the caller's.

    The same assertion the identity layer makes, now at the layer that serialises it — because
    the serialiser is the last place either could be added back, and it would look like context.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any of the service's text survives into the response.
    """
    denial = _ServiceError(
        "AccessDenied",
        "User: arn:aws:sts::696000197480:assumed-role/dat-portal-user-role/alice "
        "is not authorized to perform: s3:ListBucket",
    )

    def _denied(context):
        raise denial

    response = _drive(_denied)

    assert response["statusCode"] == 403
    for leaked in ("696000197480", "dat-portal-user-role", "assumed-role", "s3:ListBucket"):
        assert leaked not in response["body"], f"{leaked} reached the caller"


def test_a_handler_may_name_its_own_refusal_and_cannot_invent_a_code() -> None:
    """An expected refusal is a return value with a declared code, not an improvised status.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a declared code does not serialise, or an undeclared one is accepted.
    """
    def _conflicting(context):
        raise envelope.ApiError("Conflict", "the destination name is taken")

    response = _drive(_conflicting)

    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"]["code"] == "Conflict"
    assert json.loads(response["body"])["error"]["detail"] == "the destination name is taken"

    with pytest.raises(KeyError):
        envelope.ApiError("MadeUpCode")


def test_the_detail_is_omitted_rather_than_null_when_there_is_none() -> None:
    """An absent key and a null one are the same fact, and one of them invites a reader.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the key is present with no value.
    """
    body = json.loads(envelope.failure("NotFound", "req-1")["body"])

    assert "detail" not in body["error"]


def test_the_request_id_in_the_envelope_is_the_one_the_gateway_gave(stub_directory) -> None:
    """A user quoting it has to find the right record, not a request that resembles theirs.

    Args:
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If the id is absent or invented.
    """
    response = router.route("GET", "/v1/nope", bearer(), "gateway-req-77")

    assert json.loads(response["body"])["error"]["requestId"] == "gateway-req-77"
