"""Tests for the control-plane DLQ drain (SPEC-126).

Integration-ish for a Lambda: the REAL handler over the REAL cpcommon message registry and the
REAL actor reader, with only the SQS send captured. That matters here more than usual — the two
things most worth pinning are that the recipient comes from the IDENTITY BLOCK rather than from
anything else in the body, and that nothing else from the body reaches the message.

The recipient used to be a cryptographically verified claim, and this file used to mint real
RS256 tokens against a locally-generated keypair to prove it. It is trusted differently now:
the API is the only principal that may write these queues, so the block it stamped is as good
as a signature and a great deal cheaper. What replaces the bad-signature case is the shape
rule — a body whose actor is not a catalog-safe username notifies nobody.
"""

import hashlib
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"))

import dlq_drain
import pytest
from cpcommon import budget, clients, config
from token_shapes import JWT_SHAPED

JWT = JWT_SHAPED

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/1/dat-prod-notifications-requests.fifo"


class _FakeSqs:
    def __init__(self):
        self.sent = []
        self.queued = {}  # queue_url -> list[ReceiveMessage-shaped message]
        self.deleted = []  # (queue_url, receipt_handle)
        self.receive_calls = []  # queue_url, one per receive_message call
        self.receive_error_urls = set()  # urls whose receive_message raises
        self.delete_error = False  # when True, every delete_message raises

    def send_message(self, **kwargs):
        """Refuses a deduplication id SQS would refuse, so a lost notification is a missing send.

        The sender swallows the refusal, so a fake that recorded every send could not tell a
        delivered notification from a lost one. The rule is written out rather than borrowed from
        the sender, so a change to the sender's pattern cannot move the fake with it.
        """
        key = kwargs.get("MessageDeduplicationId")
        if key is not None and not (1 <= len(key) <= 128 and all("!" <= c <= "~" for c in key)):
            raise ValueError("InvalidParameterValue: MessageDeduplicationId")
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
    sqs = _FakeSqs()
    clients._sqs = sqs
    config.NOTIFICATIONS_QUEUE_URL = QUEUE_URL
    return sqs


def _identity(actor="alice"):
    """The block the API stamps, as every producer writes it.

    Args:
      actor: The verified username it names.

    Returns:
      A body fragment carrying the block.

    Raises:
      None.
    """
    return {"identity": {"actor": actor, "delegated_by": None, "assurance": "interactive"}}


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
            _record({"requestId": "r-1", **_identity("alice")}),
            _record({"requestId": "r-2", **_identity("bob")}),
        ]
    }
    dlq_drain.handler(event, None)

    assert [b["username"] for b in _bodies(sqs)] == ["alice", "bob"]
    assert [k["MessageGroupId"] for k in sqs.sent] == ["alice", "bob"]


# ── FR-002: the recipient comes from the block, never from anything else ─────


def test_an_actor_that_is_not_a_catalog_safe_username_notifies_nobody():
    """What replaced the bad-signature case, and it fails against a presence check.

    Here the block's actor is itself a raw token — the value a reader that fell back to the flat
    field would have produced on a pre-cutover message. Addressing a notification to a
    900-character string would not fail loudly — ``emit_notification`` would take it as a group
    id and write to a prefix nobody reads.
    """
    sqs = _install()

    dlq_drain.handler({"Records": [_record({"identity": {"actor": JWT, "delegated_by": None, "assurance": "interactive"}})]}, None)

    assert sqs.sent == []


def test_a_pre_cutover_message_with_no_identity_block_notifies_nobody():
    """The envelope a message enqueued before the cutover carried: a flat token, no block."""
    sqs = _install()

    dlq_drain.handler({"Records": [_record({"actor": JWT, "requestId": "r-1"})]}, None)

    assert sqs.sent == []


# ── The payload: the one body value the row carries ─────────────────────────


def test_the_row_carries_the_request_id_and_nothing_else_from_the_body():
    """A reader settles its in-flight record on this id; without it the record holds to expiry.

    The whole payload is compared rather than one key read out of it, and the location is looked
    for in the entire sent envelope: the id is the one body value the row may carry, and the
    message beside it may carry none.
    """
    sqs = _install()

    dlq_drain.handler(
        {"Records": [_record({"requestId": "r-1", "location": "alice/secret-plans/", **_identity()}, segment="file-ops")]},
        None,
    )

    assert _bodies(sqs)[0]["payload"] == {"requestId": "r-1"}
    assert sqs.sent[0]["MessageDeduplicationId"] == "dlq:r-1"
    assert "secret-plans" not in sqs.sent[0]["MessageBody"]


def test_a_128_character_request_id_still_notifies_under_a_key_the_queue_accepts():
    """The API admits an id this long, and the ``dlq:`` prefix carries it past the queue's limit.

    The fake refuses that key as SQS does, so without the sender's bound nothing is sent at all.
    The payload keeps the id whole, because it is what a reader matches its record on.
    """
    sqs = _install()
    request_id = "r" * 128

    dlq_drain.handler({"Records": [_record({"requestId": request_id, **_identity()}, segment="file-ops")]}, None)

    assert [b["username"] for b in _bodies(sqs)] == ["alice"]
    assert _bodies(sqs)[0]["payload"] == {"requestId": request_id}
    assert sqs.sent[0]["MessageDeduplicationId"] == hashlib.sha256(f"dlq:{request_id}".encode()).hexdigest()


@pytest.mark.parametrize("request_id", [None, "", 7], ids=["absent", "empty", "not-a-string"])
def test_a_body_without_a_usable_id_still_notifies_but_carries_no_payload(request_id):
    """The same predicate decides the dedup key, so the two cannot disagree about a body."""
    sqs = _install()
    body = _identity() if request_id is None else {"requestId": request_id, **_identity()}

    dlq_drain.handler({"Records": [_record(body, segment="file-ops")]}, None)

    assert [b["username"] for b in _bodies(sqs)] == ["alice"]
    assert "payload" not in _bodies(sqs)[0]
    assert "MessageDeduplicationId" not in sqs.sent[0]


# ── FR-004: the body survives consumption, the token does not ────────────────


def test_the_body_is_logged_with_a_legacy_token_redacted(caplog):
    """A body enqueued before the API stopped sending a token carries one.

    CloudWatch has a wider read audience than SQS, so it is blanked before the body is logged.

    The block rides beside it and must NOT be redacted: it is what the recipient was taken from,
    and blanking it would remove the only readable attribution while leaving the token in place.
    """
    sqs = _install()
    with caplog.at_level(logging.ERROR):
        dlq_drain.handler(
            {"Records": [_record({"idToken": JWT, "location": "alice/sales/", "requestId": "r-1", **_identity()})]},
            None,
        )

    logged = caplog.text
    # The forensic value: the body and how many times it was received.
    assert "alice/sales/" in logged
    assert "r-1" in logged
    assert "receives=3" in logged
    # The token is a bearer credential and CloudWatch has a wider read audience than SQS.
    assert JWT not in logged
    assert "<redacted>" in logged
    # …and the block it was beside is still readable, which is the half a naive fix breaks.
    # Asserted on the SERIALIZED FIELD, not on the username: this body also carries
    # "alice/sales/" as its location, so `"alice" in logged` holds whether or not the block
    # survived — and would keep holding with `identity` added to the redacted set, which is the
    # exact mistake the redaction's own docstring warns against.
    assert '"actor": "alice"' in logged
    assert logged.count("<redacted>") == 1
    # …and the notification still went out.
    assert len(sqs.sent) == 1


# ── FR-005: the drain cannot poison itself ───────────────────────────────────


def test_an_unrecognised_queue_still_notifies_with_a_generic_noun():
    # Should be unreachable (the coverage test fails first), but a wrong-but-honest message
    # beats the silence this spec exists to remove.
    sqs = _install()
    dlq_drain.handler(
        {"Records": [{"eventSourceARN": "arn:aws:sqs:us-east-1:1:dat-prod-mystery-requests-dlq.fifo", "body": json.dumps(_identity())}]},
        None,
    )

    assert _bodies(sqs)[0]["message"].startswith("Your request couldn't be started")


# ── Scheduled sweep: the pull driver that replaced the four event-source mappings ────────────
# The per-record behaviour above (recipient from token, nothing from the body, never redeliver)
# is unchanged; these pin the NEW part — that a scheduled invoke polls every DLQ, deletes what it
# drains, and cannot be stopped by one bad queue.


def test_the_sweep_drains_every_configured_dlq_and_notifies_from_the_block(monkeypatch):
    # One message on each wired DLQ. The envelopes used to disagree about where the token lived
    # — table-share and file-send said `actor`, the rest `idToken` — and this loop pinned that
    # the sweep resolved each domain's own field. They agree now: every producer writes one
    # `identity` block, which is why the per-source column is gone rather than set to one value.
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
        url = dlq_drain._queue_url(_arn(segment))
        sqs.queued[url] = [_msg({**_identity(f"user{i}"), "requestId": f"r-{i}"}, receipt=f"rh-{i}")]

    result = dlq_drain.handler({}, None)  # a scheduled event carries no Records

    assert result == {"drained": len(dlq_drain.SOURCES)}
    assert sorted(b["username"] for b in _bodies(sqs)) == [f"user{i}" for i in range(len(dlq_drain.SOURCES))]


class _Refusing:
    """A client no drain send may reach: it records what was asked of it and refuses it."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        self.calls.append(name)
        raise AssertionError(f"the drain sent on the bounded client ({name})")


def test_a_slow_send_is_waited_for_so_the_message_is_notified_before_it_is_deleted(monkeypatch):
    """The drain's send is its whole job, and the sweep deletes a message once it has notified: a
    send capped like every other would give up on a slow queue and delete the message unannounced.
    The send takes four times the cap and still arrives, on the default client."""
    monkeypatch.setattr(budget, "CALL_CAP_SECONDS", 0.05)
    sqs = _install()
    bounded = _Refusing()
    clients._sqs_bounded = bounded
    record = sqs.send_message

    def _slow_send(**kwargs):
        time.sleep(0.2)
        return record(**kwargs)

    sqs.send_message = _slow_send
    arn = _arn("data-quality")
    url = dlq_drain._queue_url(arn)
    monkeypatch.setenv("DLQ_ARNS", json.dumps([arn]))
    sqs.queued[url] = [_msg({"requestId": "r-1", **_identity("alice")}, receipt="rh-A")]

    dlq_drain.handler({}, None)

    assert [b["username"] for b in _bodies(sqs)] == ["alice"]
    assert sqs.deleted == [(url, "rh-A")]
    assert bounded.calls == []


def test_the_sweep_deletes_each_message_it_drains(monkeypatch):
    sqs = _install()
    arn = _arn("data-quality")
    url = dlq_drain._queue_url(arn)
    monkeypatch.setenv("DLQ_ARNS", json.dumps([arn]))
    sqs.queued[url] = [_msg(_identity("alice"), receipt="rh-A"), _msg(_identity("bob"), receipt="rh-B")]

    dlq_drain.handler({}, None)

    assert sqs.deleted == [(url, "rh-A"), (url, "rh-B")]


