"""The ten enqueue routes, driven through the router.

The load-bearing assertions here are about what reaches the QUEUE, not about the 200. An enqueue
that answers 200 and lands in the wrong FIFO group succeeds from outside and silently stops being
ordered the way the plane's lock was sized for, so every test below reads the recorded send.

The refusal assertions are counted against a client that records everything: a 400 issued after a
successful send looks identical to one issued before it from the caller's side.
"""

import json
import pathlib

import handler as api_handler
import pytest
import router
from apicommon import contract
from apicommon import enqueue as enqueue_module
from conftest import bearer

_QUEUE_ENV = {
    queue.env_var: f"https://sqs.test/1/{queue.id}.fifo" for queue in contract.QUEUES
}

_VECTORS = json.loads((pathlib.Path(__file__).parent / "fifo_vectors.json").read_text())


def _caller_body(vector):
    """The half of a captured message a caller actually sends.

    Derived from the browser's own recorded body rather than hand-written, because a hand-written
    fixture is what let the first draft of the request types disagree with the wire and agree with
    itself: the fixture and the type were written from each other, and every test passed.

    Args:
      vector: One recorded vector.

    The one transformation applied is stringifying a partition key's projection bounds, which is
    the flattening this contract chose: the browser sends an integer key's bounds as numbers today
    and sends them as strings once its service is rewired. The plane accepts either and the DDL
    builder interpolates rather than calculates, so the table property is unchanged — asserted
    below rather than assumed.

    Returns:
      The captured body minus whatever the sender stamps, and minus the legacy token field.
      The vectors are RECORDED, so they still carry the field the API used to forward; the route
      no longer declares its name, so the two legacy names are stripped by literal here rather
      than read off the contract.

    Raises:
      None.
    """
    route = next(
        r for r in contract.ENQUEUE_ROUTES if r.id == vector["route"].split("@")[0]
    )
    body = json.loads(vector["sent"]["MessageBody"])
    for key in {*_LEGACY_TOKEN_FIELDS, *route.stamped}:
        body.pop(key, None)
    for key in body.get("partitionKeys", []):
        if "range" in key:
            key["range"] = [str(bound) for bound in key["range"]]
    return body


#: The two field names the API used to forward a raw token in, per plane. The route no longer
#: declares one, and the recorded vectors predate that, so they are stripped by literal.
_LEGACY_TOKEN_FIELDS = frozenset({"idToken", "actor"})


_BODIES = {
    vector["route"]: _caller_body(vector)
    for vector in reversed(_VECTORS["vectors"])
}
_BODIES.update(
    {route.id: _BODIES[route.id] for route in contract.ENQUEUE_ROUTES if route.id in _BODIES}
)

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
    """The eight queue URLs and the two buckets the derivations need.

    Returns:
      None.

    Raises:
      None.
    """
    for name, value in _QUEUE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("USER_SPACE_BUCKET", "dat-prod-user-space")
    monkeypatch.setenv("SHARED_SPACE_BUCKET", "dat-prod-shared-space")


@pytest.fixture
def sqs(monkeypatch):
    """Puts a recording client behind the API-plane door.

    Returns:
      The recording client.

    Raises:
      None.
    """
    client = RecordingSqs()
    monkeypatch.setattr(enqueue_module.identity, "api_client", lambda service: client)
    return client


def _event(route, body):
    """One API Gateway payload-format-2.0 request, for the tests that need a real span.

    ``router.route`` opens no span — the handler does — so an observability assertion driven
    through the router would read an empty sink and pass for the wrong reason.

    Args:
      route: The route to call.
      body: The request body.

    Returns:
      The event.

    Raises:
      None.
    """
    return {
        "requestContext": {
            "http": {"method": route.method, "path": route.path},
            "requestId": "gateway-1",
        },
        "headers": bearer(),
        "body": json.dumps(body),
    }


def _post(route, body=None):
    """Drives one enqueue route through the router.

    Args:
      route: The route to call.
      body: The body to send, defaulting to the route's valid one.

    Returns:
      The router's response.

    Raises:
      None.
    """
    return router.route(
        route.method,
        route.path,
        headers=bearer(),
        request_id="req-1",
        body=_BODIES[route.id] if body is None else body,
    )


@pytest.mark.parametrize("route", contract.ENQUEUE_ROUTES, ids=lambda r: r.id)
def test_every_route_sends_one_message_carrying_the_identity_block_and_no_token(
    route, sqs
):
    """One send, the block stamped whole, and no credential anywhere in the body.

    The second half used to be SPEC-200's tripwire — it asserted the token was STILL being sent,
    and was written to fail on exactly the edit that stops it. This is that edit, so the
    assertion is inverted rather than dropped.
    """
    response = _post(route)

    assert response["statusCode"] == 200, response["body"]
    assert len(sqs.sends) == 1
    sent = sqs.sends[0]
    body = json.loads(sent["MessageBody"])
    assert body["identity"] == {
        "actor": "alice",
        "delegated_by": None,
        "assurance": "interactive",
    }
    assert set(body["identity"]) == {"actor", "delegated_by", "assurance"}
    assert "idToken" not in body and "actor" not in body, (
        f"{route.id} still writes a top-level token field: {sorted(body)}"
    )
    assert sent["MessageGroupId"] and sent["MessageDeduplicationId"]
    assert (
        sent["QueueUrl"]
        == _QUEUE_ENV[next(q.env_var for q in contract.QUEUES if q.id == route.queue)]
    )


@pytest.mark.parametrize("route", contract.ENQUEUE_ROUTES, ids=lambda r: r.id)
def test_every_route_echoes_the_callers_request_id_and_mints_none_of_its_own(
    route, sqs
):
    """The API mints no request id. The one id it does generate never leaves the send.

    Null on the TWO planes that have no request id — notifications, whose actions are idempotent,
    and table-share, which is why its dedup digest is that plane's entire double-submit guard.
    """
    response = _post(route)
    answered = json.loads(response["body"])
    sent_dedup = sqs.sends[0]["MessageDeduplicationId"]

    if route.id in {"notifications.enqueue", "tableShare.enqueue"}:
        assert answered["requestId"] is None
        assert sent_dedup not in response["body"]
    else:
        assert answered["requestId"] == _BODIES[route.id]["requestId"]


@pytest.mark.parametrize("forged", ["actor", "identity", "idToken"])
@pytest.mark.parametrize("route", contract.ENQUEUE_ROUTES, ids=lambda r: r.id)
def test_a_body_claiming_an_identity_is_refused_before_anything_is_sent(route, forged, sqs):
    """The three keys a forgery would use. None is a caller input, so each is a 400.

    Over EVERY enqueue route rather than one of them: the refusal is the validator's, so it
    holds by construction — but a route declaring one of these names would break it for that
    route alone, and a single-route case would still be green.
    """
    response = _post(route, {**_BODIES[route.id], forged: "someone-else"})

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == "InvalidRequest"
    assert sqs.sends == []


def test_shared_space_carries_ONE_actor_and_it_is_the_blocks(sqs):
    """The advisory top-level actor is gone, and the verified one is the only one left.

    Shared-space used to carry the caller's username twice: once in the identity block and once
    flat, where nothing read it. Two places a username appears on the wire is two that can
    disagree, and the flat one had no reader to notice. Asserted as an ABSENCE rather than by
    deleting the test, because the way this regresses is somebody re-adding the convenience.
    """
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == "sharedSpace.enqueue")

    _post(route)

    body = json.loads(sqs.sends[0]["MessageBody"])
    assert "actor" not in body
    assert body["identity"]["actor"] == "alice"
    assert body["schemaVersion"] == 1


def test_an_oversized_selection_is_refused_before_the_send(monkeypatch, sqs):
    """413 is measured on the body the API will send, after everything is stamped onto it."""
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == "fileSend.enqueue")
    huge = {
        **_BODIES[route.id],
        "source": {
            "space": {"kind": "personal", "name": "alice"},
            "items": [
                {"key": "alice/" + "x" * 1000, "kind": "file"} for _ in range(400)
            ],
        },
    }

    response = _post(route, huge)

    assert response["statusCode"] == 413
    assert json.loads(response["body"])["error"]["code"] == "PayloadTooLarge"
    assert sqs.sends == []


@pytest.mark.parametrize(
    ("code", "status", "expected"),
    [
        ("AccessDenied", 500, "InternalError"),
        ("ThrottlingException", 429, "RateLimited"),
        ("ServiceUnavailable", 503, "ApiUnavailable"),
    ],
)
def test_a_failed_send_answers_the_caller_without_calling_it_their_fault(
    code, status, expected, monkeypatch
):
    """An AccessDenied on this plane is THIS function's role, so a 403 would be a lie."""
    client = RecordingSqs(raises=_ServiceError(code))
    monkeypatch.setattr(enqueue_module.identity, "api_client", lambda service: client)
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == "fileSend.enqueue")

    response = _post(route)

    assert response["statusCode"] == status
    assert json.loads(response["body"])["error"]["code"] == expected


def test_the_size_cap_is_derived_from_what_the_queue_takes_and_what_is_stamped_on():
    """A cap written as a literal hides a wrong model, and this one has two moving parts.

    It had three. The bearer allowance went with the token, which returned 8 KB of headroom to
    callers rather than relaxing a limit — and its absence is asserted, because an allowance
    reappearing is the shape of the exposure coming back.
    """
    assert enqueue_module.SQS_MAX_MESSAGE_BYTES == 262_144
    assert enqueue_module.MAX_MESSAGE_BYTES == (
        enqueue_module.SQS_MAX_MESSAGE_BYTES - enqueue_module.MAX_IDENTITY_BLOCK_BYTES
    )
    assert not hasattr(enqueue_module, "MAX_BEARER_BYTES"), (
        "a bearer allowance means a bearer is being sent again"
    )
    largest_block = json.dumps(
        {
            "identity": {
                "actor": "a" * 63,
                "delegated_by": "a" * 63,
                "assurance": "interactive",
            }
        },
        separators=(",", ":"),
    )
    assert len(largest_block.encode("utf-8")) <= enqueue_module.MAX_IDENTITY_BLOCK_BYTES


def test_every_enqueue_route_declares_the_two_fields_that_cannot_be_defaulted():
    """A retried enqueue is a duplicate or a no-op, and the grant is on this function's role."""
    assert [r.id for r in contract.ENQUEUE_ROUTES if r.idempotent] == []
    assert {r.plane for r in contract.ENQUEUE_ROUTES} == {"api"}
    assert {r.queue for r in contract.ENQUEUE_ROUTES} == {q.id for q in contract.QUEUES}


def test_only_four_routes_stamp_a_field_and_the_values_match_what_they_declare():
    """The stamped term is not an escape hatch: mode is the branch between archive and restore."""
    declared = {r.id: r.stamped for r in contract.ENQUEUE_ROUTES if r.stamped}

    assert declared == {
        "sharedSpace.enqueue": frozenset({"schemaVersion"}),
        "tableBuild.refresh": frozenset({"mode"}),
        "archive.archive": frozenset({"mode"}),
        "archive.restore": frozenset({"mode"}),
    }
    for route in contract.ENQUEUE_ROUTES:
        values = enqueue_module._stamped_values(route)
        assert set(values) == set(route.stamped), route.id


def test_the_record_names_the_send_and_carries_no_part_of_the_body(sqs, captured_events):
    """A selection of 20,000 keys is a log record nobody can read, and object keys are user data.

    The obvious helper — stamp the validated request — is one edit away from stamping the token
    with it, so the body is excluded whole rather than filtered field by field.
    """
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == "fileSend.enqueue")

    api_handler.handler(_event(route, _BODIES[route.id]), None)

    emitted = json.dumps(captured_events.events)
    assert '"route_id"' in emitted and '"message_group_id"' in emitted
    assert '"body_bytes"' in emitted and '"queue"' in emitted
    assert '"body_request_id"' in emitted
    for absent in ("alice/a.csv", '"items"', '"recipients"', '"source"'):
        assert absent not in emitted, absent


def test_a_browser_supplied_request_id_is_stamped_but_never_becomes_the_correlation_key(
    sqs, captured_events
):
    """The trap: the correlation extractor falls back to parsing the body, and every body has one.

    Distinguishing "stamped correctly" from "leaked into correlation" needs both halves asserted,
    because a test that only looked for the literal's absence would fail on the correct behaviour.
    """
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == "fileSend.enqueue")
    body = {**_BODIES[route.id], "requestId": "cafe0000-0000-4000-8000-00000000cafe"}

    api_handler.handler(_event(route, body), None)

    records = captured_events.events
    fields = [r.get("fields", {}) for r in records]
    assert any(f.get("body_request_id") == body["requestId"] for f in fields)
    assert {f.get("request_id") for f in fields if "request_id" in f} == {"gateway-1"}
    assert body["requestId"] not in {f.get("request_id") for f in fields}


def test_the_assurance_vocabulary_is_a_closed_set_of_exactly_one():
    """Widening it must be a deliberate edit a reviewer sees, not a value that slipped in.

    The value names the assurance KIND rather than the mechanism that produced it, so a second
    value is a second contract with every plane and not a rename.
    """
    from typing import get_args

    from apicommon import identity_block

    assert get_args(identity_block.Assurance) == ("interactive",)
    assert identity_block.ASSURANCE_INTERACTIVE == "interactive"


def test_the_content_based_dedup_flags_are_read_out_of_the_terraform_not_transcribed():
    """Three queues hash the body when no explicit id is given, and the parse has one hard case.

    In shared-spaces, notifications and table-builder BOTH the request queue and its DLQ are
    content-based, so a parse that took the first match per file would be right by luck. Data
    quality declares its DLQ first and its request queue second with the opposite value, which is
    the one case that separates a correct parse from a wrong one — and getting it wrong reddens
    nothing, because an explicit id is set either way.
    """
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tf_blocks import blocks

    modules = pathlib.Path(__file__).resolve().parents[2] / "infra" / "modules"
    module_for = {
        "shared-space": "shared-spaces",
        "notifications": "notifications",
        "table-builder": "table-builder",
        "table-share": "table-share",
        "data-quality": "data-quality",
        "file-send": "file-send",
        "archive": "archive",
        "file-ops": "file-ops",
        "results-conversion": "results-conversion",
    }
    deployed = {}
    for queue in contract.QUEUES:
        source = (modules / module_for[queue.id] / "sqs.tf").read_text()
        body = blocks(source, "aws_sqs_queue")["requests"]
        deployed[queue.id] = "content_based_deduplication = true" in body.replace("  ", " ")

    assert deployed == {q.id: q.content_based_deduplication for q in contract.QUEUES}
    assert {q.id for q in contract.QUEUES if q.content_based_deduplication} == {
        "shared-space",
        "notifications",
        "table-builder",
    }


def test_stringifying_a_projection_bound_does_not_move_the_table_property():
    """The claim the flattened `range` rests on, asserted rather than argued.

    The contract declares projection bounds as strings because its type vocabulary cannot express
    one field that is numbers for an integer key and strings for a date key. That is only safe if
    the two render identically — the DDL builder interpolates the pair into one property and does
    no arithmetic, so it does. If that ever stops being true, an integer partition silently
    projects over the wrong range and the table reads as empty.
    """
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "control-plane-common"))
    from cpcommon import ddl

    numeric = ddl.projection_properties({"name": "year", "type": "integer", "range": [2020, 2026]})
    stringly = ddl.projection_properties(
        {"name": "year", "type": "integer", "range": ["2020", "2026"]}
    )

    assert numeric == stringly


def test_a_missing_queue_variable_is_a_fault_and_not_a_refusal_blaming_the_queue(monkeypatch, sqs):
    """The failure the switchover is most likely to produce, and the one that used to lie.

    Eight queue variables land at once. When the send helper resolved its client and its URL inside
    the try, an unset one was reshaped into 503 "the queue could not be reached" — a sentence that
    points the operator at the network, recorded as a successful span with no stack. An unset and
    an empty variable are the same case here, because an unset repo variable renders as empty.
    """
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == "fileSend.enqueue")
    monkeypatch.setenv(
        next(q.env_var for q in contract.QUEUES if q.id == route.queue), ""
    )

    response = api_handler.handler(_event(route, _BODIES[route.id]), None)

    body = json.loads(response["body"])

    assert response["statusCode"] >= 500
    assert sqs.sends == []
    assert "could not be reached" not in json.dumps(body), (
        "a misconfigured queue must not be reported as an unreachable one"
    )
