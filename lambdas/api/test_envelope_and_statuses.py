"""The wire's shape: one success form, one failure form, and a closed set of statuses.

The assertions here are the ones five later ports copy without re-deciding, so each is about the
contract rather than about the one route that exists today.
"""

import json

import pytest
import router
from apicommon import contract, envelope
from conftest import bearer

_FAULT_ROUTE = contract.Route(
    id="envelope.fault",
    method="GET",
    path="/v1/envelope-fault",
    idempotent=True,
    plane="user",
    request=None,
    query=None,
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


def test_an_options_request_takes_the_ordinary_unauthenticated_refusal() -> None:
    """No browser calls this API, so an ``OPTIONS`` is not a preflight to answer before authentication.

    Driven for a path that exists and one that does not, and compared byte for byte with a ``GET``
    carrying no token, because an answer that differed would be a second door or an inventory.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If an ``OPTIONS`` is answered, or if its refusal differs from the no-token one.
    """
    existing = router.route("OPTIONS", "/v1/user-directory", {})
    absent = router.route("OPTIONS", "/v1/no-such-thing", {})
    no_token = router.route("GET", "/v1/user-directory", {})

    assert existing["statusCode"] == 401
    assert existing["body"] == absent["body"] == no_token["body"]
    assert not [name for name in existing.get("headers", {}) if name.lower().startswith("access-control-")]


@pytest.mark.parametrize(
    ("character", "wire_bytes"),
    [
        ("a", 1),
        ('"', 4),
        ("\\", 4),
        ("\n", 3),
        ("\x01", 7),
        ("\u0416", 7),
        ("\u4e2d", 7),
        ("\U0001f600", 14),
    ],
)
def test_a_response_is_measured_after_the_runtimes_second_escape(character, wire_bytes) -> None:
    """What one more character costs on the wire, counted by hand from both serializations.

    The first pass writes ``\\u0416`` for a Cyrillic letter, six bytes; the runtime escapes its
    backslash again, seven. A measurement of the stored or once-serialized size gives two or six
    and admits a response the runtime then cannot send.

    Args:
      character: One character of a document body.
      wire_bytes: What it adds to the response the runtime sends.

    Returns:
      None.

    Raises:
      AssertionError: If the measurement disagrees with the hand count.
    """
    once = envelope.served_bytes({"body": character})
    twice = envelope.served_bytes({"body": character * 2})

    assert twice - once == wire_bytes
