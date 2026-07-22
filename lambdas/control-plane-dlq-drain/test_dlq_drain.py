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
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"))

import jwt  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

import dlq_drain  # noqa: E402
from cpcommon import clients, config  # noqa: E402

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
    clients._jwks = _FakeJwks()
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


def test_every_request_dlq_the_repo_provisions_is_either_wired_or_named_as_excluded():
    """A fifth control plane cannot be added without wiring it or failing here.

    Reads the IaC rather than a hand-maintained list, because a hand-maintained list is
    exactly what goes stale — and a DLQ that silently isn't drained is indistinguishable, to
    the user, from the bug this spec fixes.
    """
    modules_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "infra", "modules"
    )
    provisioned = set()
    for module in sorted(os.listdir(modules_dir)):
        locals_tf = os.path.join(modules_dir, module, "locals.tf")
        if not os.path.isfile(locals_tf):
            continue
        with open(locals_tf) as handle:
            for match in re.finditer(r'dlq_name\s*=\s*"[^"]*\$\{var\.environment\}-([a-z-]+)-requests-dlq', handle.read()):
                provisioned.add(match.group(1))

    assert provisioned, "found no request DLQs in infra/modules — the scan itself is broken"
    assert provisioned == set(dlq_drain.SOURCES) | dlq_drain.UNDRAINED_QUEUES


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


def test_one_unrecoverable_message_does_not_suppress_the_rest_of_the_batch():
    sqs = _install()
    event = {
        "Records": [
            _record("{not json at all"),
            _record({"idToken": _token("bob")}),
        ]
    }
    dlq_drain.handler(event, None)

    assert [b["username"] for b in _bodies(sqs)] == ["bob"]


def test_table_share_reads_its_token_from_actor_not_idToken():
    # The one domain that names the field differently. A hard-coded "idToken" would notify
    # nobody here, silently.
    sqs = _install()
    dlq_drain.handler({"Records": [_record({"actor": _token("carol")}, segment="table-share")]}, None)

    assert [b["username"] for b in _bodies(sqs)] == ["carol"]
    assert "share" in _bodies(sqs)[0]["message"]


# ── FR-002: the recipient is verified, never asserted ────────────────────────


def test_the_token_wins_over_a_body_asserted_username():
    # The DLQ is reachable by anything that can enqueue. A body claiming to be someone else
    # must never route a notification to that someone else.
    sqs = _install()
    dlq_drain.handler(
        {"Records": [_record({"username": "victim", "actor": "victim", "idToken": _token("mallory")})]}, None
    )

    assert [b["username"] for b in _bodies(sqs)] == ["mallory"]


def test_an_expired_but_validly_signed_token_still_notifies():
    # Dead-lettered messages are old by construction; enforcing exp would drop exactly the
    # late failures this drain exists to surface.
    sqs = _install()
    dlq_drain.handler({"Records": [_record({"idToken": _token("alice", exp_offset=-86400)})]}, None)

    assert [b["username"] for b in _bodies(sqs)] == ["alice"]


def test_a_bad_signature_notifies_nobody():
    sqs = _install()
    dlq_drain.handler({"Records": [_record({"idToken": _token("mallory", key=_OTHER_PEM)})]}, None)

    assert sqs.sent == []


def test_a_body_with_no_token_notifies_nobody():
    sqs = _install()
    dlq_drain.handler({"Records": [_record({"requestId": "r-1", "location": "alice/sales/"})]}, None)

    assert sqs.sent == []


# ── FR-003: the message says it never ran, and says nothing else ─────────────


def test_the_message_says_it_could_not_be_started_and_that_nothing_changed():
    sqs = _install()
    dlq_drain.handler({"Records": [_record({"idToken": _token()})]}, None)

    message = _bodies(sqs)[0]["message"]
    assert message.startswith("Your data quality check couldn't be started")
    assert "nothing was created or changed" in message
    assert "try again" in message.lower()
    assert "Administrator" in message
    # "failed" reads as "it ran and went wrong" — the opposite of what happened.
    assert "failed" not in message.lower()


def test_no_value_from_the_untrusted_body_reaches_the_message():
    # Nothing here has authorized anything, so echoing a body-supplied string into a
    # victim's inbox would make the notification pipeline a text-injection channel.
    sqs = _install()
    hostile = "SECURITY ALERT: visit http://evil.example.com to re-enter your password"
    dlq_drain.handler(
        {
            "Records": [
                _record({"idToken": _token(), "location": hostile, "tableName": hostile, "space": hostile})
            ]
        },
        None,
    )

    message = _bodies(sqs)[0]["message"]
    assert hostile not in message
    assert "evil.example.com" not in message


def test_the_message_carries_no_link():
    # There is nothing to link to: the request never ran.
    sqs = _install()
    dlq_drain.handler({"Records": [_record({"idToken": _token()})]}, None)

    assert "link" not in _bodies(sqs)[0]


def test_the_reason_code_is_registered_so_it_is_a_valid_terminal_reason():
    from cpcommon import messages

    assert messages.is_known_reason(dlq_drain.COULD_NOT_START)


def test_dedup_uses_the_request_id_when_there_is_one_and_falls_back_when_there_is_not():
    sqs = _install()
    dlq_drain.handler(
        {
            "Records": [
                _record({"requestId": "req-9", "idToken": _token()}),
                _record({"idToken": _token()}),
                _record({"requestId": "", "idToken": _token()}),
            ]
        },
        None,
    )

    assert sqs.sent[0]["MessageDeduplicationId"] == "dlq:req-9"
    # No usable id → content dedup, rather than inventing one (which would defeat it).
    assert "MessageDeduplicationId" not in sqs.sent[1]
    assert "MessageDeduplicationId" not in sqs.sent[2]


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


def test_a_wrongly_named_token_field_is_still_redacted():
    # A malformed body may carry the other domain's field name; a redactor that only knew
    # this source's field would log a live credential.
    body = dlq_drain._redacted({"actor": "secret-token", "idToken": "other-secret"}, "idToken")
    assert body == {"actor": "<redacted>", "idToken": "<redacted>"}


def test_an_unparseable_body_is_logged_rather_than_lost(caplog):
    with caplog.at_level(logging.ERROR):
        dlq_drain.handler({"Records": [_record("<<<not json>>>")]}, None)

    assert "<<<not json>>>" in caplog.text


# ── FR-005: the drain cannot poison itself ───────────────────────────────────


def test_a_batch_of_completely_malformed_records_returns_normally():
    # A throw means redelivery, and a message that always throws is redelivered until
    # retention expires — burning invocations on a failure nobody is watching, which is the
    # invisibility this whole spec exists to end.
    _install()
    event = {"Records": [{}, {"body": None}, "not-even-a-dict", {"body": "[]"}, {"body": "null"}]}
    assert dlq_drain.handler(event, None) == {"drained": 5}


def test_the_handler_survives_a_per_message_path_that_throws_anyway():
    """The outer catch is the belt to _notify_one's braces, so it needs its own test.

    Every path inside `_notify_one` is already total, which means a batch test can pass with
    the handler's own `except` deleted — a false green on the guard that actually decides
    whether a poison message loops until retention expires. Forcing a throw is the only way
    to see this one fail when it is broken.
    """
    _install()
    original = dlq_drain._notify_one
    calls = []

    def _boom(record):
        calls.append(record)
        raise RuntimeError("something nobody anticipated")

    dlq_drain._notify_one = _boom
    try:
        assert dlq_drain.handler({"Records": [_record({}), _record({})]}, None) == {"drained": 2}
        # …and it kept going rather than stopping at the first throw.
        assert len(calls) == 2
    finally:
        dlq_drain._notify_one = original


def test_an_empty_or_absent_event_returns_normally():
    _install()
    assert dlq_drain.handler({}, None) == {"drained": 0}
    assert dlq_drain.handler(None, None) == {"drained": 0}


def test_a_failing_notification_send_never_fails_the_drain():
    _install()

    class _Boom:
        def send_message(self, **kwargs):
            raise RuntimeError("sqs is down")

    clients._sqs = _Boom()
    assert dlq_drain.handler({"Records": [_record({"idToken": _token()})]}, None) == {"drained": 1}


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


def test_queue_url_is_derived_from_the_arn():
    assert (
        dlq_drain._queue_url("arn:aws:sqs:us-east-1:1:dat-prod-data-quality-requests-dlq.fifo")
        == "https://sqs.us-east-1.amazonaws.com/1/dat-prod-data-quality-requests-dlq.fifo"
    )


def test_dlq_arns_reads_the_env_and_tolerates_a_malformed_value(monkeypatch):
    monkeypatch.setenv("DLQ_ARNS", json.dumps(["arn:a", "arn:b"]))
    assert dlq_drain._dlq_arns() == ["arn:a", "arn:b"]
    # A malformed env is a deploy error, not a reason to crash the sweep — drain nothing.
    monkeypatch.setenv("DLQ_ARNS", "{not json")
    assert dlq_drain._dlq_arns() == []
    monkeypatch.delenv("DLQ_ARNS", raising=False)
    assert dlq_drain._dlq_arns() == []


def test_the_sweep_drains_every_configured_dlq_and_notifies_from_the_token(monkeypatch):
    # One message on each of the four wired DLQs, each carrying the token in ITS domain's field
    # (table-share uses `actor`, the rest `idToken`) — so this also pins that the sweep preserves
    # the per-domain token-field resolution the event-source path had.
    sqs = _install()
    arns = [_arn(segment) for segment in dlq_drain.SOURCES]
    monkeypatch.setenv("DLQ_ARNS", json.dumps(arns))
    for i, segment in enumerate(dlq_drain.SOURCES):
        field = dlq_drain.SOURCES[segment].token_field
        url = dlq_drain._queue_url(_arn(segment))
        sqs.queued[url] = [_msg({field: _token(f"user{i}"), "requestId": f"r-{i}"}, receipt=f"rh-{i}")]

    result = dlq_drain.handler({}, None)  # a scheduled event carries no Records

    assert result == {"drained": 4}
    assert sorted(b["username"] for b in _bodies(sqs)) == ["user0", "user1", "user2", "user3"]


def test_the_sweep_deletes_each_message_it_drains(monkeypatch):
    sqs = _install()
    arn = _arn("data-quality")
    url = dlq_drain._queue_url(arn)
    monkeypatch.setenv("DLQ_ARNS", json.dumps([arn]))
    sqs.queued[url] = [_msg({"idToken": _token("alice")}, receipt="rh-A"), _msg({"idToken": _token("bob")}, receipt="rh-B")]

    dlq_drain.handler({}, None)

    assert sqs.deleted == [(url, "rh-A"), (url, "rh-B")]


def test_the_sweep_deletes_a_message_it_cannot_notify_about(monkeypatch):
    # No token → no verifiable recipient → no notification. But the message must STILL be deleted:
    # a redelivered terminal message is exactly the invisibility this drain exists to end (FR-005).
    sqs = _install()
    arn = _arn("data-quality")
    url = dlq_drain._queue_url(arn)
    monkeypatch.setenv("DLQ_ARNS", json.dumps([arn]))
    sqs.queued[url] = [_msg({"requestId": "r-1"}, receipt="rh-X")]

    result = dlq_drain.handler({}, None)

    assert sqs.sent == []
    assert sqs.deleted == [(url, "rh-X")]
    assert result == {"drained": 1}


def test_an_empty_queue_is_polled_once_and_left(monkeypatch):
    sqs = _install()
    arn = _arn("table-builder")
    monkeypatch.setenv("DLQ_ARNS", json.dumps([arn]))

    result = dlq_drain.handler({}, None)

    # One receive returns empty and the loop stops — no runaway polling, nothing deleted.
    assert sqs.receive_calls == [dlq_drain._queue_url(arn)]
    assert sqs.deleted == []
    assert result == {"drained": 0}


def test_a_receive_failure_on_one_queue_does_not_stop_the_rest(monkeypatch):
    sqs = _install()
    good, bad = _arn("data-quality"), _arn("table-builder")
    monkeypatch.setenv("DLQ_ARNS", json.dumps([bad, good]))
    sqs.receive_error_urls.add(dlq_drain._queue_url(bad))
    sqs.queued[dlq_drain._queue_url(good)] = [_msg({"idToken": _token("alice")}, receipt="rh-1")]

    result = dlq_drain.handler({}, None)

    assert [b["username"] for b in _bodies(sqs)] == ["alice"]
    assert result == {"drained": 1}


def test_a_delete_failure_does_not_crash_the_sweep_or_drop_the_notification(monkeypatch):
    sqs = _install()
    arn = _arn("data-quality")
    monkeypatch.setenv("DLQ_ARNS", json.dumps([arn]))
    sqs.delete_error = True
    sqs.queued[dlq_drain._queue_url(arn)] = [_msg({"idToken": _token("alice")}, receipt="rh-1")]

    assert dlq_drain.handler({}, None) == {"drained": 1}
    assert [b["username"] for b in _bodies(sqs)] == ["alice"]


def test_a_scheduled_event_shape_takes_the_sweep_path(monkeypatch):
    sqs = _install()
    arn = _arn("shared-space")
    monkeypatch.setenv("DLQ_ARNS", json.dumps([arn]))
    sqs.queued[dlq_drain._queue_url(arn)] = [_msg({"idToken": _token("dave")}, receipt="rh-1")]

    scheduled = {"source": "aws.events", "detail-type": "Scheduled Event", "detail": {}}
    assert dlq_drain.handler(scheduled, None) == {"drained": 1}
    assert [b["username"] for b in _bodies(sqs)] == ["dave"]
