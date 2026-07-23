"""Sweep the structured-logging queue into Hive-partitioned NDJSON on S3 (SPEC-127).

Every control-plane verb emits ``log-foundry`` events to a standard SQS queue. This function is
the other end: an EventBridge schedule fires it every 5 minutes, it drains what is there, groups
the events by ``(service, dt, hh)``, and writes one NDJSON object per group under
``s3://{admin-bucket}/logs/{service}/dt=…/hh=…/``.

**It pulls; it never long-polls.** The delivery model is the whole point of the design. An SQS
event-source mapping or an EventBridge Pipe holds an always-on managed poll loop against a queue
that is empty most of the time, and that idle long-polling was the bulk of this account's SQS
request volume — the problem #270/#271 fixed by converting the DLQ drain from four event-source
mappings to one scheduled sweep. A scheduled consumer that then called ``receive_message`` with
``WaitTimeSeconds=20`` would reintroduce the same cost from a different direction, spending 20
billed seconds per empty round doing nothing. Hence ``WaitTimeSeconds=0`` below, which is
mandatory rather than an oversight.

**Every message is routable, so every message is deletable.** A sweep that left messages it
could not understand on the queue would build a slow poison loop: the same body received,
rejected and redelivered every 5 minutes until retention expires. An unparseable body, or one
whose ``service`` is missing or malformed, is written verbatim under ``logs/_unrouted/`` and then
deleted — see :func:`_route`, where ``service`` is treated as untrusted input on a path.
"""

import json
import logging
import os
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from cpcommon import clients, observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="observability")

ADMIN_BUCKET = os.environ.get("ADMIN_BUCKET", "")
LOGS_QUEUE_URL = os.environ.get("LOGS_QUEUE_URL", "")
LOGS_PREFIX = "logs"

#: `service` becomes part of an S3 key and arrives inside a message body, so it is untrusted
#: input on a path — the same class of surface every validate-authorize verb exists to police.
#: Anything that does not match lands in _unrouted/ rather than being used to build a key.
SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{2,62}$")

#: Where a body goes when it cannot be routed. Not a valid `service` (the pattern above forbids
#: a leading underscore), so a real service can never collide with it.
UNROUTED = "_unrouted"

#: One sweep is bounded: 100 rounds of 10. The next schedule tick picks up any remainder five
#: minutes later, so the cap costs latency on a backlog, never data.
MAX_ROUNDS = 100
MAX_MESSAGES = 1000


def _partition(event):
    """Return ``(dt, hh)`` for an event, from the EVENT's own timestamp.

    Deliberately not the sweep's clock. A delayed or replayed event stamped with sweep time
    lands in the wrong hour and becomes invisible to anyone querying the window it actually
    belongs to — which is precisely the window they would be querying while debugging it.

    Falls back to the sweep clock when the timestamp is missing or unparseable; the caller
    counts those so a systematic problem shows up rather than hiding in the partitions.
    """
    raw = event.get("timestamp") if isinstance(event, dict) else None
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.strftime("%Y-%m-%d"), parsed.strftime("%H"), False
        except ValueError:
            pass
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d"), now.strftime("%H"), True


def _route(body):
    """Return ``(service, event_or_none)`` for one raw message body.

    A body that is not valid JSON, is not an object, or carries a missing/malformed ``service``
    routes to ``_unrouted`` and is preserved VERBATIM — the point of _unrouted is to be able to
    see what actually arrived, so nothing is normalised on the way in.
    """
    try:
        event = json.loads(body)
    except (ValueError, TypeError):
        return UNROUTED, None
    if not isinstance(event, dict):
        return UNROUTED, None
    service = event.get("service")
    if not isinstance(service, str) or not SERVICE_RE.match(service):
        return UNROUTED, None
    return service, event


def _receive_all():
    """Short-poll the queue until a round comes back empty or the cap is hit.

    Returns ``(messages, truncated)``. ``truncated`` is surfaced by the caller rather than
    swallowed: a silent cap reads as "swept everything" when it didn't.
    """
    sqs = clients.sqs()
    messages = []
    for _ in range(MAX_ROUNDS):
        if len(messages) >= MAX_MESSAGES:
            return messages, True
        batch = sqs.receive_message(
            QueueUrl=LOGS_QUEUE_URL,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=0,  # short poll — see the module docstring; this is mandatory
            MessageAttributeNames=[],
        ).get("Messages", [])
        if not batch:
            return messages, False
        messages.extend(batch)
    return messages, True


def _write_group(sweep_id, seq, service, dt, hh, bodies):
    """Write one group's NDJSON. Returns True only if the object actually landed."""
    key = f"{LOGS_PREFIX}/{service}/dt={dt}/hh={hh}/{sweep_id}-{seq}.ndjson"
    try:
        clients.s3().put_object(
            Bucket=ADMIN_BUCKET,
            Key=key,
            Body=("\n".join(bodies) + "\n").encode("utf-8"),
            ContentType="application/x-ndjson",
        )
        return True
    except Exception:
        # Not fatal to the sweep: this group's messages simply are not deleted, so they
        # redeliver after the visibility timeout and the next sweep retries them. Other
        # services' groups still get written.
        logger.exception("log-sweep: failed to write %s (%d events left on queue)", key, len(bodies))
        return False


def _delete(receipts):
    """Delete a group's messages, in SQS's batch-of-10 chunks."""
    sqs = clients.sqs()
    for i in range(0, len(receipts), 10):
        chunk = receipts[i : i + 10]
        try:
            sqs.delete_message_batch(
                QueueUrl=LOGS_QUEUE_URL,
                Entries=[{"Id": str(n), "ReceiptHandle": r} for n, r in enumerate(chunk)],
            )
        except Exception:
            # The events are already durable in S3; a failed delete only means they will be
            # written again next sweep, producing duplicate log_ids that a reader collapses.
            logger.exception("log-sweep: failed to delete %d messages", len(chunk))


@observability.traced("sweep")
def handler(event, context):
    """Drain the logs queue into S3. Total: no message can make this raise.

    The sweep instruments ITSELF (``service="observability"``), which is what makes SPEC-127
    verifiable end to end without instrumenting a control plane. The self-reference is safe —
    this invocation's own events go through the same queue and are collected by the NEXT
    scheduled sweep, never recursively within this one.
    """
    if not LOGS_QUEUE_URL or not ADMIN_BUCKET:
        logger.warning("log-sweep: LOGS_QUEUE_URL or ADMIN_BUCKET unset — nothing to do")
        return {"swept": 0, "written": 0}

    messages, truncated = _receive_all()
    if not messages:
        return {"swept": 0, "written": 0}

    groups = defaultdict(list)  # (service, dt, hh) -> [(body, receipt), ...]
    undated = 0
    for message in messages:
        body = message.get("Body", "")
        service, parsed = _route(body)
        dt, hh, fell_back = _partition(parsed)
        undated += 1 if fell_back else 0
        groups[(service, dt, hh)].append((body, message.get("ReceiptHandle", "")))

    sweep_id = uuid.uuid4().hex
    written = 0
    for seq, ((service, dt, hh), items) in enumerate(sorted(groups.items())):
        bodies = [b for b, _ in items]
        if _write_group(sweep_id, seq, service, dt, hh, bodies):
            written += len(bodies)
            # Strictly AFTER a successful put. The resulting guarantee is at-least-once: a
            # sweep that writes and then dies before deleting will write those events again
            # next round, producing duplicate log_ids that a reader collapses on. Losing logs
            # is worse than duplicating them.
            _delete([r for _, r in items if r])

    if truncated:
        # Explicit, with the count — a silent cap reads as "swept everything" when it didn't.
        logger.warning(
            "log-sweep: hit the %d-message cap; %d messages taken this round, remainder next sweep",
            MAX_MESSAGES,
            len(messages),
        )
    if undated:
        logger.warning("log-sweep: %d event(s) had no usable timestamp; used the sweep clock", undated)

    logger.info(
        "log-sweep: %d message(s) in %d group(s), %d written", len(messages), len(groups), written
    )
    return {"swept": len(messages), "written": written, "groups": len(groups)}
