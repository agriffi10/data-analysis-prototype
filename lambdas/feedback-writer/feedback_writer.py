"""Feedback writer — the single writer of each day's feedback document.

The feedback FIFO queue triggers this Lambda directly with a batch size of one, so each
invocation carries exactly one submission. The handler read-modify-writes that day's object under
the admin bucket and is the only writer of it. There is no state machine and no fan-out: a
one-task append does not get a control plane.

**Nothing here verifies anything, and nothing here needs to.** The API verified the caller, took
the username from the token's own claim, and is the only principal holding ``sqs:SendMessage`` on
this queue — the browser holds no grant on it at all, which is why a user cannot file feedback
attributed to somebody else. So this module reads ``record["body"]`` directly rather than through
``cpcommon.events.parse_sqs_request``: that helper's population is swept by
``lambdas/test_actor_fleet.py`` and obliges its members to resolve an actor through
``trusted_actor``, and this envelope carries no identity block to resolve one from. Reading the
body directly is the same shape ``notifications-writer`` uses, and it is a decision rather than an
omission.

**The day is decided by the SUBMISSION, never by this function's clock.** The key comes from the
event's own ``submittedAt``, which is also what the API derived the ``MessageGroupId`` from — so
every message destined for one day's object is already serialized behind the previous one, and the
object a submission lands in is the one it was filed under. A writer that stamped its own clock
would put a redelivered message in a different day from the one it was submitted on, which is
precisely the day somebody would be reading.

**An unreadable document is never overwritten.** The append parses what it read and raises on a
document it does not recognise, leaving the day's records intact for an operator to recover — the
same disposition an unreadable settings document has. Overwriting would turn one bad byte into a
silent, total loss of a day nobody is watching.

**The read is fail-safe rather than absence-discriminating.** Any read failure is reported as "no
object, no tag", which makes the following write create-only: a transient fault or a denial then
loses its precondition instead of overwriting a day that is really there. That is what lets this
role hold no ``s3:ListBucket`` on the admin bucket — absence is never claimed on the strength of a
``NoSuchKey`` this role could not be told about.

**The message text is never logged.** It is a user's own prose, it rides into a store with a far
wider read audience than this queue, and nothing an operator needs from these records requires it.
The events carry its LENGTH.

This queue's dead-letter queue is deliberately undrained — see ``dlq_drain.UNDRAINED_QUEUES``. The
drain names a recipient only from the identity block the API nests in a request, and this body
keeps its username at the top level instead, so draining it would mean teaching the drain a second
place to find one.

Attributes:
  ADMIN_BUCKET: Destination bucket, set by Terraform.
  FEEDBACK_PREFIX: Root prefix for the day-partitioned layout.
  DOCUMENT_VERSION: The document shape this writer creates and understands. A document declaring
    anything else is refused untouched rather than migrated in place by a function nobody is
    watching.
  SCHEMA_VERSION: The message shape the API sends. Recorded on each entry so a later reader can
    tell which producer wrote it.
  CATEGORIES: The categories a submission may carry. The API refuses anything else before the
    send; this is the guard for a message that reached the queue another way.
  ENTRY_FIELDS: The keys copied from a message onto a stored entry, in the order they are
    written. Derived from nothing else, so a field the API starts sending is not silently
    persisted until it is named here.
  REQUIRED_FIELDS: The keys a message must carry. ``route`` is absent from it deliberately: it is
    optional on the wire.
  MAX_CAS_ATTEMPTS: Conditional-write attempts on one day object before giving up.
    ``cpcommon.cas.MAX_ATTEMPTS`` — this loop is not a fourth copy of it.
  LARGE_OBJECT_WARN_BYTES: The size at which rewriting the day in full is worth knowing about.
    The document has no cap — the product declines a per-user quota — and the function reads it
    back, parses it, appends, re-serialises and encodes, so peak memory is several multiples of
    what is on the wire. Sized well under what the function's memory buys, because the failure it
    warns about is an OOM: a SIGKILL skips the span flush, so the one durable operator signal is
    absent for exactly that failure, and every later submission that day fails the same way into
    a dead-letter queue nobody drains. Log-sweep carries the same warning over the same shape.
"""

import json
import logging
import os
from datetime import UTC, datetime

from cpcommon import cas, clients, observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="feedback")

ADMIN_BUCKET = os.environ.get("ADMIN_BUCKET", "")

FEEDBACK_PREFIX = "feedback"
DOCUMENT_VERSION = 1
SCHEMA_VERSION = 1

CATEGORIES = frozenset({"bug", "idea", "question", "other"})

ENTRY_FIELDS = ("eventId", "username", "category", "message", "route", "submittedAt")
REQUIRED_FIELDS = ("eventId", "username", "category", "message", "submittedAt")

MAX_CAS_ATTEMPTS = cas.MAX_ATTEMPTS

LARGE_OBJECT_WARN_BYTES = 16 * 1024 * 1024


class ValidationError(Exception):
    """A schema-invalid message. Raising retries the record into the DLQ with no write."""


class CorruptDocumentError(Exception):
    """The day's object will not parse, so it is left exactly as it is.

    Its own type rather than a ``ValidationError``: one names a bad message and the other names a
    document already in the bucket, and an operator needs to know which of the two they are
    looking at before they touch anything.
    """


def _parse_record(record):
    """Parses and shape-checks one SQS record's body.

    Args:
      record: The SQS record.

    Returns:
      The parsed submission.

    Raises:
      ValidationError: On a missing body, a body that is not valid JSON, a body that is not an
        object, a missing or non-string required field, or a category outside the closed set.
    """
    body = record.get("body") if isinstance(record, dict) else None
    if not body:
        raise ValidationError("missing message body")
    try:
        event = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"body is not valid JSON: {exc}") from exc
    if not isinstance(event, dict):
        raise ValidationError("message body is not an object")

    for field in REQUIRED_FIELDS:
        value = event.get(field)
        if not isinstance(value, str) or not value:
            raise ValidationError(f"{field} is missing or not a non-empty string")
    if event["category"] not in CATEGORIES:
        raise ValidationError(f"unknown category: {event['category']!r}")
    return event


def submitted_day(submitted_at):
    """Resolves the UTC day one submission belongs to.

    Args:
      submitted_at: The API's ``submittedAt`` stamp.

    Returns:
      The submission's date in UTC.

    Raises:
      ValidationError: If the stamp cannot be parsed. Refused rather than defaulted to this
        function's own clock: a redelivered message would then land in a day it was not submitted
        on, and disagree with the ``MessageGroupId`` that serialized it.
    """
    try:
        parsed = datetime.fromisoformat(submitted_at)
    except ValueError as exc:
        raise ValidationError(f"submittedAt is not an ISO 8601 timestamp: {exc}") from exc
    if parsed.tzinfo is None:
        return parsed.date()
    return parsed.astimezone(UTC).date()


def day_key(day):
    """Builds the key of one day's feedback object.

    Args:
      day: The submission's UTC date.

    Returns:
      The object key.

    Raises:
      None.
    """
    return f"{FEEDBACK_PREFIX}/{day:%Y}/{day:%m}/{day:%d}.json"


def _entry(event):
    """Builds the stored entry for one submission.

    Args:
      event: The parsed submission.

    Returns:
      The entry, carrying only the declared fields and only those the message actually sent.

    Raises:
      None.
    """
    entry = {field: event[field] for field in ENTRY_FIELDS if field in event}
    entry["schemaVersion"] = event.get("schemaVersion", SCHEMA_VERSION)
    return entry


def _read(key):
    """Reads a day object's current contents and entity tag.

    A read failure is reported as absent with no tag, which makes the following write a
    create-only conditional — so a transient error or a denial can never cause a silent overwrite
    of a day's feedback. It fails the write instead, and the message redelivers.

    Args:
      key: The day object's key.

    Returns:
      A ``(raw bytes or None, etag or None)`` pair; both None when the object could not be read.

    Raises:
      None.
    """
    try:
        response = clients.s3().get_object(Bucket=ADMIN_BUCKET, Key=key)
        raw = response["Body"].read()
        if len(raw) > LARGE_OBJECT_WARN_BYTES:
            observability.warning("day object is large", key=key, bytes=len(raw))
            logger.warning(
                "feedback-writer: %s is %.1f MB; it is rewritten in full on every append",
                key,
                len(raw) / 1024 / 1024,
            )
        return raw, response.get("ETag")
    except Exception as err:  # noqa: BLE001
        logger.info("feedback-writer: no readable object at %s (%s); creating it", key, err)
        return None, None


def _document(raw, day):
    """Parses a day object, or builds an empty one when there is nothing there.

    Args:
      raw: The object's bytes, or None when it does not exist.
      day: The submission's UTC date, for a freshly-created document.

    Returns:
      The document to append to.

    Raises:
      CorruptDocumentError: If the bytes are not a JSON object of the version and shape this
        writer understands. Raised rather than replaced: the day's records are somebody's only
        copy, and a writer that recovers by overwriting loses them all to fix one.
    """
    if raw is None:
        return {"version": DOCUMENT_VERSION, "date": f"{day:%Y-%m-%d}", "entries": []}
    try:
        document = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise CorruptDocumentError(f"the day's object is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise CorruptDocumentError("the day's object is not a JSON object")
    if document.get("version") != DOCUMENT_VERSION:
        raise CorruptDocumentError(
            f"the day's object declares version {document.get('version')!r}, "
            f"not {DOCUMENT_VERSION}"
        )
    if not isinstance(document.get("entries"), list):
        raise CorruptDocumentError("the day's object carries no entries array")
    return document


def append(event):
    """Appends one submission to its day's object under a compare-and-swap loop.

    Re-reads and re-applies on a precondition failure rather than retrying the same write: the
    object changed underneath, so the new content has to be rebuilt on top of whatever the winner
    wrote. Exhaustion RAISES, so the message redelivers and eventually dead-letters — a submission
    dropped here would be gone with nothing recording that it ever arrived.

    ``skip_no_op=False`` matches the two sibling callers rather than resting on inequality. It
    changes nothing here — the loop compares the raw bytes it read against the dict this builds,
    so they can never be equal — and that is exactly why it is set explicitly: a caller whose
    read and apply types ever line up would otherwise stop writing silently.

    Args:
      event: The parsed submission.

    Returns:
      A ``(key, entry count)`` pair for the caller's log record.

    Raises:
      ValidationError: If the submission's timestamp cannot be resolved to a day.
      CorruptDocumentError: If the day's existing object will not parse.
      CasExhausted: If every attempt lost to a concurrent writer.
      ClientError: On any write fault that is not a precondition failure.
    """
    key = day_key(submitted_day(event["submittedAt"]))
    entry = _entry(event)

    def _read_day():
        """Reads the day object.

        Args:
          None.

        Returns:
          The ``(raw bytes or None, etag or None)`` pair.

        Raises:
          None.
        """
        return _read(key)

    def _apply(raw):
        """Appends the entry to the freshly-read document.

        Args:
          raw: The object's current bytes, or None when it does not exist.

        Returns:
          The full document to write.

        Raises:
          CorruptDocumentError: If the existing object will not parse.
        """
        document = _document(raw, submitted_day(event["submittedAt"]))
        document["entries"] = [*document["entries"], entry]
        return document

    def _write(document, etag):
        """Writes the day object conditionally on the tag it was read at.

        Args:
          document: The full document.
          etag: The tag to match, or None to write only if the object is absent.

        Returns:
          None.

        Raises:
          ClientError: On a precondition failure, so the loop can retry, or any other S3 fault.
        """
        kwargs = {
            "Bucket": ADMIN_BUCKET,
            "Key": key,
            "Body": json.dumps(document).encode("utf-8"),
            "ContentType": "application/json",
        }
        if etag is None:
            kwargs["IfNoneMatch"] = "*"
        else:
            kwargs["IfMatch"] = etag
        clients.s3().put_object(**kwargs)

    def _on_conflict(attempt):
        """Records one lost race.

        Args:
          attempt: The 1-based attempt that lost.

        Returns:
          None.

        Raises:
          None.
        """
        observability.warning(
            "day object changed under us",
            key=key,
            attempt=attempt,
            attempts=MAX_CAS_ATTEMPTS,
        )

    written = cas.cas_mutate(
        _read_day,
        _apply,
        _write,
        label=key,
        max_attempts=MAX_CAS_ATTEMPTS,
        on_conflict=_on_conflict,
        skip_no_op=False,
    )
    return key, len(written["entries"])


@observability.traced("write")
def handler(event, context):
    """SQS event-source-mapping entry point, one record per invocation.

    The single-record assumption is code and infrastructure coupling: it holds only because the
    Terraform sets a batch size of one, and raising that is a one-line edit. A batch is refused
    rather than absorbed — taking the first record and discarding the rest would drop every
    submission but one, silently, and a submission has no other copy anywhere.

    Nothing here is caught. Every failure this can meet — a malformed message, an unreadable day
    object, a lost CAS race, an S3 fault — redelivers and then dead-letters, which is the only
    honest outcome for a queue whose whole payload is something a person typed and expects to have
    reached us.

    Args:
      event: The SQS event.
      context: The Lambda context, unused.

    Returns:
      A small structured result: the key written and the resulting entry count.

    Raises:
      ValidationError: When the event carries no records, more than one record, or the record
        fails validation. No write occurs.
      CorruptDocumentError: When the day's existing object will not parse.
      CasExhausted: When every conditional-write attempt lost.
      ClientError: On any S3 fault.
    """
    records = event.get("Records", []) if isinstance(event, dict) else []
    if not records:
        observability.error("no SQS records in event", reason="malformed-event")
        raise ValidationError("no SQS records in event")
    if len(records) > 1:
        observability.error(
            "multi-record SQS event", reason="batch-size-drift", records=len(records)
        )
        raise ValidationError(
            f"expected one SQS record per invocation, got {len(records)} — "
            "the feedback event-source mapping must keep batch_size = 1"
        )

    submission = _parse_record(records[0])
    observability.stamp(
        event_id=submission["eventId"],
        category=submission["category"],
        message_chars=len(submission["message"]),
    )

    key, entries = append(submission)

    observability.info("feedback written", key=key, entries=entries)
    logger.info("feedback-writer: appended to %s (%d entries)", key, entries)
    return {"key": key, "entries": entries}
