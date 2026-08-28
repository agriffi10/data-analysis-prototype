"""Tests for the control-plane DLQ drain (SPEC-126).

Integration-ish for a Lambda: the REAL handler over the REAL cpcommon message registry and
the REAL token verification (against a locally-generated RSA keypair, JWKS client stubbed),
with only the SQS send captured. That matters here more than usual — the two things most
worth pinning are that the recipient comes from the TOKEN rather than the body, and that
nothing from the body reaches the message. A test that stubbed `verified_username` would
verify neither.
"""

import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"))

import dlq_drain
import jwt
from cpcommon import clients, config
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_PEM = _OTHER_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)

ISSUER = f"https://cognito-idp.{config.REGION}.amazonaws.com/{config.USER_POOL_ID}"
QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/1/dat-prod-notifications-requests.fifo"


class _FakeSigningKey:
    key = _KEY.public_key()


class _FakeJwks:
    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey()


class _FakeSqs:
    def __init__(self):
        self.sent = []
        self.queued = {}  # queue_url -> list[ReceiveMessage-shaped message]
        self.deleted = []  # (queue_url, receipt_handle)
        self.receive_calls = []  # queue_url, one per receive_message call
        self.receive_error_urls = set()  # urls whose receive_message raises
        self.delete_error = False  # when True, every delete_message raises

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "m-1"}

    def receive_message(self, **kwargs):
        url = kwargs["QueueUrl"]
        self.receive_calls.append(url)
        if url in self.receive_error_urls:
            raise RuntimeError("receive failed")
        pending = self.queued.get(url, [])
        batch = pending[: kwargs.get("MaxNumberOfMessages", 10)]
        self.queued[url] = pending[len(batch) :]  # a received message is no longer visible
        return {"Messages": batch} if batch else {}

    def delete_message(self, **kwargs):
        if self.delete_error:
            raise RuntimeError("delete failed")
        self.deleted.append((kwargs["QueueUrl"], kwargs.get("ReceiptHandle")))
        return {}


def _install():
    # Stub the ACCESSOR, not the cache: `_jwks` is a per-URL dict now
    # (SPEC-151 FR-009), and what these tests actually want to fake is the client.
    clients.jwks = lambda url: _FakeJwks()
    sqs = _FakeSqs()
    clients._sqs = sqs
    config.NOTIFICATIONS_QUEUE_URL = QUEUE_URL
    return sqs


def _token(username="alice", *, exp_offset=3600, key=_PRIVATE_PEM):
    return jwt.encode(
        {
            "cognito:username": username,
            "token_use": "id",
            "aud": config.APP_CLIENT_ID,
            "iss": ISSUER,
            "exp": int(time.time()) + exp_offset,
        },
        key,
        algorithm="RS256",
    )


def _arn(segment="data-quality"):
    return f"arn:aws:sqs:us-east-1:1:dat-prod-{segment}-requests-dlq.fifo"


def _record(body, *, segment="data-quality", receives="3"):
    raw = body if isinstance(body, str) else json.dumps(body)
    return {"eventSourceARN": _arn(segment), "body": raw, "attributes": {"ApproximateReceiveCount": receives}}


def _msg(body, *, receipt="rh-1", receives="3"):
    """A ReceiveMessage-shaped message, as the scheduled sweep sees it off a DLQ."""
    raw = body if isinstance(body, str) else json.dumps(body)
    return {"Body": raw, "ReceiptHandle": receipt, "Attributes": {"ApproximateReceiveCount": receives}}


def _bodies(sqs):
    return [json.loads(k["MessageBody"]) for k in sqs.sent]


# ── FR-001: every DLQ drains, one message = one notification ─────────────────


def test_each_source_is_recognised_from_its_queue_arn():
    for segment, source in dlq_drain.SOURCES.items():
        assert dlq_drain._source_for(_arn(segment)) is source


def test_a_batch_of_n_messages_produces_n_notifications():
    sqs = _install()
    event = {
        "Records": [
            _record({"requestId": "r-1", "idToken": _token("alice")}),
            _record({"requestId": "r-2", "idToken": _token("bob")}),
        ]
    }
    dlq_drain.handler(event, None)

    assert [b["username"] for b in _bodies(sqs)] == ["alice", "bob"]
    assert [k["MessageGroupId"] for k in sqs.sent] == ["alice", "bob"]


# ── FR-002: the recipient is verified, never asserted ────────────────────────


def test_a_bad_signature_notifies_nobody():
    sqs = _install()
    dlq_drain.handler({"Records": [_record({"idToken": _token("mallory", key=_OTHER_PEM)})]}, None)

    assert sqs.sent == []


# ── FR-004: the body survives consumption, the token does not ────────────────


def test_the_body_is_logged_with_the_token_redacted(caplog):
    sqs = _install()
    token = _token()
    with caplog.at_level(logging.ERROR):
        dlq_drain.handler({"Records": [_record({"idToken": token, "location": "alice/sales/", "requestId": "r-1"})]}, None)

    logged = caplog.text
    # The forensic value: the body and how many times it was received.
    assert "alice/sales/" in logged
    assert "r-1" in logged
    assert "receives=3" in logged
    # The token is a bearer credential and CloudWatch has a wider read audience than SQS.
    assert token not in logged
    assert "<redacted>" in logged
    # …and the notification still went out.
    assert len(sqs.sent) == 1


# ── FR-005: the drain cannot poison itself ───────────────────────────────────


def test_an_unrecognised_queue_still_notifies_with_a_generic_noun():
    # Should be unreachable (the coverage test fails first), but a wrong-but-honest message
    # beats the silence this spec exists to remove.
    sqs = _install()
    dlq_drain.handler(
        {"Records": [{"eventSourceARN": "arn:aws:sqs:us-east-1:1:dat-prod-mystery-requests-dlq.fifo", "body": json.dumps({"idToken": _token()})}]},
        None,
    )

    assert _bodies(sqs)[0]["message"].startswith("Your request couldn't be started")


# ── Scheduled sweep: the pull driver that replaced the four event-source mappings ────────────
# The per-record behaviour above (recipient from token, nothing from the body, never redeliver)
# is unchanged; these pin the NEW part — that a scheduled invoke polls every DLQ, deletes what it
# drains, and cannot be stopped by one bad queue.


def test_the_sweep_drains_every_configured_dlq_and_notifies_from_the_token(monkeypatch):
    # One message on each wired DLQ, each carrying the token in ITS domain's field (table-share
    # and file-send use `actor`, the rest `idToken`) — so this also pins that the sweep preserves
    # the per-domain token-field resolution the event-source path had.
    #
    # The expectations below are DERIVED from SOURCES rather than written out, because the
    # fixture is too: a literal 4 was really asserting "nobody has added a plane", which is
    # test_every_request_dlq_the_repo_provisions_is_either_wired_or_named_as_excluded's job and
    # is checked against the IaC rather than against this dict. Here the count would only ever
    # restate the loop above it.
    sqs = _install()
    arns = [_arn(segment) for segment in dlq_drain.SOURCES]
    monkeypatch.setenv("DLQ_ARNS", json.dumps(arns))
    for i, segment in enumerate(dlq_drain.SOURCES):
        field = dlq_drain.SOURCES[segment].token_field
        url = dlq_drain._queue_url(_arn(segment))
        sqs.queued[url] = [_msg({field: _token(f"user{i}"), "requestId": f"r-{i}"}, receipt=f"rh-{i}")]

    result = dlq_drain.handler({}, None)  # a scheduled event carries no Records

    assert result == {"drained": len(dlq_drain.SOURCES)}
    assert sorted(b["username"] for b in _bodies(sqs)) == [f"user{i}" for i in range(len(dlq_drain.SOURCES))]


def test_the_sweep_deletes_each_message_it_drains(monkeypatch):
    sqs = _install()
    arn = _arn("data-quality")
    url = dlq_drain._queue_url(arn)
    monkeypatch.setenv("DLQ_ARNS", json.dumps([arn]))
    sqs.queued[url] = [_msg({"idToken": _token("alice")}, receipt="rh-A"), _msg({"idToken": _token("bob")}, receipt="rh-B")]

    dlq_drain.handler({}, None)

    assert sqs.deleted == [(url, "rh-A"), (url, "rh-B")]


