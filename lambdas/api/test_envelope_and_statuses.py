"""The wire's shape: one success form, one failure form, and a closed set of statuses.

The assertions here are the ones five later ports copy without re-deciding, so each is about the
contract rather than about the one route that exists today.
"""

import json

import router
from apicommon import contract
from conftest import bearer

_FAULT_ROUTE = contract.Route(
    id="envelope.fault",
    method="GET",
    path="/v1/envelope-fault",
    idempotent=True,
    plane="user",
    request=None,
    response=contract.UserDirectoryResponse,
)


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
