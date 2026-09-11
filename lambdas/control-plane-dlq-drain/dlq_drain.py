"""Drains every control plane's request DLQ into the notification the user already reads.

Each control plane dead-letters a request it cannot process — a malformed body the Pipe
rejects, or a message that exhausts its receives. When that happens no verb runs and no
execution starts, so nothing in the arc's own failure machinery fires. The request simply
disappears and the person who made it is left watching for a result that will never come.

This one function sits on every request DLQ in ``SOURCES`` and turns each dead-lettered message
into one sentence in the actor's inbox: your request couldn't be started, nothing was created or
changed, try again.

Three things shape the whole handler. The body is untrusted — by definition it is a message the
pipeline refused, so the recipient comes from the API's identity block inside it, never from a
username the body asserts, and nothing from the body is interpolated into the message.
Consuming a DLQ destroys the evidence, so the body is logged, any legacy token redacted, before anything
else happens. And it cannot be allowed to fail: a throw means redelivery, and a message that
always throws is redelivered until retention expires, burning invocations on a failure nobody
is watching — the exact invisibility this exists to end. Every per-message path is total.

The drain used to hang off four SQS event-source mappings — four managed poll loops on queues
that are, by design, almost always empty, and that idle polling was the bulk of the account's
SQS request volume. It now runs on one schedule and polls each of its queues itself. Everything a
notification depends on is unchanged; only the driver moved from push to pull.

The service name is not a control-plane name: this function spans every plane and is
nobody's verb, so it gets its own queryable set. That name is load-bearing in a quiet way — it
becomes an S3 key, and the sweep routes anything failing its pattern to the unrouted partition
without erroring, so a name that missed the pattern would file every one of these events
somewhere nobody looks. Pinned by a test that checks it against the sweep's own pattern rather
than against a human's reading of it.

Attributes:
  _LEGACY_TOKEN_FIELDS: The two top-level fields a PRE-CUTOVER envelope kept its raw ID token in.
    The API stops writing either once the planes read the identity block instead, so on a current
    message this set matches nothing — it is kept because a 14-day queue plus three failed
    receives means a stale body can still arrive, and that body is precisely what this drain
    exists to surface into a log group with a far wider read audience than the queue.
  _MAX_BODY_CHARS: Cap on the serialised forensic body. It is unbounded, untrusted input, and
    every event is appended into a day object the sweep rewrites in full every ten minutes — one
    pathological body would be paid for again on every sweep for the rest of that day.
  COULD_NOT_START: The user-facing reason this drain emits, registered through the shared
    messages hook like every other reason code so its wording lives in a registry rather than
    inline at the emit site. Not "failed": that reads as "it ran and went wrong", and the two
    facts the user needs in order to decide whether to re-submit are that it never started and
    that nothing changed.
  SOURCES: Keyed by the domain segment of the DLQ name, because that is the only thing about a
    queue that is stable across project and environment.
  UNDRAINED_QUEUES: DLQs this drain deliberately does not attach to. Two, for two different
    reasons, and the second is not a special case of the first. **notifications**: the drain's
    only delivery channel IS that queue, so draining its DLQ would ask the queue that just failed
    to deliver to deliver the news about itself. **feedback**: the recipient of every notification
    this drain sends comes from the verified ``identity`` block inside the message body, and a
    feedback message carries none by design — the API verified the caller and the browser never
    touches that queue. Draining it would mean notifying whoever an untrusted body field named,
    which is the exact inversion this drain's recipient rule exists to prevent. Named here rather
    than merely omitted, so the coverage tests can tell "excluded on purpose" from "someone
    forgot".
  _FALLBACK_NOUN: The generic noun for a queue whose descriptor is missing. It should be
    unreachable — the coverage test fails first — but a wrong-but-honest message beats no
    message at all.
  _MAX_ROUNDS_PER_QUEUE: Receive rounds per queue per sweep. These queues are almost always
    empty, so the cap only bounds a pathological burst; the next tick mops up any remainder.
  _RECEIVE_WAIT_SECONDS: Long-poll each receive rather than short-poll. A short poll samples a
    subset of SQS hosts and can return empty while a message waits, deferring it a whole
    interval, and a couple of seconds on an empty queue is nothing on this cadence.
  _MESSAGES: This drain's own resolver, registered through the shared hook so its one code is a
    valid terminal reason and its wording lives in a registry rather than inline at the emit
    site.
"""

import json
import logging
import os

from cpcommon import actor as cpactor
from cpcommon import clients, messages, observability
from cpcommon.notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="dlq-drain")

_LEGACY_TOKEN_FIELDS = frozenset({"idToken", "actor"})

_MAX_BODY_CHARS = 4096

COULD_NOT_START = "could_not_start"

_MESSAGES = messages.register(
    {
        COULD_NOT_START: (
            "your {noun} couldn't be started, so nothing was created or changed. "
            "Please try again, and contact the Administrator if it keeps happening."
        )
    }
)


class Source:
    """One wired DLQ, and the domain word its notification uses.

    There used to be a third column saying where this domain's envelope kept the actor's ID
    token, because the envelopes disagreed — three said ``idToken`` and the rest said ``actor``.
    The recipient now comes from the ``identity`` block, which every producer writes identically,
    so the disagreement is gone and the COLUMN goes with it rather than being set to one value
    on every row: a per-source field whose sources all agree is a fork whose operands always
    match, which this repo has shipped before and which passes forever.

    Attributes:
      source: The domain segment of the queue name.
      noun: The domain word the notification uses.
    """

    def __init__(self, source: str, noun: str):
        """Records one queue's descriptor.

        Args:
          source: The domain segment of the queue name.
          noun: The domain word the notification uses.

        Returns:
          None.

        Raises:
          None.
        """
        self.source = source
        self.noun = noun


SOURCES: dict[str, Source] = {
    "data-quality": Source("data-quality", "data quality check"),
    "table-builder": Source("table-builder", "table"),
    "table-share": Source("table-share", "share"),
    "shared-space": Source("shared-space", "shared space"),
    "file-send": Source("file-send", "file send"),
    "archive": Source("archive", "archive"),
    "file-ops": Source("file-ops", "file operation"),
    "results-conversion": Source("results-conversion", "results conversion"),
}

UNDRAINED_QUEUES = frozenset({"notifications", "feedback"})

_FALLBACK_NOUN = "request"


def _source_for(event_source_arn: str) -> Source | None:
    """Resolves the descriptor for a record's source queue.

    Args:
      event_source_arn: The queue ARN the record came from.

    Returns:
      The matching descriptor, or None when the queue is not one ``SOURCES`` names.

    Raises:
      None.
    """
    queue_name = (event_source_arn or "").rsplit(":", 1)[-1]
    for segment, source in SOURCES.items():
        if f"-{segment}-requests-dlq" in queue_name:
            return source
    return None


def _redacted(body: dict) -> dict:
    """Returns a copy of the body with any LEGACY top-level token field replaced by a marker.

    The API no longer sends a token, so on a current envelope this changes nothing. It is not
    therefore dead: a message enqueued before the trust flip still carries one, and a 14-day
    queue plus three failed receives means a stale body can arrive here long after the producer
    stopped writing them. That message is exactly the one this drain exists to surface, and
    CloudWatch Logs has a far wider read audience than the SQS queue it came from — an expired
    token is still a signed assertion about a real user.

    **It must not be pointed at ``identity`` instead.** The replacement is top-level only, so
    that would blank the block this function's caller has just taken its recipient from, while
    removing nothing sensitive: the block holds a username, a null and a literal, and every one
    of them is meant to be readable in the record.

    Args:
      body: The parsed message body.

    Returns:
      A redacted copy; the argument is not mutated.

    Raises:
      None.
    """
    redacted = dict(body)
    for field in _LEGACY_TOKEN_FIELDS:
        if field in redacted:
            redacted[field] = "<redacted>"
    return redacted


def _request_id(body: dict) -> str | None:
    """Reads the request id a dead-lettered body names, or nothing when it names no usable one.

    One predicate for the three things the id becomes here — an event field, a deduplication key
    and the payload a reader settles on — so they cannot disagree about which bodies have one.
    Usable means a non-empty string, the same test ``observability.request_id_of`` applies for
    the failure payloads other planes send; ``_notify_one`` says why no stricter shape is owed.

    Args:
      body: The parsed message body.

    Returns:
      The id, or None.

    Raises:
      None.
    """
    request_id = body.get("requestId")
    return request_id if isinstance(request_id, str) and request_id else None


def _request_id_field(body: dict) -> dict:
    """Returns the request id as an event field, or nothing when the body has no usable one.

    A field, never baggage, and that is the whole point. Every other instrumented function
    handles one request per invocation, so the request id is stamped into baggage once and every
    event inherits it. This function handles hundreds of messages per invocation, each its own
    request, and the baggage reset runs once at the top of the wrapper. Set per message, the id
    would persist onto the next message's events, and a body without one would silently inherit
    its predecessor's — a fabricated correlation key that merges two unrelated requests into one
    query result while nothing about the output looks wrong.

    Omitted entirely rather than emitted empty, for the same reason: an absent field is
    unjoinable, which is honest; an empty one is a value.

    Args:
      body: The parsed message body.

    Returns:
      A single-key dict, or an empty one.

    Raises:
      None.
    """
    request_id = _request_id(body)
    return {"request_id": request_id} if request_id else {}


def _forensic(body: dict) -> dict:
    """Builds the fields carrying the dead-lettered body as a permanent forensic record.

    Consuming a DLQ message destroys the evidence: each queue's retention was knowingly traded
    for a log group's, as the price of the user finding out at all. The structured store is
    retained forever, so writing the body here upgrades that record from a copy that expires to
    one that does not.

    Three properties, each closing a specific hazard. Redacted through the same helper the
    CloudWatch line uses. Capped, because the body is unbounded untrusted input and the sweep
    rewrites the day's object in full every ten minutes. And one serialised field, never
    re-parsed into fields — promoting attacker-controlled keys into the event's own namespace
    would let a body shadow the request id, the verb or the service.

    Args:
      body: The parsed message body.

    Returns:
      The body field plus its truncation flag and original length. The flag is stated rather
      than implied: a silently truncated forensic record is worse than a short one, because it
      reads as complete.

    Raises:
      None.
    """
    serialized = json.dumps(_redacted(body), default=str)
    truncated = len(serialized) > _MAX_BODY_CHARS
    return {
        "body": serialized[:_MAX_BODY_CHARS],
        "body_truncated": truncated,
        "body_length": len(serialized),
    }


def _notify_one(record: dict) -> None:
    """Turns one dead-lettered record into at most one notification.

    No value from the body reaches the message — not a path, not a table name, not a space name.
    Every other producer interpolates values a verb already authorized; nothing here has
    authorized anything, so echoing an attacker-supplied string back into a victim's inbox would
    turn the notification pipeline into a text-injection channel. The domain noun is ours, and
    the identity block names the recipient. No link is set, because the request never ran and
    there is nothing to link to.

    **The row's payload carries one body value, the request id, and nothing else**, because a
    reader settles its in-flight record by matching it: without the id a dead-lettered request
    holds its record, and whatever that record gates, until it expires or is dismissed. It does not
    reopen the channel the rule above closes, for three reasons. The recipient is the actor the
    API stamped, and a delegated one is refused, so the id lands only in the inbox of the caller
    who chose it. Only the API writes the block a recipient is read from, and it also made the
    id the message's deduplication key, so SQS has already held it to 128 printable ASCII
    characters — which is the payload's whole size bound, far under the writer's ceiling. And no
    reader renders it as text: the browser keeps it only when it cannot change a URL, and uses
    it to match a record and, beside a conflict list this row never carries, to build a link.

    The body is logged before the emit, because the event source deletes the message on success.
    An unparseable body cannot be redacted and cannot be notified about, so it is recorded as a
    bounded repr — which escapes newlines and control characters, so an attacker-supplied body
    cannot forge a second record — and the message is dropped. A body the actor reader refuses —
    no identity block, no usable actor in it, a delegated actor or an unaccepted assurance — is
    likewise only recorded: guessing a recipient from the body would be worse than silence,
    because it would route a notification wherever an attacker asked.

    Deduplication uses the request's own id when it has one, so a message that somehow
    dead-letters twice collapses to one notification. A body without a usable id falls back to
    the queue's content-based dedup rather than inventing an id, which would defeat it. The
    prefix carries an id near the API's 128-character limit past what the queue accepts as a
    key, and the sender sends such a key as its digest; the payload keeps the id as it is.

    The recipient is recorded: the username is already the S3 prefix, the principal tag and the
    Glue database name, and which user was affected is the first question anyone asks about a
    dead-lettered request.

    Args:
      record: The SQS record, real or shaped from a sweep's receive.

    Returns:
      None.

    Raises:
      None.
    """
    source = _source_for(record.get("eventSourceARN", ""))
    noun = source.noun if source else _FALLBACK_NOUN
    if source is None:
        logger.error("no descriptor for eventSourceARN %r; using the generic noun", record.get("eventSourceARN"))
        observability.error(
            "no descriptor for the queue",
            reason="no-descriptor",
            queue_arn=record.get("eventSourceARN"),
        )

    raw = record.get("body") or ""
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("body is not a JSON object")  # noqa: TRY004
    except Exception:  # noqa: BLE001
        logger.error("dead-lettered %s message is not a JSON object; body=%r", noun, raw)
        observability.error(
            "dead-lettered message could not be parsed",
            reason="unparseable-body",
            domain=noun,
            body=repr(raw)[:_MAX_BODY_CHARS],
            body_length=len(raw),
        )
        return

    logger.error(
        "dead-lettered %s request (receives=%s): %s",
        noun,
        (record.get("attributes") or {}).get("ApproximateReceiveCount"),
        json.dumps(_redacted(body), default=str),
    )

    try:
        username = cpactor.trusted_actor(body).username
    except Exception:
        logger.exception("could not derive a recipient for a dead-lettered %s request", noun)
        observability.error(
            "no verified recipient for a dead-lettered request",
            reason="no-verified-recipient",
            domain=noun,
            **_request_id_field(body),
            **_forensic(body),
        )
        return

    clause = _MESSAGES.body(COULD_NOT_START, noun=noun)
    message = clause[0].upper() + clause[1:]

    request_id = _request_id(body)
    dedup_id = f"dlq:{request_id}" if request_id else None
    payload = {"requestId": request_id} if request_id else None

    emit_notification(username, message, dedup_id=dedup_id, payload=payload)

    observability.info(
        "notified a dead-lettered request",
        domain=noun,
        recipient=username,
        receives=(record.get("attributes") or {}).get("ApproximateReceiveCount"),
        dedup=dedup_id is not None,
        **_request_id_field(body),
        **_forensic(body),
    )


_MAX_ROUNDS_PER_QUEUE = 10

_RECEIVE_WAIT_SECONDS = 2


def _guarded_notify(record) -> None:
    """Calls the per-record notifier so it can never raise — the belt to its own braces.

    Args:
      record: The SQS record, or anything else, which is coerced to an empty dict.

    Returns:
      None.

    Raises:
      None. A per-message throw must never stop the batch or the sweep.
    """
    try:
        _notify_one(record if isinstance(record, dict) else {})
    except Exception:
        logger.exception("dlq-drain record handling failed")


def _dlq_arns() -> list[str]:
    """Reads the DLQ ARNs to sweep from the environment.

    The variable is a JSON list mirroring the drain's IAM read scope. A malformed value is a
    deploy error: it sweeps nothing rather than crashing, and records that explicitly, because
    an empty sweep is otherwise indistinguishable from a healthy idle one in every field it
    reports — and a deploy error that disables the drain outright must not look like a quiet
    Tuesday.

    Args:
      None.

    Returns:
      The queue ARNs, or an empty list.

    Raises:
      None.
    """
    try:
        arns = json.loads(os.environ.get("DLQ_ARNS", "[]"))
    except Exception:
        logger.exception("DLQ_ARNS is not valid JSON; sweeping nothing")
        observability.error("DLQ_ARNS is not valid JSON; sweeping nothing", reason="malformed-dlq-arns")
        return []
    return [a for a in arns if isinstance(a, str)] if isinstance(arns, list) else []


def _queue_url(queue_arn: str) -> str:
    """Derives the standard queue URL from a queue ARN.

    Args:
      queue_arn: The queue ARN.

    Returns:
      The queue URL.

    Raises:
      ValueError: If the ARN does not have the expected number of segments.
    """
    _, _, _, region, account, name = queue_arn.split(":", 5)
    return f"https://sqs.{region}.amazonaws.com/{account}/{name}"


def _record_from_message(queue_arn: str, message: dict) -> dict:
    """Shapes a raw receive result like the SQS-event record the notifier expects.

    A receive does not carry the source ARN — the event source used to inject it — so the sweep
    supplies the queue it is polling. The receive count is requested explicitly and used only
    for the forensic log line.

    Args:
      queue_arn: The queue being swept.
      message: One received message.

    Returns:
      A record dict in the event-source shape.

    Raises:
      None.
    """
    return {
        "eventSourceARN": queue_arn,
        "body": message.get("Body"),
        "attributes": {"ApproximateReceiveCount": (message.get("Attributes") or {}).get("ApproximateReceiveCount")},
    }


@observability.step("sweep-queue")
def _sweep_one_queue(queue_arn: str) -> int:
    """Drains one DLQ, notifying then deleting each message until empty or the round cap.

    A message is deleted regardless of the notify outcome. The event-source model deleted the
    whole batch on return — even a message it could not act on — and a redelivery only re-runs a
    decision already made about a terminal message. A delete failure is rare and transient: the
    message resurfaces on a later sweep, and may notify once more then, outside the
    notifications queue's dedup window, rather than being lost.

    Args:
      queue_arn: The queue to sweep.

    Returns:
      The number of messages drained.

    Raises:
      None. A receive failure ends this queue's sweep and the next tick retries.
    """
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
        except Exception:
            logger.exception("could not receive from %s; leaving it for the next sweep", queue_arn)
            observability.error(
                "could not receive from a queue", reason="receive-failed", queue_arn=queue_arn
            )
            break
        messages = response.get("Messages") or []
        if not messages:
            break
        for message in messages:
            _guarded_notify(_record_from_message(queue_arn, message))
            try:
                sqs.delete_message(QueueUrl=url, ReceiptHandle=message.get("ReceiptHandle"))
            except Exception:
                logger.exception("could not delete a drained message; it will resurface next sweep")
                observability.warning(
                    "could not delete a drained message; it will resurface",
                    reason="delete-failed",
                    queue_arn=queue_arn,
                    lost=False,
                )
            drained += 1
    return drained


@observability.traced("drain")
def handler(event, context):
    """Notifies the actor behind every dead-lettered request.

    ``@traced`` is the only decorator here: there is no failure notifier, because this function
    is the failure handler and has no upstream to notify through.

    On its schedule the event carries no records, so the handler sweeps every DLQ in
    ``DLQ_ARNS`` itself. Handed an SQS event instead — a captured record replayed by hand — it
    processes those records directly; the per-record path is shared.

    Args:
      event: Either an SQS event or the schedule's empty payload.
      context: The Lambda context, unused.

    Returns:
      A dict reporting how many messages were drained.

    Raises:
      None. Total by construction either way: one unparseable, unverifiable or un-notifiable
      message never raises and never suppresses the rest.
    """
    records = (event or {}).get("Records")
    if records is not None:
        for record in records:
            _guarded_notify(record)
        return {"drained": len(records)}

    return {"drained": sum(_sweep_one_queue(arn) for arn in _dlq_arns())}
