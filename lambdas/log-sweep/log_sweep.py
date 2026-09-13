"""Sweeps the structured-logging queue into one NDJSON object per service per day.

Every control-plane verb emits events to a FIFO SQS queue. This function is the other end: a
schedule fires it every ten minutes, it drains what is there, groups the events by service and
date, and appends them to that day's object under the admin bucket.

It pulls; it never long-polls. An always-on managed poll loop against a queue that is empty
most of the time was the bulk of this account's SQS request volume, and a scheduled consumer
that then waited on each receive would reintroduce the same cost from a different direction.
The zero wait below is mandatory rather than an oversight.

Every message is routable, so every message is deletable. A sweep that left messages it could
not understand on the queue would build a slow poison loop. An unparseable body, or one whose
service is missing or malformed, is written verbatim under the unrouted partition and then
deleted.

Appending costs a read, and S3 has no append, so one object per day per service means
read-modify-write. Two consequences are designed for rather than discovered: overlapping sweeps
would lose updates, so every write is conditional and a precondition failure re-reads and
re-applies; and a day's file is rewritten in full on every write, so the bytes moved per day
scale with the square of the day's volume. A sweep writes once per wave in which that day-group
appears, not once per invocation — draining a deep backlog is hundreds of read-modify-writes
over an already-large object, which is what ``LARGE_OBJECT_WARN_BYTES`` and the reserve below
exist to keep visible.

A sweep is a loop of waves, and the queue's own ordering is why. On a FIFO queue a message group
stops yielding once one of its messages is in flight, until that message is deleted or its
visibility lapses — so a receive loop that holds everything it has taken can only ever collect
one round per group, however many rounds it is allowed. Deleting is what unblocks the group, and
a message may only be deleted once its events are durable in S3, so the receive, the write and
the delete have to repeat together rather than run once each. Before this was understood the
sweep took exactly ``10 x backlogged groups`` messages per invocation and reported itself
drained, and the queue fell six days behind on a fourteen-day retention.

The same rule made the message group the sweep's real ceiling: each group gives up ten a wave,
however many waves run. The producers therefore put every event in its own group, so a wave
takes up to ``MAX_MESSAGES`` from any mix of services; grouped by service, one working
session's API traffic outran ten a wave for hours. The wave loop still earns its place — a
wave can fill its cap, and a message left behind by an older producer is still in a shared
group.

The emitters that ride the receive and the write run once per wave rather than once per sweep,
which for a function that logs into the queue it drains is a volume decision rather than a
detail. What convergence needs is that the sweep puts back less than it takes from every group
its own output lands in. Grouped by service, that was one group giving up ten a wave while
each wave put three events plus four per day-group into it, so the sweep's own group grew
whenever another group was behind. Grouped per event, its output drains alongside everything
else, and the ratio across the whole queue is the one that matters. The counters the handler
keeps — waves, messages, day-groups — are summed across the sweep and reported once, so the
summary stays one event however deep the backlog.

Attributes:
  _sweep_id: Set once per invocation and prepended to every CloudWatch line by the filter below.
  ADMIN_BUCKET: Destination bucket, set by Terraform.
  LOGS_QUEUE_URL: Source queue, set by Terraform.
  LOGS_PREFIX: Root prefix for the partitioned layout.
  DAY_OBJECT: The per-day object's basename.
  SERVICE_RE: The service name rule. A service becomes part of an S3 key and arrives inside a
    message body, so it is untrusted input on a path — the same class of surface every
    validate-authorize verb exists to police.
  UNROUTED: Where a body goes when it cannot be routed. Not a valid service name, since the
    pattern forbids a leading underscore, so a real service can never collide with it.
  MAX_ROUNDS: Receive rounds per wave.
  MAX_MESSAGES: Message cap per wave. The next wave, or the next schedule tick, picks up any
    remainder, so the cap costs latency on a backlog, never data.
  MAX_WAVES: Receive-write-delete cycles per sweep. With every event in its own group a full
    wave is ``MAX_MESSAGES``, and about this many full waves fit in the timeout after the
    reserve, so this is where the wave cap and the time reserve meet rather than a number the
    arrival rate is divided by. A caught-up sweep stops well short of it during an active
    session, on the first wave that held only what arrived after the sweep started and whose
    receive ended on an empty round. The queue's age, not this stop, is the backlog signal.
  SWEEP_RESERVE_MS: Invocation time held back for the final wave's write and delete. The wave
    cost is a function of the day object's size, which grows all day, so the wave count alone
    cannot bound the sweep's duration.
  STOP_WAVE_CAP, STOP_TIME_RESERVE, STOP_GROUP_BLOCKED: Why a sweep stopped with the queue
    possibly still yielding. Separate values rather than one flag because the three want
    opposite responses — more waves, a longer timeout, and a look at whatever is leaving
    messages in flight — and a reason you can filter on is worth more than a message you can
    read once. ``group-blocked`` names the condition rather than either cause, because an
    undeleted message blocks its group exactly as an unwritten one does, and because
    ``_append_day`` already emits ``reason="write-failed"`` for a different thing entirely. It
    qualifies either way a sweep finishes on its own, an empty receive or a wave of arrivals,
    since a blocked group can hide older messages from both; the clock and the cap outrank it.
  MAX_CAS_ATTEMPTS: Conditional-write attempts per day object before giving up and leaving the
    messages queued. ``cpcommon.cas.MAX_ATTEMPTS`` — this was one of three
    copies of the loop, and the caps had drifted.
  LARGE_OBJECT_WARN_BYTES: Size at which the read-modify-write cost is worth knowing about. The
    function has finite memory and a finite timeout, and the alternative is discovering this as
    a timeout months later.
"""

import json
import logging
import os
import re
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from cpcommon import cas, clients, observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="observability")

_sweep_id = ""


class _SweepIdFilter(logging.Filter):
    """Prepends this invocation's sweep id to every CloudWatch line the sweep writes.

    A filter rather than an edit to each logging call, for two reasons. The structured events
    and the CloudWatch lines are two accounts of the same sweep, and a join key present on only
    one side of the join is not a join key — so every line needs it, including the ones in
    helpers that know nothing about the invocation. And a line added later gets the id for free,
    which is the difference between a property and a convention.
    """

    def filter(self, record):
        """Prefixes the record's message with the sweep id when one is set.

        Args:
          record: The log record.

        Returns:
          True, always — this filter annotates rather than excludes.

        Raises:
          None.
        """
        if _sweep_id and not str(record.msg).startswith("[sweep "):
            record.msg = f"[sweep {_sweep_id}] {record.msg}"
        return True


logger.addFilter(_SweepIdFilter())

ADMIN_BUCKET = os.environ.get("ADMIN_BUCKET", "")
LOGS_QUEUE_URL = os.environ.get("LOGS_QUEUE_URL", "")
LOGS_PREFIX = "logs"
DAY_OBJECT = "data.jsonl"

SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{2,62}$")

UNROUTED = "_unrouted"

MAX_ROUNDS = 100
MAX_MESSAGES = 1000

MAX_WAVES = 50
SWEEP_RESERVE_MS = 60_000

STOP_WAVE_CAP = "wave-cap"
STOP_TIME_RESERVE = "time-reserve"
STOP_GROUP_BLOCKED = "group-blocked"

MAX_CAS_ATTEMPTS = cas.MAX_ATTEMPTS

LARGE_OBJECT_WARN_BYTES = 64 * 1024 * 1024


def _partition(event):
    """Derives the date partition for one event, from the event's own timestamp.

    Deliberately not the sweep's clock. A delayed or replayed event stamped with sweep time
    lands in the wrong day and becomes invisible to anyone querying the window it actually
    belongs to — which is precisely the window they would be querying while debugging it.

    Args:
      event: The parsed event, or None when the body could not be routed.

    Returns:
      A ``(year, month, day, fell back)`` tuple. The fallback flag is set when the timestamp was
      missing or unparseable and the sweep clock was used instead; the caller counts those so a
      systematic problem shows up rather than hiding in the partitions.

    Raises:
      None.
    """
    raw = event.get("timestamp") if isinstance(event, dict) else None
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
            return parsed.strftime("%Y"), parsed.strftime("%m"), parsed.strftime("%d"), False
        except ValueError:
            pass
    now = datetime.now(UTC)
    return now.strftime("%Y"), now.strftime("%m"), now.strftime("%d"), True


def _route(body):
    """Decides which service partition one raw message body belongs to.

    A body that is not valid JSON, is not an object, or carries a missing or malformed service
    routes to the unrouted partition and is preserved verbatim — the point of that partition is
    to be able to see what actually arrived, so nothing is normalised on the way in.

    Args:
      body: The raw SQS message body.

    Returns:
      A ``(service, parsed event or None)`` tuple.

    Raises:
      None.
    """
    try:
        event = json.loads(body)
    except (ValueError, TypeError):
        return UNROUTED, None
    if not isinstance(event, dict):
        return UNROUTED, None
    service = event.get("service")
    if not isinstance(service, str) or not SERVICE_RE.fullmatch(service):
        return UNROUTED, None
    return service, event


def _day_key(service, year, month, day):
    """Builds the Hive-partitioned key for one service-day.

    The service is a partition column like the date parts, so an Athena table over the log
    prefix can prune on it — the reason it is a partition assignment rather than a bare
    directory.

    Args:
      service: The service name.
      year: The four-digit year.
      month: The two-digit month.
      day: The two-digit day.

    Returns:
      The object key.

    Raises:
      None.
    """
    return f"{LOGS_PREFIX}/service={service}/year={year}/month={month}/day={day}/{DAY_OBJECT}"


def _read_day(key):
    """Reads a day object's current contents and entity tag.

    A read failure is reported as absent with no tag, which makes the following write a
    create-only conditional — so a transient read error can never cause a silent overwrite of a
    day's logs. It fails the write instead, and the messages stay queued for the next sweep.

    Args:
      key: The day object's key.

    Returns:
      An ``(existing bytes, etag)`` tuple, empty and None when the object does not exist yet.

    Raises:
      None.
    """
    try:
        response = clients.s3().get_object(Bucket=ADMIN_BUCKET, Key=key)
        return response["Body"].read(), response.get("ETag")
    except Exception as err:  # noqa: BLE001
        logger.info("log-sweep: no existing object at %s (%s); creating it", key, err)
        return b"", None


@observability.step("append-day")
def _append_day(key, new_lines):
    """Appends lines to a day's object under a compare-and-swap loop.

    Re-reads and re-applies on a precondition failure rather than retrying the same write: the
    whole point is that the object changed underneath, so the new content has to be rebuilt on
    top of what the winner wrote. Contention is recorded once per retry, because the retry count
    is the signal — a sweep that succeeds on the fourth attempt is a sweep that nearly did not.

    One destination, one child span, and every event here is per destination, never per message.
    The failure reason is a stable token rather than a stringified exception: a reason you can
    filter on is worth more than a message you can read once. Exhaustion and a write fault are
    two reasons, which is why the shared loop raises a distinct type for the first rather than
    leaving them to be told apart by message text.

    ``skip_no_op=False`` because this loop never had a no-op check. ``payload`` is never empty
    today, so the shared default would not fire — but resting on that inequality would make an
    empty-batch caller silently stop writing instead of writing an empty append.

    Args:
      key: The day object's key.
      new_lines: The message bodies to append.

    Returns:
      True only if the lines landed. On False the messages stay on the queue and redeliver.

    Raises:
      None.
    """
    payload = ("\n".join(new_lines) + "\n").encode("utf-8")
    observability.info("appending", key=key, events=len(new_lines))

    def _read():
        """Reads the day object, warning when it has grown expensive to rewrite in full.

        Args:
          None.

        Returns:
          The ``(existing bytes, etag)`` tuple.

        Raises:
          None.
        """
        existing, etag = _read_day(key)
        if len(existing) > LARGE_OBJECT_WARN_BYTES:
            logger.warning(
                "log-sweep: %s is %.1f MB; read-modify-write moves it in full every sweep",
                key,
                len(existing) / 1024 / 1024,
            )
            observability.warning("day object is large", key=key, bytes=len(existing))
        return existing, etag

    def _apply(existing):
        """Builds the new day object: the existing bytes, newline-terminated, plus the payload.

        Args:
          existing: The day object's current bytes, empty when it does not exist yet.

        Returns:
          The full body to write.

        Raises:
          None.
        """
        if existing and not existing.endswith(b"\n"):
            existing += b"\n"
        return existing + payload

    def _write(body, etag):
        """Writes the day object conditionally on the tag it was read at.

        Args:
          body: The full object body.
          etag: The tag to match, or None to write only if the object is absent.

        Returns:
          None.

        Raises:
          ClientError: On a precondition failure, so the loop can retry, or any other S3 fault.
        """
        kwargs = {
            "Bucket": ADMIN_BUCKET,
            "Key": key,
            "Body": body,
            "ContentType": "application/x-ndjson",
        }
        if etag is None:
            kwargs["IfNoneMatch"] = "*"
        else:
            kwargs["IfMatch"] = etag
        clients.s3().put_object(**kwargs)

    def _on_conflict(attempt):
        """Records one lost race, in both accounts of the sweep.

        Args:
          attempt: The 1-based attempt that lost.

        Returns:
          None.

        Raises:
          None.
        """
        logger.info(
            "log-sweep: %s changed under us (attempt %d/%d); re-reading",
            key,
            attempt,
            MAX_CAS_ATTEMPTS,
        )
        observability.warning(
            "day object changed under us", key=key, attempt=attempt, attempts=MAX_CAS_ATTEMPTS
        )

    try:
        written = cas.cas_mutate(
            _read,
            _apply,
            _write,
            label=key,
            max_attempts=MAX_CAS_ATTEMPTS,
            on_conflict=_on_conflict,
            skip_no_op=False,
        )
    except cas.CasExhausted:
        logger.error(
            "log-sweep: gave up on %s after %d CAS attempts; %d events left queued for the "
            "next sweep",
            key,
            MAX_CAS_ATTEMPTS,
            len(new_lines),
        )
        observability.error(
            "append failed", key=key, events=len(new_lines), reason="precondition-exhausted"
        )
        return False
    except Exception:
        logger.exception("log-sweep: failed to write %s (%d events left queued)", key, len(new_lines))
        observability.error("append failed", key=key, events=len(new_lines), reason="write-failed")
        return False

    observability.info("appended", key=key, events=len(new_lines), bytes=len(written))
    return True


@observability.step("receive")
def _receive_all():
    """Short-polls the queue until a round comes back empty or the cap is hit.

    One wave's receive, not the sweep's. An empty round here does not have to mean the queue is
    empty: on a FIFO queue a group this wave has touched yields nothing more until the wave's
    delete lands, which is why the caller writes and deletes and comes back rather than treating
    the empty round as the end of the sweep, unless everything the wave took arrived after the
    sweep began. With every event in its own group no group holds a second message, so the loop
    runs until the queue or the cap is exhausted — and a message from an older producer, still
    in a shared group, is what the coming back is still for.

    Its own child span because the poll loop and the writes have completely different failure
    modes, and this is the half that is billed per round. The span opens once per wave rather
    than once per sweep, a volume decision taken deliberately: this function emits into the
    queue it drains, and its events land in groups of their own, so they drain alongside the
    messages they describe rather than queueing behind them.

    Each message comes back with its ``SentTimestamp``, which is how the caller tells a wave of
    backlog from a wave of arrivals.

    Args:
      None.

    Returns:
      A ``(messages, truncated)`` tuple. The caller surfaces the truncation rather than
      swallowing it: a silent cap reads as "swept everything" when it did not.

    Raises:
      ClientError: On any SQS receive fault.
    """
    sqs = clients.sqs()
    messages = []
    for _ in range(MAX_ROUNDS):
        if len(messages) >= MAX_MESSAGES:
            return messages, True
        batch = sqs.receive_message(
            QueueUrl=LOGS_QUEUE_URL,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=0,
            MessageAttributeNames=[],
            MessageSystemAttributeNames=["SentTimestamp"],
        ).get("Messages", [])
        if not batch:
            return messages, False
        messages.extend(batch)
    return messages, True


def _time_is_short(context):
    """Reports whether too little of the invocation is left to risk another wave.

    A wave's cost tracks the day object's size, which grows all day, so ``MAX_WAVES`` bounds the
    wave count but not the duration. Falls back to False when there is no context, which is the
    local and test case: the wave cap still bounds those.

    Args:
      context: The Lambda context, or None.

    Returns:
      True when the remaining time is under the reserve.

    Raises:
      None.
    """
    remaining = getattr(context, "get_remaining_time_in_millis", None)
    return bool(remaining) and remaining() < SWEEP_RESERVE_MS


def _sent_since(message, started_ms):
    """Reports whether the queue stamped one message at or after the sweep began.

    A message the sweep cannot date reads as older, because the two wrong answers are not
    symmetric: calling an old message new can end a sweep with backlog still queued, while
    calling a new one old only costs the wave the sweep would have run anyway.

    Args:
      message: One message as ``receive_message`` returned it.
      started_ms: The sweep's start, in epoch milliseconds.

    Returns:
      True only when the message carries a ``SentTimestamp`` that parses as an integer no
      earlier than ``started_ms``.

    Raises:
      None.
    """
    attributes = message.get("Attributes")
    sent = attributes.get("SentTimestamp") if isinstance(attributes, dict) else None
    try:
        return int(sent) >= started_ms
    except (TypeError, ValueError):
        return False


def _delete(receipts):
    """Deletes a group's messages in the batch size SQS accepts.

    A failed delete only means those events will be appended again next sweep, producing
    duplicate ids that a reader collapses — the events are already durable in S3. One event is
    emitted per group rather than per failed chunk, because a chunk is ten messages and a
    per-chunk emitter would scale with the message count on exactly the path where the queue is
    already unhappy.

    It is the count that matters to the caller, not just the log line. An undeleted message stays
    in flight and its group stays blocked, so the sweep's next receive can come back empty with
    the queue nowhere near drained — the same false reading a failed append produces, through the
    door that is more likely to open.

    Both halves of the response are read. ``DeleteMessageBatch`` reports a partial failure as
    **HTTP 200 with a ``Failed`` array**, so a try/except sees nothing at all on the most likely
    real fault; the same shape was closed on ``delete_objects``, and this had it too.

    Args:
      receipts: The receipt handles to delete.

    Returns:
      The number of messages still in flight, and so still blocking their group — a message
      genuinely back on the queue blocks nothing.

    Raises:
      None.
    """
    sqs = clients.sqs()
    undeleted = 0
    for i in range(0, len(receipts), 10):
        chunk = receipts[i : i + 10]
        try:
            response = sqs.delete_message_batch(
                QueueUrl=LOGS_QUEUE_URL,
                Entries=[{"Id": str(n), "ReceiptHandle": r} for n, r in enumerate(chunk)],
            )
        except Exception:
            logger.exception("log-sweep: failed to delete %d messages", len(chunk))
            undeleted += len(chunk)
            continue
        rejected = len(response.get("Failed") or [])
        if rejected:
            logger.warning("log-sweep: the queue rejected %d delete(s)", rejected)
            undeleted += rejected
    if undeleted:
        observability.warning(
            "delete failed; events will be appended again next sweep",
            events=undeleted,
            lost=False,
        )
    return undeleted


@observability.traced("sweep")
def handler(event, context):
    """Drains the logs queue into the day's objects.

    The sweep instruments itself, which is what makes the pipe verifiable end to end without
    instrumenting a control plane. Its own events go through the same queue, and a later wave of
    the same invocation can receive them — the library sends every ten finished spans or every
    second, not only at the end — so the sweep partly drains itself, and while a session is
    active every wave finds what arrived during the one before. Waiting for an empty receive
    would therefore chase arrivals to the wave cap for as long as they kept landing in every
    wave, rewriting the day objects once a wave with no backlog behind them. So the sweep also
    finishes after the first wave that held only messages the queue stamped after the sweep
    began: the backlog it was started for has been taken, as far as a short poll can tell, and
    what arrives next waits one tick. Two kinds of wave keep it going instead: one holding a
    message it cannot date, and one whose receive stopped at a cap rather than an empty round,
    because SQS does not order messages across groups, so a full wave of new messages says
    nothing about what is still queued behind it. A legacy group keeps it going until the group
    is empty or the cap or the clock stops it, since a group never yields a new message ahead of
    an older one of its own.

    That self-reference is also why the emitters are placed the way they are. No emitter is per
    message: this function emits into the queue it drains, so an event per message consumed
    would mean draining a batch produced about as many more, and the queue would have a floor it
    could never get below — permanently busy carrying its own telemetry, with the day objects
    growing to match.

    What bounds the volume is a ratio rather than a constant, and the wave loop is why. The
    receive and the per-destination events fire once per wave and once per (wave, day-group) —
    three, plus four per day-group — so a sweep's events grow with the work it does. The ratio
    has to hold in every message group that output lands in, not merely across the queue:
    grouped by service, all of it landed in one group that gave up ten a wave, and a wave
    touching two day-groups put eleven back, so that group grew whenever another was behind.
    Grouped per event, the output drains alongside everything else and the queue-wide ratio is
    the one that governs. The summary below is the only part aggregated to one event per sweep,
    because it is the only part genuinely per sweep. The property to preserve when adding an
    emitter here is the ratio, not a count.

    The plain logging calls stay alongside the structured events deliberately, and this is the
    one function where that is not duplication to copy into a verb. The sink is the queue only,
    so a sweep that cannot write to S3 cannot report through the structured store that it could
    not write to S3 — the mechanism that would carry the report is the thing that failed. Its
    CloudWatch line is the only account of that failure that exists.

    Messages are deleted strictly after a successful append. The resulting guarantee is
    at-least-once: a sweep that writes and then dies before deleting will append those events
    again next round, producing duplicate ids that a reader collapses on. Losing logs is worse
    than duplicating them. Unrouted bodies are counted but never recorded in an event — they are
    already preserved verbatim in their own partition, and echoing unbounded queue input into a
    day object risks precisely the growth this design is careful about.

    The summary's level carries the outcome, so a partly-failed sweep is reachable without
    reading a field: an earlier version reported the counts and no failure count at all, so a
    sweep that wrote two destinations of three read as a success in every field it had.

    Args:
      event: Ignored; the schedule carries no payload.
      context: The Lambda context, unused.

    Returns:
      A dict of the messages swept and events written, plus the day-groups touched and the waves
      run when there was anything to sweep. The two early returns — not configured, and nothing
      on the queue — report zeroes and omit the group and wave counts.

    Raises:
      None. Total by design: no message can make this raise.
    """
    global _sweep_id
    _sweep_id = sweep_id = uuid.uuid4().hex
    started_ms = time.time_ns() // 1_000_000
    observability.stamp(sweep_id=sweep_id)

    if not LOGS_QUEUE_URL or not ADMIN_BUCKET:
        logger.warning("log-sweep: LOGS_QUEUE_URL or ADMIN_BUCKET unset — nothing to do")
        observability.warning(
            "not configured",
            has_queue=bool(LOGS_QUEUE_URL),
            has_bucket=bool(ADMIN_BUCKET),
        )
        return {"swept": 0, "written": 0}

    swept = 0
    written = 0
    failed = 0
    undated = 0
    unrouted = 0
    waves = 0
    capped = False
    stuck = 0
    stop_reason = ""
    touched = set()

    while True:
        if waves and _time_is_short(context):
            stop_reason = STOP_TIME_RESERVE
            break
        if waves >= MAX_WAVES:
            stop_reason = STOP_WAVE_CAP
            break
        messages, truncated = _receive_all()
        if not messages:
            break
        waves += 1
        swept += len(messages)
        capped = capped or truncated

        groups = defaultdict(list)
        for message in messages:
            body = message.get("Body", "")
            service, parsed = _route(body)
            year, month, day, fell_back = _partition(parsed)
            undated += 1 if fell_back else 0
            unrouted += 1 if service == UNROUTED else 0
            groups[(service, year, month, day)].append(
                (body, message.get("ReceiptHandle", ""))
            )

        observability.info("received", messages=len(messages), groups=len(groups))

        for (service, year, month, day), items in sorted(groups.items()):
            key = _day_key(service, year, month, day)
            touched.add(key)
            if _append_day(key, [b for b, _ in items]):
                written += len(items)
                stuck += _delete([r for _, r in items if r])
            else:
                failed += len(items)

        if not truncated and all(_sent_since(m, started_ms) for m in messages):
            break

    if not stop_reason and (failed or stuck):
        stop_reason = STOP_GROUP_BLOCKED

    if not swept:
        return {"swept": 0, "written": 0}

    if capped:
        logger.warning(
            "log-sweep: a wave filled its %d-message cap; %d message(s) over %d wave(s)",
            MAX_MESSAGES,
            swept,
            waves,
        )
        observability.warning(
            "a wave filled the message cap", limit=MAX_MESSAGES, taken=swept, waves=waves
        )
    if stop_reason:
        logger.warning(
            "log-sweep: stopped on %s; %d message(s) over %d wave(s), the queue may still be "
            "yielding",
            stop_reason,
            swept,
            waves,
        )
        observability.warning(
            "stopped with the queue possibly still yielding",
            reason=stop_reason,
            taken=swept,
            waves=waves,
            limit=MAX_WAVES,
        )
    if undated:
        logger.warning("log-sweep: %d event(s) had no usable timestamp; used the sweep clock", undated)
        observability.warning("events had no usable timestamp", undated=undated)
    if unrouted:
        observability.warning("bodies could not be routed", unrouted=unrouted)

    logger.info(
        "log-sweep %s: %d message(s) in %d day-group(s) over %d wave(s), %d written",
        sweep_id,
        swept,
        len(touched),
        waves,
        written,
    )
    outcome = observability.error if failed else observability.info
    outcome(
        "swept",
        messages=swept,
        groups=len(touched),
        waves=waves,
        written=written,
        failed=failed,
    )
    return {"swept": swept, "written": written, "groups": len(touched), "waves": waves}
