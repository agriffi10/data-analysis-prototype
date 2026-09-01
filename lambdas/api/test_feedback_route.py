"""The feedback route, driven through the router.

The load-bearing assertions are about what reaches the QUEUE and about who the submission is
attributed to. A route that answers 200 and sends the wrong username has no symptom anywhere: the
caller sees success, the writer sees a well-formed message, and the wrong name is in a file nobody
reads until somebody follows it up.

Refusals are counted against a client that records everything, because a 400 issued AFTER a
successful send looks identical to one issued before it from the caller's side.
"""

import json

import handler as api_handler
import pytest
import router
from apicommon import contract
from apicommon import identity as identity_module
from conftest import bearer
from routes import feedback

ROUTE = contract.route_by_id("feedback.submit")

QUEUE_URL = "https://sqs.test/1/dat-prod-feedback-requests.fifo"


class _ServiceError(Exception):
    """A botocore-shaped client error, built here rather than imported.

    Attributes:
      response: The shape the error classifier reads a code out of.
    """

    def __init__(self, code):
        """Builds the error.

        Args:
          code: The service error code.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class RecordingSqs:
    """An SQS client that records every send, so a refusal's cost can be counted.

    Attributes:
      sends: The keyword arguments of every ``send_message``, in order.
    """

    def __init__(self, raises=None):
        """Builds the fake.

        Args:
          raises: An exception to raise instead of sending, or None.

        Returns:
          None.

        Raises:
          None.
        """
        self.sends = []
        self._raises = raises

    def send_message(self, **kwargs):
        """Records one send.

        Args:
          **kwargs: The send request.

        Returns:
          A message id.

        Raises:
          Exception: Whatever this fake was configured to raise.
        """
        self.sends.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return {"MessageId": "m1"}


@pytest.fixture(autouse=True)
def _queue_environment(monkeypatch):
    """Sets the one variable this route reads.

    Args:
      monkeypatch: pytest's patcher.

    Returns:
      None.

    Raises:
      None.
    """
    monkeypatch.setenv("FEEDBACK_QUEUE_URL", QUEUE_URL)


@pytest.fixture
def sqs(monkeypatch):
    """Puts a recording client behind the API-plane door.

    Args:
      monkeypatch: pytest's patcher.

    Returns:
      The recording client.

    Raises:
      None.
    """
    client = RecordingSqs()
    monkeypatch.setattr(identity_module, "api_client", lambda service: client)
    return client


def _body(**over):
    """A valid submission body.

    Args:
      **over: Fields to replace, or to drop with a None value.

    Returns:
      The body.

    Raises:
        None.
    """
    body = {"category": "bug", "message": "The upload bar sticks at 0%.", "route": "/files"}
    body.update(over)
    return {k: v for k, v in body.items() if v is not None}


def _post(body=None, username="alice"):
    """Drives the route through the router.

    Args:
      body: The body to send, defaulting to a valid one.
      username: The username the bearer asserts.

    Returns:
      The router's response.

    Raises:
      None.
    """
    return router.route(
        ROUTE.method,
        ROUTE.path,
        headers=bearer(username),
        request_id="req-1",
        body=_body() if body is None else body,
    )


def _sent(client):
    """The parsed body of the one message sent.

    Args:
      client: The recording client.

    Returns:
      The message body.

    Raises:
      None.
    """
    return json.loads(client.sends[0]["MessageBody"])


def test_the_route_is_declared_the_way_the_wire_needs_it() -> None:
    """Each field is a decision the declaration forces, and each has a consequence.

    ``idempotent`` false is what makes ``apiRetryPolicy`` yield no retry, so a submission cannot
    be silently doubled by the transport. ``plane`` api is what keeps the queue unwritable by the
    browser — on the user plane the portal role would need the send grant, and then a caller could
    file feedback under any name it chose.
    """
    assert (ROUTE.method, ROUTE.path) == ("POST", "/v1/feedback")
    assert ROUTE.idempotent is False
    assert ROUTE.plane == "api"
    assert not isinstance(ROUTE, contract.EnqueueRoute), (
        "the feedback route is served by its own handler; joining the enqueue family would carve "
        "exemptions into guards that exist to refuse them"
    )
    assert (ROUTE.method, ROUTE.path) not in router.PUBLIC_ROUTES


def test_the_request_type_cannot_name_a_person() -> None:
    """The body has no username, userId or email field — asserted on the DECLARED shape.

    Checked against the declaration rather than against a handler's behaviour: a handler that
    ignores a username field passes every test until somebody stops ignoring it, whereas a shape
    with no such field cannot grow one without this failing.
    """
    fields = {name for name, _node, _required in contract.walk(ROUTE.request).fields}

    assert fields == {"category", "message", "route"}
    assert not fields & {"username", "userId", "email", "user", "actor"}


def test_a_submission_is_attributed_to_the_TOKEN_and_never_to_the_body(sqs) -> None:
    """One send, the verified claim as the username, and the stamps the writer keys on."""
    response = _post(username="acarter")

    assert response["statusCode"] == 200
    assert len(sqs.sends) == 1
    sent = _sent(sqs)
    assert sent["username"] == "acarter"
    assert sent["category"] == "bug"
    assert sent["message"] == "The upload bar sticks at 0%."
    assert sent["route"] == "/files"
    assert sent["schemaVersion"] == 1
    assert sqs.sends[0]["QueueUrl"] == QUEUE_URL


def test_a_body_that_claims_a_username_is_refused_before_anything_is_sent(sqs) -> None:
    """An unknown key is refused by the existing validator; no leniency is added for this route."""
    response = _post(_body(username="mallory"))

    assert json.loads(response["body"])["error"]["code"] == "InvalidRequest"
    assert sqs.sends == [], "a refusal issued after a send is not a refusal"


def test_the_group_id_is_the_day_and_the_dedup_id_is_the_event_id(sqs) -> None:
    """The group id must agree with the key the writer derives, or the serialization is fiction.

    Both are read off the SAME send rather than recomputed here: a test that rebuilt the date
    would agree with itself while the route and the writer disagreed.
    """
    _post()

    sent_args = sqs.sends[0]
    sent = _sent(sqs)
    assert sent_args["MessageGroupId"] == sent["submittedAt"][:10]
    assert sent_args["MessageDeduplicationId"] == sent["eventId"]
    assert sent["submittedAt"].endswith("Z")


def test_two_submissions_get_different_dedup_ids(sqs) -> None:
    """The id is minted per submission, so a genuine second submission is not collapsed away."""
    _post()
    _post()

    first, second = (json.loads(s["MessageBody"])["eventId"] for s in sqs.sends)
    assert first != second


def test_the_message_carries_no_token_and_no_email_address(sqs) -> None:
    """A raw bearer used to ride beside these bodies; nothing may reintroduce one here."""
    _post()

    serialized = sqs.sends[0]["MessageBody"]
    assert "idToken" not in serialized
    assert "@" not in serialized, f"the message carries an address: {serialized}"
    assert set(_sent(sqs)) == {
        "schemaVersion",
        "eventId",
        "username",
        "category",
        "message",
        "route",
        "submittedAt",
    }


@pytest.mark.parametrize("length", [4000, 4001])
def test_the_message_boundary_is_at_four_thousand_characters(sqs, length) -> None:
    """The boundary asserted on both sides — one of them alone cannot see an off-by-one."""
    response = _post(_body(message="x" * length))

    if length == feedback.MAX_MESSAGE_CHARS:
        assert response["statusCode"] == 200
        assert len(sqs.sends) == 1
    else:
        assert json.loads(response["body"])["error"]["code"] == "InvalidRequest"
        assert sqs.sends == []


@pytest.mark.parametrize("message", ["", "   \n\t "])
def test_an_empty_or_whitespace_only_message_is_refused(sqs, message) -> None:
    """Trimmed before both checks: whitespace is empty to a reader and full to a length check."""
    response = _post(_body(message=message))

    assert json.loads(response["body"])["error"]["code"] == "InvalidRequest"
    assert sqs.sends == []


def test_the_message_is_stored_trimmed(sqs) -> None:
    """What the length check measured is what lands, or the cap describes a different string."""
    _post(_body(message="  hello  "))

    assert _sent(sqs)["message"] == "hello"


def test_a_route_over_the_cap_is_refused_and_a_missing_one_is_simply_absent(sqs) -> None:
    """Optional on the wire, bounded when present, and never invented when it is not."""
    refused = _post(_body(route="/" + "x" * feedback.MAX_ROUTE_CHARS))
    assert json.loads(refused["body"])["error"]["code"] == "InvalidRequest"
    assert sqs.sends == []

    assert _post(_body(route=None))["statusCode"] == 200
    assert "route" not in _sent(sqs)


@pytest.mark.parametrize("category", ["praise", "", "BUG"])
def test_a_category_outside_the_closed_set_is_refused_by_the_wire(sqs, category) -> None:
    """The literal is the guard, so a fifth value never reaches the handler at all."""
    response = _post(_body(category=category))

    assert json.loads(response["body"])["error"]["code"] == "InvalidRequest"
    assert sqs.sends == []


def test_an_unauthenticated_request_gets_the_same_refusal_every_route_gives() -> None:
    """Byte-identical to another authenticated route's refusal, and it names nothing."""
    mine = router.route(ROUTE.method, ROUTE.path, headers={}, request_id="req-1", body=_body())
    theirs = router.route("GET", "/v1/user-directory", headers={}, request_id="req-1")

    assert mine["statusCode"] == 401
    assert mine == theirs
    assert "feedback" not in json.dumps(mine)


@pytest.mark.parametrize(
    ("aws_code", "expected"),
    [
        ("ThrottlingException", "RateLimited"),
        ("ServiceUnavailable", "ApiUnavailable"),
        ("AccessDenied", "InternalError"),
    ],
)
def test_a_failed_send_tells_the_caller_the_submission_did_not_happen(
    monkeypatch, aws_code, expected
) -> None:
    """A queue failure is a fault, never a 200 — and an AccessDenied here is NOT a denial.

    On this plane the credential is the function's own execution role, so answering 403 would tell
    a user they may not do something when the deployment is misconfigured.
    """
    client = RecordingSqs(raises=_ServiceError(aws_code))
    monkeypatch.setattr(identity_module, "api_client", lambda service: client)

    response = _post()

    assert response["statusCode"] != 200
    assert json.loads(response["body"])["error"]["code"] == expected


def test_a_missing_queue_variable_is_a_fault_and_not_a_refusal_blaming_the_queue(
    monkeypatch, sqs
) -> None:
    """The failure a switchover is most likely to produce, and the one that used to lie.

    An unset repo variable renders as the empty string, so unset and empty are the same case. The
    client and the URL are resolved before the try for exactly this reason: inside it, a
    misconfiguration would be reshaped into "the queue is unavailable" — a 503 pointing the
    operator at the network, recorded as a successful span with no stack.
    """
    monkeypatch.setenv("FEEDBACK_QUEUE_URL", "")

    response = api_handler.handler(
        {
            "requestContext": {
                "http": {"method": ROUTE.method, "path": ROUTE.path},
                "requestId": "gateway-1",
            },
            "headers": bearer(),
            "body": json.dumps(_body()),
        },
        None,
    )

    assert response["statusCode"] >= 500
    assert sqs.sends == []
    assert "could not be reached" not in json.dumps(json.loads(response["body"]))
    assert "unavailable" not in json.loads(response["body"])["error"].get("detail", "")


def test_the_span_records_the_submission_without_its_text(sqs, captured_events) -> None:
    """A user's prose in a log store is the one thing this route must never emit."""
    secret = "my email is a@b.com and the password is hunter2"

    api_handler.handler(
        {
            "requestContext": {
                "http": {"method": ROUTE.method, "path": ROUTE.path},
                "requestId": "gateway-1",
            },
            "headers": bearer(),
            "body": json.dumps(_body(message=secret)),
        },
        None,
    )

    rendered = json.dumps([dict(e) for e in captured_events.events])
    assert secret not in rendered and "hunter2" not in rendered
    assert f'"message_chars": {len(secret)}' in rendered, (
        "the length is what makes the event say anything at all about the submission"
    )
    assert _sent(sqs)["message"] == secret
