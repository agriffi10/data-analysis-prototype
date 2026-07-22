"""Drain every control plane's request DLQ into the notification the user already reads (SPEC-126).

Each control plane dead-letters a request it cannot process — a malformed body the Pipe
rejects, a message that exhausts its three receives. When that happens **no verb runs and no
execution starts**, so nothing in the arc's own failure machinery fires: no
``@notifies_on_failure``, no ``NotifyFailure`` state. The request simply disappears and the
person who made it is left watching for a result that will never come.

This one function sits on all four request DLQs (data-quality, table-builder, table-share,
shared-spaces) and turns each dead-lettered message into one sentence in the actor's inbox:
your request couldn't be started, nothing was created or changed, try again.

Three things shape the whole handler:

- **The body is untrusted.** It is, by definition, a message the pipeline refused. The
  recipient comes from the VERIFIED token inside it, never from a ``username`` the body
  asserts, and nothing from the body is interpolated into the message (FR-002/FR-003).
- **Consuming a DLQ destroys the evidence.** An SQS event source deletes the message on
  success, so the body is logged — token redacted — before anything else happens (FR-004).
- **It cannot be allowed to fail.** A throw means redelivery, and a message that always
  throws is redelivered until retention expires, burning invocations on a failure nobody is
  watching — which is the exact invisibility this spec exists to end. Every per-message path
  is total (FR-005).
"""

import json
import logging
import os

from cpcommon import auth, clients, messages
from cpcommon.notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)

#: The user-facing reason this drain emits. Registered through the ``cpcommon.messages``
#: domain hook like every other reason code, so it is a valid ``TerminalError`` reason and
#: its wording lives in a registry rather than inline at the emit site (SPEC-107 FR-005).
COULD_NOT_START = "could_not_start"

#: NOT "failed" — "failed" reads as "it ran and went wrong", and the two facts the user needs
#: in order to decide whether to re-submit are that it never started and that nothing changed.
_MESSAGES = messages.register(
    {
        COULD_NOT_START: (
            "your {noun} couldn't be started, so nothing was created or changed. "
            "Please try again, and contact the Administrator if it keeps happening."
        )
    }
)


class Source:
    """One wired DLQ: how to name its domain to the user, and where its token lives.

    ``token_field`` is PER-DOMAIN and not a constant, which looks like an inconsistency and
    is really a fact about the four envelopes: data-quality, table-builder and shared-spaces
    put the actor's ID token in ``idToken``, while table-share puts it in ``actor``
    (``table_share_validate_authorize.py``). A single hard-coded field name would silently
    notify nobody for whichever domain it did not match — and silently is precisely the
    failure mode this spec exists to remove.
    """

    def __init__(self, source: str, noun: str, token_field: str):
        self.source = source
        self.noun = noun
        self.token_field = token_field


#: Keyed by the DOMAIN SEGMENT of the DLQ name (`{project}-{env}-{segment}-requests-dlq.fifo`),
#: because that is the only thing about a queue that is stable across project/environment.
SOURCES: dict[str, Source] = {
    "data-quality": Source("data-quality", "data quality check", "idToken"),
    "table-builder": Source("table-builder", "table", "idToken"),
    "table-share": Source("table-share", "share", "actor"),
    "shared-space": Source("shared-space", "shared space", "idToken"),
}

#: DLQs this drain deliberately does NOT attach to. See FR-006 and the comment in
#: ``infra/modules/notifications/sqs.tf``: the drain's only delivery channel is the
#: notifications queue, so draining the NOTIFICATIONS DLQ would ask the queue that just
#: failed to deliver to deliver the news about itself. Named here rather than merely omitted,
#: so the coverage test can tell "excluded on purpose" from "someone forgot".
UNDRAINED_QUEUES = frozenset({"notifications"})

#: The generic noun for a queue whose descriptor is missing. It should be unreachable — the
#: coverage test fails first — but a wrong-but-honest message beats no message at all.
_FALLBACK_NOUN = "request"


def _source_for(event_source_arn: str) -> Source | None:
    """Resolve the descriptor for a record's ``eventSourceARN``, or None."""
    queue_name = (event_source_arn or "").rsplit(":", 1)[-1]
    for segment, source in SOURCES.items():
        if f"-{segment}-requests-dlq" in queue_name:
            return source
    return None


def _redacted(body: dict, token_field: str) -> dict:
    """The body with its token replaced by a marker.

    The token is a BEARER CREDENTIAL, and CloudWatch Logs has a far wider read audience
    than the SQS queue the body came from — an expired token is still a signed assertion
    about a real user. Every known token field is redacted, not just this source's, because
    a malformed body may carry the wrong one.
    """
    redacted = dict(body)
    for field in {token_field, *(s.token_field for s in SOURCES.values())}:
        if field in redacted:
            redacted[field] = "<redacted>"
    return redacted


def _notify_one(record: dict) -> None:
    """Turn one dead-lettered record into (at most) one notification. Never raises."""
    source = _source_for(record.get("eventSourceARN", ""))
    noun = source.noun if source else _FALLBACK_NOUN
    token_field = source.token_field if source else "idToken"
    if source is None:
        logger.error("no descriptor for eventSourceARN %r; using the generic noun", record.get("eventSourceARN"))

    raw = record.get("body") or ""
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("body is not a JSON object")
    except Exception:  # noqa: BLE001 - an unparseable body is expected input here
        # THE ONE THING WORTH KEEPING IS THE BODY ITSELF. It cannot be redacted (there is no
        # structure to redact), and it cannot be notified about (there is no token to
        # identify a recipient), so log it and stop.
        logger.error("dead-lettered %s message is not a JSON object; body=%r", noun, raw)
        return

    # FR-004: log BEFORE emitting. The event source deletes this message on success, trading
    # the DLQ's 14-day copy for the log group's retention — the deliberate cost of the user
    # finding out at all.
    logger.error(
        "dead-lettered %s request (receives=%s): %s",
        noun,
        (record.get("attributes") or {}).get("ApproximateReceiveCount"),
        json.dumps(_redacted(body, token_field), default=str),
    )

    try:
        username = auth.verified_username_ignoring_expiry(
            body.get(token_field) or "", missing_token_detail=f"missing {token_field}"
        )
    except Exception:  # noqa: BLE001 - no verifiable actor = no trustworthy recipient
        # Guessing a recipient from the body would be worse than silence: it would route a
        # notification wherever an attacker asked. Mirrors tbcommon/notify's pre-identity
        # posture and SPEC-114 FR-004.
        logger.exception("could not derive a verified recipient for a dead-lettered %s request", noun)
        return

    # NO VALUE FROM THE BODY REACHES THE MESSAGE — not a path, not a table name, not a space
    # name. Every other producer interpolates values a verb already AUTHORIZED; nothing here
    # has authorized anything, so echoing an attacker-supplied string back into a victim's
    # inbox would turn the notification pipeline into a text-injection channel. The domain
    # noun is ours; the token is the only thing taken from the body, and only to name a
    # recipient.
    clause = _MESSAGES.body(COULD_NOT_START, noun=noun)
    message = clause[0].upper() + clause[1:]

    # Dedup on the request's OWN id when it has one, so a message that somehow dead-letters
    # twice collapses to one notification. A body without a usable id falls back to the
    # queue's content-based dedup rather than inventing an id, which would defeat it.
    request_id = body.get("requestId")
    dedup_id = f"dlq:{request_id}" if isinstance(request_id, str) and request_id else None

    # No `link`: the request never ran, so there is nothing to link to.
    emit_notification(username, message, dedup_id=dedup_id)


# ── Scheduled sweep (SPEC-126 follow-up: SQS event-source mappings → EventBridge schedule) ────
# The drain used to hang off four SQS event-source mappings — four managed poll loops on queues
# that are, by design, almost always empty, and that idle polling was the bulk of the account's
# SQS request volume. It now runs on ONE EventBridge schedule and sweeps all four queues itself:
# receive a batch, notify, delete, repeat until the queue is empty. Everything a notification
# depends on (_notify_one and what it calls) is UNCHANGED — only the driver moved from push to pull.

#: Receive rounds a single sweep makes per queue before leaving the rest for the next tick. These
#: queues are almost always empty (one empty receive and we move on); the cap only bounds a
#: pathological burst so one sweep cannot run to the timeout — 10 rounds × 10 = 100 messages per
#: queue per sweep, and the next tick mops up any remainder.
_MAX_ROUNDS_PER_QUEUE = 10

#: Long-poll each receive rather than short-poll (WaitTimeSeconds=0): a short poll samples a
#: subset of SQS hosts and can return empty while a message waits, deferring it a whole interval.
#: A couple of seconds of wait on an empty queue is nothing on a 10-minute cadence.
_RECEIVE_WAIT_SECONDS = 2


def _guarded_notify(record) -> None:
    """Call _notify_one so it can never raise — the belt to _notify_one's own braces (FR-005)."""
    try:
        _notify_one(record if isinstance(record, dict) else {})
    except Exception:  # noqa: BLE001 - a per-message throw must never stop the batch/sweep
        logger.exception("dlq-drain record handling failed")


def _dlq_arns() -> list[str]:
    """The DLQ ARNs to sweep, from DLQ_ARNS (a JSON list mirroring the drain's IAM read scope)."""
    try:
        arns = json.loads(os.environ.get("DLQ_ARNS", "[]"))
    except Exception:  # noqa: BLE001 - a malformed env is a deploy error; sweep nothing, don't crash
        logger.exception("DLQ_ARNS is not valid JSON; sweeping nothing")
        return []
    return [a for a in arns if isinstance(a, str)] if isinstance(arns, list) else []


def _queue_url(queue_arn: str) -> str:
    """The queue URL for a queue ARN: arn:aws:sqs:REGION:ACCOUNT:NAME → the standard URL."""
    _, _, _, region, account, name = queue_arn.split(":", 5)
    return f"https://sqs.{region}.amazonaws.com/{account}/{name}"


def _record_from_message(queue_arn: str, message: dict) -> dict:
    """Shape a raw ReceiveMessage result like the SQS-event record _notify_one expects.

    ReceiveMessage does not carry eventSourceARN (the event source used to inject it), so the
    sweep supplies the queue it is polling. ApproximateReceiveCount is requested explicitly and
    used only for the forensic log line.
    """
    return {
        "eventSourceARN": queue_arn,
        "body": message.get("Body"),
        "attributes": {"ApproximateReceiveCount": (message.get("Attributes") or {}).get("ApproximateReceiveCount")},
    }


def _sweep_one_queue(queue_arn: str) -> int:
    """Drain one DLQ — notify then delete each message, until empty or the round cap. Never raises."""
    sqs = clients.sqs()
    url = _queue_url(queue_arn)
    drained = 0
    for _ in range(_MAX_ROUNDS_PER_QUEUE):
        try:
            response = sqs.receive_message(
                QueueUrl=url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=_RECEIVE_WAIT_SECONDS,
                AttributeNames=["ApproximateReceiveCount"],
            )
        except Exception:  # noqa: BLE001 - a receive failure is transient; the next sweep retries
            logger.exception("could not receive from %s; leaving it for the next sweep", queue_arn)
            break
        messages = response.get("Messages") or []
        if not messages:
            break
        for message in messages:
            _guarded_notify(_record_from_message(queue_arn, message))
            # Delete regardless of the notify outcome. The event-source model deleted the whole
            # batch on return — even a message it could not act on — and a redelivery only re-runs
            # a decision already made about a terminal message (FR-005). A delete failure is rare
            # and transient; the message resurfaces on a later sweep (and may notify once more then,
            # outside the notifications queue's 5-minute dedup window) rather than being lost.
            try:
                sqs.delete_message(QueueUrl=url, ReceiptHandle=message.get("ReceiptHandle"))
            except Exception:  # noqa: BLE001 - see above; a resurfaced message is deduped, not doubled
                logger.exception("could not delete a drained message; it will resurface next sweep")
            drained += 1
    return drained


def handler(event, context):  # noqa: ARG001 - context unused; Lambda supplies it
    """Notify the actor behind every dead-lettered request.

    On its EventBridge schedule the event carries no ``Records``, so the handler SWEEPS all four
    request DLQs itself. Handed an SQS event instead — a captured record replayed with
    ``aws lambda invoke`` — it processes those records directly; the per-record path is shared.

    Total by construction either way: one unparseable, unverifiable or un-notifiable message never
    raises and never suppresses the rest. A message is deleted whether or not it could be notified
    about, because a redelivery would only re-run a path that already decided it had nothing it
    could do (FR-005).
    """
    records = (event or {}).get("Records")
    if records is not None:
        for record in records:
            _guarded_notify(record)
        return {"drained": len(records)}

    return {"drained": sum(_sweep_one_queue(arn) for arn in _dlq_arns())}
