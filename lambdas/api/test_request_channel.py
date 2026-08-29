"""The request channel, and the guarantee that had to survive opening it.

``RequestContext`` once carried no request data at all, which made "a handler cannot read a
username the caller asserted" true *by shape* — there was nothing to read. SPEC-198's object
routes take ``{space, key}`` and cannot work that way, so the body and the query now reach a
handler. This module is what replaces the shape: the identity a handler is given is unchanged by
anything the caller says, the query vocabulary refuses a declaration a query string cannot carry,
and no route module reaches past the framework into the raw event.

The assertions are on the **resolved identity** and on **reason codes**, never on the absence of a
field name — the next field is called something else — and never on a bare call count, because a
refusal that fails safely passes a call-count assertion while returning the wrong status.
"""

import ast
import pathlib
from typing import NotRequired, TypedDict

import pytest
import router
from apicommon import contract
from conftest import bearer, declare_route

ROUTES_DIR = pathlib.Path(__file__).parent / "routes"


class _ClaimingQuery(TypedDict):
    """A query that ASSERTS a username, declared so the contract admits it.

    Declared rather than omitted for the reason the body twin beside it is: a query the transport
    refuses before dispatch would prove nothing, because it never arrives. This one reaches the
    handler and still cannot influence the identity.

    Attributes:
      username: The username the caller claims to be.
      spaceName: A space the caller names. FLAT, not a nested ``SpaceRef`` — a query string
        carries only strings, so the nested form is undeclarable here by construction.
    """

    username: str
    spaceName: NotRequired[str]


class _ClaimingBody(TypedDict):
    """A body that ASSERTS a username and an acting identity, declared so the contract admits it.

    Attributes:
      username: The username the caller claims to be.
      acting_as: The identity the caller asks to act as.
    """

    username: str
    acting_as: str


class _EchoResponse(TypedDict):
    """What the probe handler reports back about the identity it was given.

    Attributes:
      resolved: The username the framework resolved, from the verified token alone.
    """

    resolved: str


def _echo_route(query: object = None, request: object = _ClaimingBody) -> contract.Route:
    """Builds a probe route declaring caller-asserted identity fields.

    Args:
      query: The declared query type, or None.
      request: The declared body type, or None.

    Returns:
      The route.

    Raises:
      None.
    """
    return contract.Route(
        id="test.echoIdentity",
        method="GET",
        path="/v1/_test-echo-identity",
        idempotent=True,
        plane="user",
        request=request,
        query=query,
        response=_EchoResponse,
    )


def _echo_handler(context) -> _EchoResponse:  # type: ignore[no-untyped-def]
    """Reports the resolved identity, ignoring everything the caller asserted.

    Args:
      context: The request context.

    Returns:
      The resolved username.

    Raises:
      None.
    """
    return {"resolved": context.acting_as.username}


class TestTheIdentityAHandlerIsGivenIgnoresWhatTheCallerSaid:
    """FR-014 AC4 — the guarantee the shape used to provide."""

    def test_a_body_and_a_query_naming_another_user_do_not_move_the_identity(self) -> None:
        """A request asserting a different user resolves to the verified one."""
        with declare_route(_echo_route(query=_ClaimingQuery), _echo_handler):
            answer = router.route(
                "GET",
                "/v1/_test-echo-identity",
                bearer(),
                "rq",
                {"username": "mallory", "acting_as": "mallory"},
                {"username": "mallory", "spaceName": "mallory"},
            )

        assert answer["statusCode"] == 200
        assert "mallory" not in answer["body"]
        assert "alice" in answer["body"]

    def test_the_asserted_fields_do_reach_the_handler(self) -> None:
        """The probe is not vacuous: the claimed values really did arrive.

        Without this, the test above would pass against a transport that dropped the body — which
        is the state this whole module exists to move away from, and it would look identical.
        """
        seen: dict[str, object] = {}

        def _capture(context) -> _EchoResponse:  # type: ignore[no-untyped-def]
            seen["body"] = context.body
            seen["query"] = dict(context.query)
            return {"resolved": context.acting_as.username}

        with declare_route(_echo_route(query=_ClaimingQuery), _capture):
            router.route(
                "GET",
                "/v1/_test-echo-identity",
                bearer(),
                "rq",
                {"username": "mallory", "acting_as": "mallory"},
                {"username": "mallory"},
            )

        assert seen["body"] == {"username": "mallory", "acting_as": "mallory"}
        assert seen["query"] == {"username": "mallory"}


class TestAQueryDeclarationIsRefusedForWhatAQueryStringCannotCarry:
    """FR-014 AC3 — the vocabulary narrows in query position, at declaration time."""

    def test_a_flat_all_strings_query_is_accepted(self) -> None:
        """The shape a GET route must use."""
        contract._check_query(_echo_route(query=_ClaimingQuery))

    @pytest.mark.parametrize(
        ("name", "declared"),
        [
            ("a nested object", TypedDict("_Nested", {"space": _EchoResponse})),
            ("an int", TypedDict("_Int", {"maxKeys": int})),
            ("a bool", TypedDict("_Bool", {"recursive": bool})),
            ("a list", TypedDict("_List", {"keys": list[str]})),
        ],
    )
    def test_a_query_field_a_query_string_cannot_carry_is_refused(self, name, declared) -> None:
        """Each is refused when the route is DECLARED, not when a request arrives.

        Accepted, each of these emits clean TypeScript and then refuses every real request with a
        400 the handler never sees, because the gateway delivers all strings. A build-time
        refusal; never a per-request one.
        """
        with pytest.raises(contract.UnsupportedTypeError) as raised:
            contract._check_query(_echo_route(query=declared))

        assert "only strings" in str(raised.value), name

    def test_the_gateway_all_strings_payload_validates(self) -> None:
        """The payload API Gateway actually sends is what the declaration accepts."""
        route = _echo_route(query=_ClaimingQuery)
        assert contract.validate_query(route, {"username": "a", "spaceName": "b"}) is None

    def test_an_undeclared_query_is_refused(self) -> None:
        """A route declaring no query refuses one, rather than ignoring it.

        This makes `GET /v1/user-directory?x=1` a 400 where it was previously ignored — a
        deliberate tightening, recorded rather than slipped in. It matches the body's own rule,
        where an unknown key is refused as firmly as a missing one: a caller and a server that
        disagree about the shape should find out at once.
        """
        assert contract.validate_query(_echo_route(query=None), {"x": "1"}) == "InvalidRequest"

    def test_an_unknown_query_key_is_refused(self) -> None:
        """Refused as firmly as a missing one — the body's own rule, applied here."""
        route = _echo_route(query=_ClaimingQuery)
        assert contract.validate_query(route, {"username": "a", "nope": "1"}) == "InvalidRequest"


class TestNoRouteReachesPastTheFramework:
    """A route reads what it was handed, and nothing else."""

    def test_the_sweep_reaches_the_modules_it_claims_to(self) -> None:
        """Guard the guard: over an empty file list, `offenders == []` passes vacuously."""
        modules = sorted(ROUTES_DIR.glob("*.py"))
        assert len(modules) >= 6, f"the sweep resolved onto {len(modules)} route modules"

    def test_no_route_module_names_the_raw_event_or_headers(self) -> None:
        """Parsed, not grepped: a comment mentioning `event` is not a read of one."""
        offenders: list[str] = []
        for module in sorted(ROUTES_DIR.glob("*.py")):
            tree = ast.parse(module.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in {"event", "headers"}:
                    offenders.append(f"{module.name}:{node.lineno} reads {node.id}")

        assert offenders == []
