"""Sweep the structured-logging queue into one NDJSON object per service per day (SPEC-127/129).

Every control-plane verb emits ``log-foundry`` events to a FIFO SQS queue. This function is the
other end: an EventBridge schedule fires it every 10 minutes, it drains what is there, groups the
events by ``(service, year, month, day)``, and **appends** them to that day's object at
``s3://{admin-bucket}/logs/service={service}/year=YYYY/month=MM/day=DD/data.jsonl``.

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
rejected and redelivered every 10 minutes until retention expires. An unparseable body, or one
whose ``service`` is missing or malformed, is written verbatim under
``logs/service=_unrouted/`` and then deleted — see :func:`_route`, where ``service`` is treated
as untrusted input on a path.

**Appending costs a read, and S3 has no append.** One object per day per service means
read-modify-write: GET what is there, concatenate, PUT it back. Two consequences are designed
for rather than discovered:

* **Lost updates.** Two overlapping sweeps would both read the same object and the second PUT
  would silently erase the first one's events. Every write is therefore conditional —
  ``If-None-Match: *`` to create, ``If-Match: <etag>`` to extend — and a precondition failure
  re-reads and re-applies, the same CAS loop ``dqcommon.index_store`` uses for the runs index.
* **The object only grows.** A day's file is rewritten in full on every sweep, so the bytes moved
  per day scale with the square of the day's volume. :data:`LARGE_OBJECT_WARN_BYTES` logs when a
  day's object gets big enough for that to matter, because the alternative is discovering it as a
  timeout months later.
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

#: Set once per invocation (FR-007) and prepended to every CloudWatch line by ``_SweepIdFilter``.
_sweep_id = ""


class _SweepIdFilter(logging.Filter):
    """Prepend this invocation's ``sweep_id`` to every CloudWatch line the sweep writes.

    A filter rather than an edit to each ``logger.*`` call, for two reasons. The structured
    events and the CloudWatch lines are two accounts of the same sweep, and a join key present on
    only one side of the join is not a join key — so *every* line needs it, including the ones in
    ``_read_day`` and ``_append_day`` that know nothing about the invocation. And a line added
    later gets the id for free, which is the difference between a property and a convention.
    """

    def filter(self, record):
        if _sweep_id and not str(record.msg).startswith("[sweep "):
            record.msg = f"[sweep {_sweep_id}] {record.msg}"
        return True


logger.addFilter(_SweepIdFilter())

ADMIN_BUCKET = os.environ.get("ADMIN_BUCKET", "")
LOGS_QUEUE_URL = os.environ.get("LOGS_QUEUE_URL", "")
LOGS_PREFIX = "logs"
DAY_OBJECT = "data.jsonl"

#: `service` becomes part of an S3 key and arrives inside a message body, so it is untrusted
#: input on a path — the same class of surface every validate-authorize verb exists to police.
#: Anything that does not match lands under service=_unrouted rather than building a key.
SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{2,62}$")

#: Where a body goes when it cannot be routed. Not a valid `service` (the pattern above forbids
#: a leading underscore), so a real service can never collide with it.
UNROUTED = "_unrouted"

#: One sweep is bounded: 100 rounds of 10. The next schedule tick picks up any remainder ten
#: minutes later, so the cap costs latency on a backlog, never data.
MAX_ROUNDS = 100
MAX_MESSAGES = 1000

#: CAS attempts per day-object before giving up and leaving the messages queued.
MAX_CAS_ATTEMPTS = 5

#: Read-modify-write moves the whole object every sweep. At this size that is worth knowing
#: about — the function has 512 MB and a 300s timeout, and both are finite.
LARGE_OBJECT_WARN_BYTES = 64 * 1024 * 1024


def _partition(event):
    """Return ``(year, month, day, fell_back)`` for an event, from the EVENT's own timestamp.

    Deliberately not the sweep's clock. A delayed or replayed event stamped with sweep time
    lands in the wrong day and becomes invisible to anyone querying the window it actually
    belongs to — which is precisely the window they would be querying while debugging it.

    Falls back to the sweep clock when the timestamp is missing or unparseable; the caller
    counts those so a systematic problem shows up rather than hiding in the partitions.
    """
    raw = event.get("timestamp") if isinstance(event, dict) else None
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.strftime("%Y"), parsed.strftime("%m"), parsed.strftime("%d"), False
        except ValueError:
            pass
    now = datetime.now(timezone.utc)
    return now.strftime("%Y"), now.strftime("%m"), now.strftime("%d"), True


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


def _day_key(service, year, month, day):
    """The Hive-partitioned key for one service-day.

    ``service=`` is a partition column like the date parts, so an Athena table over ``logs/``
    can prune on it — the reason it is ``service={name}`` rather than a bare directory.
    """
    return f"{LOGS_PREFIX}/service={service}/year={year}/month={month}/day={day}/{DAY_OBJECT}"


def _read_day(key):
    """Return ``(existing_bytes, etag)``. ``(b"", None)`` when the object does not exist yet.

    A read failure is reported as "absent with no etag", which makes the following write use
    ``If-None-Match: *`` — so a transient read error can never cause a silent OVERWRITE of a
    day's logs. It fails the write instead, and the messages stay queued for the next sweep.
    """
    try:
        response = clients.s3().get_object(Bucket=ADMIN_BUCKET, Key=key)
        return response["Body"].read(), response.get("ETag")
    except Exception as err:  # noqa: BLE001 - absent is the ordinary case on the day's first sweep
        logger.info("log-sweep: no existing object at %s (%s); creating it", key, err)
        return b"", None


def _is_precondition(exc):
    """True when a conditional PutObject lost to a concurrent writer.

    ``PreconditionFailed``/412 is If-Match losing; ``ConditionalRequestConflict``/409 is what S3
    returns when two If-None-Match creates race — which is exactly what two sweeps would do on
    the first event of a new day. Same predicate as ``dqcommon.index_store``.
    """
    code = str(((getattr(exc, "response", {}) or {}).get("Error") or {}).get("Code", ""))
    return code in ("PreconditionFailed", "412", "ConditionalRequestConflict", "409")


@observability.step("append-day")
def _append_day(key, new_lines):
    """Append lines to a day's object under CAS. Returns True only if they landed.

    Re-reads and re-applies on a precondition failure rather than retrying the same write: the
    whole point is that the object changed underneath us, so the new content has to be rebuilt
    on top of what the winner wrote.

    One destination, one child span, and the events below are per-destination — never per
    message (SPEC-131 FR-005). ``reason`` on the failure path is a stable token rather than a
    stringified exception: a reason you can filter on is worth more than a message you can read
    once.
    """
    payload = ("\n".join(new_lines) + "\n").encode("utf-8")
    observability.info("appending", key=key, events=len(new_lines))
    for attempt in range(MAX_CAS_ATTEMPTS):
        existing, etag = _read_day(key)
        if len(existing) > LARGE_OBJECT_WARN_BYTES:
            logger.warning(
                "log-sweep: %s is %.1f MB; read-modify-write moves it in full every sweep",
                key,
                len(existing) / 1024 / 1024,
            )
            observability.warning("day object is large", key=key, bytes=len(existing))
        # A day's object always ends in a newline (below), so concatenation needs no separator —
        # but tolerate a hand-edited object that doesn't.
        if existing and not existing.endswith(b"\n"):
            existing += b"\n"
        kwargs = {
            "Bucket": ADMIN_BUCKET,
            "Key": key,
            "Body": existing + payload,
            "ContentType": "application/x-ndjson",
        }
        if etag is None:
            kwargs["IfNoneMatch"] = "*"
        else:
            kwargs["IfMatch"] = etag
        try:
            clients.s3().put_object(**kwargs)
            observability.info(
                "appended",
                key=key,
                events=len(new_lines),
                bytes=len(existing) + len(payload),
            )
            return True
        except Exception as err:  # every failure path is total (see handler)
            if _is_precondition(err):
                logger.info(
                    "log-sweep: %s changed under us (attempt %d/%d); re-reading",
                    key,
                    attempt + 1,
                    MAX_CAS_ATTEMPTS,
                )
                # Once per retry, because the retry COUNT is the contention signal — a sweep
                # that succeeds on attempt 4 is a sweep that nearly didn't.
                observability.warning(
                    "day object changed under us",
                    key=key,
                    attempt=attempt + 1,
                    attempts=MAX_CAS_ATTEMPTS,
                )
                continue
            # Not a race: a real write failure. The messages stay on the queue and redeliver.
            logger.exception("log-sweep: failed to write %s (%d events left queued)", key, len(new_lines))
            observability.error(
                "append failed", key=key, events=len(new_lines), reason="write-failed"
            )
            return False
    logger.error(
        "log-sweep: gave up on %s after %d CAS attempts; %d events left queued for the next sweep",
        key,
        MAX_CAS_ATTEMPTS,
        len(new_lines),
    )
    observability.error(
        "append failed", key=key, events=len(new_lines), reason="precondition-exhausted"
    )
    return False


@observability.step("receive")
def _receive_all():
    """Short-poll the queue until a round comes back empty or the cap is hit.

    Returns ``(messages, truncated)``. ``truncated`` is surfaced by the caller rather than
    swallowed: a silent cap reads as "swept everything" when it didn't.

    Its own child span because the poll loop and the writes have completely different failure
    modes, and this is the half that is billed per round.
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


def _delete(receipts):
    """Delete a group's messages, in SQS's batch-of-10 chunks."""
    sqs = clients.sqs()
    undeleted = 0
    for i in range(0, len(receipts), 10):
        chunk = receipts[i : i + 10]
        try:
            sqs.delete_message_batch(
                QueueUrl=LOGS_QUEUE_URL,
                Entries=[{"Id": str(n), "ReceiptHandle": r} for n, r in enumerate(chunk)],
            )
        except Exception:
            # The events are already durable in S3; a failed delete only means they will be
            # appended again next sweep, producing duplicate log_ids that a reader collapses.
            logger.exception("log-sweep: failed to delete %d messages", len(chunk))
            undeleted += len(chunk)
    if undeleted:
        # ONE event per group, not per failed chunk — a chunk is 10 messages, so a per-chunk
        # emitter would be O(messages) on exactly the path where the queue is already unhappy.
        observability.warning(
            "delete failed; events will be appended again next sweep",
            events=undeleted,
            lost=False,
        )


@observability.traced("sweep")
def handler(event, context):
    """Drain the logs queue into the day's objects. Total: no message can make this raise.

    The sweep instruments ITSELF (``service="observability"``), which is what makes the pipe
    verifiable end to end without instrumenting a control plane. The self-reference is safe —
    this invocation's own events go through the same queue and are collected by the NEXT
    scheduled sweep, never recursively within this one.

    **That self-reference is also why the event count here is bounded** (SPEC-131 FR-005).
    Every emitter below is per-sweep or per-day-group, never per message: this function emits
    into the queue it drains, so an event per message consumed would mean draining M messages
    produced ~M more, and the queue would have a floor it could never get below — permanently
    busy carrying its own telemetry, with the day objects growing to match. Day-groups are
    bounded by the number of control planes; messages are bounded by nothing.

    **The existing ``logger`` calls stay alongside the structured events, deliberately, and
    this is the one function where that is not duplication to copy into a verb.** The sink is
    SQS-only (SPEC-127, user decision), so a sweep that cannot write to S3 cannot report through
    the structured store that it could not write to S3 — the mechanism that would carry the
    report is the thing that failed. Its CloudWatch line is the only account of that failure
    that exists.
    """
    global _sweep_id
    # Before any emitter, so every event of this invocation carries it — including the boundary
    # spans, which is what joins the two accounts. `traced`'s _reset_baggage() clears it between
    # warm invocations, so a sweep can never inherit the previous one's id.
    _sweep_id = sweep_id = uuid.uuid4().hex
    observability.stamp(sweep_id=sweep_id)

    if not LOGS_QUEUE_URL or not ADMIN_BUCKET:
        logger.warning("log-sweep: LOGS_QUEUE_URL or ADMIN_BUCKET unset — nothing to do")
        observability.warning(
            "not configured",
            has_queue=bool(LOGS_QUEUE_URL),
            has_bucket=bool(ADMIN_BUCKET),
        )
        return {"swept": 0, "written": 0}

    messages, truncated = _receive_all()
    if not messages:
        return {"swept": 0, "written": 0}

    groups = defaultdict(list)  # (service, year, month, day) -> [(body, receipt), ...]
    undated = 0
    unrouted = 0
    for message in messages:
        body = message.get("Body", "")
        service, parsed = _route(body)
        year, month, day, fell_back = _partition(parsed)
        undated += 1 if fell_back else 0
        unrouted += 1 if service == UNROUTED else 0
        groups[(service, year, month, day)].append((body, message.get("ReceiptHandle", "")))

    observability.info("received", messages=len(messages), groups=len(groups))

    written = 0
    failed = 0
    for (service, year, month, day), items in sorted(groups.items()):
        key = _day_key(service, year, month, day)
        if _append_day(key, [b for b, _ in items]):
            written += len(items)
            # Strictly AFTER a successful append. The resulting guarantee is at-least-once: a
            # sweep that writes and then dies before deleting will append those events again
            # next round, producing duplicate log_ids that a reader collapses on. Losing logs
            # is worse than duplicating them.
            _delete([r for _, r in items if r])
        else:
            failed += len(items)

    if truncated:
        # Explicit, with the count — a silent cap reads as "swept everything" when it didn't.
        logger.warning(
            "log-sweep: hit the %d-message cap; %d messages taken this round, remainder next sweep",
            MAX_MESSAGES,
            len(messages),
        )
        observability.warning("hit the message cap", limit=MAX_MESSAGES, taken=len(messages))
    if undated:
        logger.warning("log-sweep: %d event(s) had no usable timestamp; used the sweep clock", undated)
        observability.warning("events had no usable timestamp", undated=undated)
    if unrouted:
        # The body itself is NOT logged. Not on sensitivity grounds — it is already preserved
        # verbatim under logs/service=_unrouted/, where it can be read deliberately — but
        # because it is unbounded input from a queue, and echoing it into a day object risks
        # precisely the growth the read-modify-write design is careful about.
        observability.warning("bodies could not be routed", unrouted=unrouted)

    logger.info(
        "log-sweep %s: %d message(s) in %d day-group(s), %d written",
        sweep_id,
        len(messages),
        len(groups),
        written,
    )
    # Level carries the outcome, so "a sweep that partly failed" is reachable without reading a
    # field: the old summary reported swept/groups/written and no failure count at all, so a
    # sweep that wrote two destinations of three read as a success in every field it had.
    outcome = observability.error if failed else observability.info
    outcome(
        "swept",
        messages=len(messages),
        groups=len(groups),
        written=written,
        failed=failed,
    )
    return {"swept": len(messages), "written": written, "groups": len(groups)}
