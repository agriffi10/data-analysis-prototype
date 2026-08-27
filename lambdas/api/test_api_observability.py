"""What this service records, what it must never record, and the correlation key it does not trust.

The field rule binds here more sharply than anywhere else in the fleet — user metadata in, file
contents out, tokens and emails always out — because this service holds a bearer token on every
single request.
"""

import json
from typing import TypedDict

import handler as api_handler
import router
from apicommon import contract


class _ClaimingBody(TypedDict):
    """A body that ASSERTS a username, declared so the contract accepts it.

    Declared rather than omitted on purpose: the point of the tests below is that a
    caller-stated username cannot reach the session tags, and a body the transport refuses
    before dispatch would prove that by never arriving. This one is admitted all the way to
    the router and still cannot influence anything.
    """

    username: str
from conftest import StubS3, bearer, declare_route, directory_document, token

_ECHO_ROUTE = contract.Route(
    id="obs.echo",
    method="POST",
    path="/v1/obs-echo",
    idempotent=False,
    plane="user",
    request=_ClaimingBody,
    response=contract.UserDirectoryResponse,
)


def _event(method, path, headers, body=None, request_id="gateway-1"):
    """Builds an API Gateway payload-format-2.0 event.

    Args:
      method: The request method.
      path: The request path.
      headers: The request headers.
      body: The raw request body, already serialized.
      request_id: The gateway's id for the request.

    Returns:
      The event.

    Raises:
      None.
    """
    event = {
        "requestContext": {"http": {"method": method, "path": path}, "requestId": request_id},
        "headers": headers,
    }
    if body is not None:
        event["body"] = body
    return event


def _fields(events):
    """Every record's stamped fields.

    Args:
      events: The captured records.

    Returns:
      The field dicts.

    Raises:
      None.
    """
    return [event["fields"] for event in events if isinstance(event.get("fields"), dict)]


def test_the_correlation_id_is_the_GATEWAYS_and_never_the_callers(captured_events) -> None:
    """The trap this service walks into by doing nothing.

    ``cpcommon.observability`` reads a top-level ``requestId`` and then falls back to parsing
    ``body`` as JSON — and an API Gateway v2 event's body IS a JSON string. A submit shape carries
    a browser-supplied ``requestId``, so left implicit this service's correlation key would be a
    value the caller chose. This can fail today and would have failed a naive implementation.

    Args:
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If any record carries the caller's value as its correlation key.
    """
    api_handler.handler(
        _event(
            "POST",
            "/v1/obs-echo",
            bearer(),
            body=json.dumps({"requestId": "spoofed"}),
            request_id="gateway-77",
        ),
        None,
    )

    serialised = json.dumps(captured_events.events)
    assert "spoofed" not in serialised, (
        "the caller chose this service's correlation key by putting one in the body"
    )
    assert any(fields.get("request_id") == "gateway-77" for fields in _fields(captured_events.events))


def test_a_client_supplied_request_id_is_recorded_separately_and_only_if_it_is_a_uuid(
    captured_events, stub_directory
) -> None:
    """A field the caller controls is a field, never a key.

    Args:
      captured_events: The capturing sink.
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If a non-UUID value is recorded, or a valid one is dropped.
    """
    api_handler.handler(
        _event(
            "GET",
            "/v1/user-directory",
            {**bearer(), "x-request-id": "3f0a1c88-0f4e-4a2f-9d3b-2b1f0c9a7e55"},
        ),
        None,
    )
    valid = _fields(captured_events.events)
    assert any(
        fields.get("client_request_id") == "3f0a1c88-0f4e-4a2f-9d3b-2b1f0c9a7e55"
        for fields in valid
    )

    captured_events.events.clear()
    api_handler.handler(
        _event("GET", "/v1/user-directory", {**bearer(), "x-request-id": "../../etc/passwd"}),
        None,
    )
    assert "etc/passwd" not in json.dumps(captured_events.events)
    assert all(
        fields.get("client_request_id") is None for fields in _fields(captured_events.events)
    )


def test_each_request_stamps_the_route_the_method_and_the_actor(
    captured_events, stub_directory
) -> None:
    """The fields a WHERE clause wants, and the username is metadata rather than content.

    The route travels as a stamped field rather than as the span name: ``traced`` names the span
    at decoration time and there is exactly one entry point, so a per-route span name is not
    available — and a field is what a query wants anyway.

    Args:
      captured_events: The capturing sink.
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If any is absent.
    """
    api_handler.handler(_event("GET", "/v1/user-directory", bearer("alice")), None)

    fields = _fields(captured_events.events)
    assert any(f.get("route_id") == "userDirectory.get" for f in fields)
    assert any(f.get("method") == "GET" for f in fields)
    assert any(f.get("username") == "alice" for f in fields)


def test_the_usernames_ARRAY_is_never_recorded_and_the_count_is(
    captured_events, stub_directory
) -> None:
    """The directory is the contents of an S3 object, which the field rule puts out of bounds.

    The obvious wrong implementation is a helper that stamps the response body, and it would look
    like good telemetry.

    Args:
      captured_events: The capturing sink.
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If any username reaches a record, or the count is absent.
    """
    stub_directory(_stub_serving(["alice", "bob_smith", "carol"]))

    api_handler.handler(_event("GET", "/v1/user-directory", bearer("alice")), None)

    serialised = json.dumps(captured_events.events)
    assert "bob_smith" not in serialised, "the directory's contents reached the operator store"
    assert "carol" not in serialised
    assert any(f.get("username_count") == 3 for f in _fields(captured_events.events))


def _stub_serving(usernames):
    """A user-plane S3 client serving a document carrying those usernames.

    Args:
      usernames: The names the document lists.

    Returns:
      The stub.

    Raises:
      None.
    """
    return StubS3(payload=directory_document(usernames=usernames))


def test_no_bearer_and_no_email_reaches_any_record(captured_events, stub_directory) -> None:
    """This service holds a token on every request, so the rule is asserted on every path.

    Args:
      captured_events: The capturing sink.
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If a token segment or an email address is recorded.
    """
    supplied = token("alice", email="someone@example.test")
    header = {"authorization": f"Bearer {supplied}"}

    api_handler.handler(_event("GET", "/v1/user-directory", header), None)
    api_handler.handler(_event("GET", "/v1/nope", header), None)
    api_handler.handler(_event("GET", "/v1/user-directory", {}), None)

    serialised = json.dumps(captured_events.events)
    for segment in supplied.split("."):
        assert segment not in serialised, "a token segment survived into a record"
    assert "someone@example.test" not in serialised
    assert "@" not in serialised
    assert "Bearer" not in serialised


def test_a_route_that_is_not_served_is_still_recorded_with_a_bounded_route(
    captured_events,
) -> None:
    """The unserved path is where an unbounded caller-supplied value would land.

    Args:
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If nothing is recorded, or the recorded route is unbounded.
    """
    router.route("GET", "/v1/" + "b" * 4000, bearer(), "req-9")

    routes = [f["route"] for f in _fields(captured_events.events) if "route" in f]
    assert routes
    for recorded in routes:
        assert len(recorded) <= 2 * router.MAX_ECHOED_CHARS + 1


def test_no_module_under_routes_names_a_credential() -> None:
    """The bearer never reaches a handler; the router verifies it and discards it before dispatch.

    Structural rather than habitual: a handler that cannot name the header cannot read it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any route module names one.
    """
    import pathlib

    here = pathlib.Path(__file__).resolve().parent
    for path in sorted((here / "routes").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("authorization", "Authorization", "bearer", "id_token"):
            assert forbidden not in source, f"{path.name} names {forbidden!r}"


def test_a_handler_receives_no_way_to_read_what_the_caller_said_about_themselves() -> None:
    """The query string and the body never leave the entry point.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a handler can see a caller-stated value.
    """
    seen = {}

    def _capture(context):
        seen["context"] = context
        return {"usernames": [], "generatedAt": None}

    with declare_route(_ECHO_ROUTE, _capture):
        api_handler.handler(
            _event(
                "POST",
                "/v1/obs-echo",
                bearer("alice"),
                body=json.dumps({"username": "mallory"}),
            ),
            None,
        )

    context = seen["context"]
    assert context.principal.username == "alice"
    assert "mallory" not in json.dumps(
        {"route": context.route, "request_id": context.request_id}
    )
    assert not hasattr(context, "body")
    assert not hasattr(context, "event")
    assert not hasattr(context, "headers")


def test_every_answer_records_its_HTTP_STATUS_and_its_wire_code(
    captured_events, stub_directory
) -> None:
    """The span's status is not the HTTP status, and conflating them records nothing.

    Every enveloped failure is RETURNED rather than raised, so the span closes successfully for a
    401, a 403 and a 404 alike — a query filtering on the span status finds one value for every
    outcome the API has. These are the fields a `WHERE` clause actually wants.

    Args:
      captured_events: The capturing sink.
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If a status or a failure code is absent.
    """
    cases = [
        (_event("GET", "/v1/user-directory", bearer("alice")), 200, None),
        (_event("GET", "/v1/user-directory", {}), 401, "SessionExpired"),
        (_event("GET", "/v1/nope", bearer()), 404, "NotFound"),
        (_event("OPTIONS", "/v1/user-directory", {}), 200, None),
    ]

    for event, status, code in cases:
        captured_events.events.clear()
        api_handler.handler(event, None)
        fields = _fields(captured_events.events)

        assert any(f.get("status") == status for f in fields), f"no record carried status {status}"
        if code is None:
            assert all("code" not in f for f in fields), "a success recorded a failure code"
        else:
            assert any(f.get("code") == code for f in fields), f"no record carried code {code}"


def test_the_verified_username_is_recorded_as_the_ACTOR(captured_events, stub_directory) -> None:
    """Named as the field a later query joins on, not as whatever the identity layer happens to call it.

    Args:
      captured_events: The capturing sink.
      stub_directory: The stubbed user plane.

    Returns:
      None.

    Raises:
      AssertionError: If the actor is absent.
    """
    api_handler.handler(_event("GET", "/v1/user-directory", bearer("alice")), None)

    assert any(f.get("actor") == "alice" for f in _fields(captured_events.events))


def test_a_body_the_contract_does_not_declare_is_REFUSED_before_dispatch(captured_events) -> None:
    """The validator is on the runtime path, not merely unit-tested beside it.

    A validator nothing calls is a validator the first POST route inherits unwired — and the
    inheriting spec would have no way to notice, because its own tests would pass.

    Args:
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If an undeclared key reaches a handler, or is not answered 400.
    """
    reached = []

    with declare_route(_ECHO_ROUTE, lambda context: reached.append(1) or {}):
        response = api_handler.handler(
            _event("POST", "/v1/obs-echo", bearer(), body=json.dumps({"unknown": "key"})), None
        )

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == "InvalidRequest"
    assert reached == [], "the handler ran despite a body the contract does not declare"


def test_a_body_that_is_not_JSON_is_refused_rather_than_ignored(captured_events) -> None:
    """An absent body and an unparseable one are different facts.

    Answering the same for both would let a route declaring no body accept any bytes at all.

    Args:
      captured_events: The capturing sink.

    Returns:
      None.

    Raises:
      AssertionError: If arbitrary bytes are accepted.
    """
    event = _event("POST", "/v1/obs-echo", bearer())
    event["body"] = "<html>not json</html>"

    with declare_route(_ECHO_ROUTE, lambda context: {}):
        response = api_handler.handler(event, None)

    assert response["statusCode"] == 400
