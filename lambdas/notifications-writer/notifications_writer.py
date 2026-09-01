"""Notifications writer — the single writer of each user's notifications inbox.

The notifications FIFO queue triggers this Lambda directly with a batch size of one, so each
invocation carries exactly one action-discriminated envelope. The handler read-modify-writes
the user's inbox object and is the only writer of it; per-user serialization comes from the
FIFO message group plus that batch size. There is no delete — notifications are only ever
marked read.

Actor binding differs by action. The user-originated actions carry the caller's Cognito ID
token and the target is the verified username claim, so any body username is ignored. Creation
is trusted-producer-only and uses the body username, which is correct because a plane notifying
a recipient holds no token for the person it is telling. A schema-invalid or unauthorized
message raises, so the record retries and then lands in the dead-letter queue — never a partial
write.

What makes trusted-producer-only true of the running system is a check here, not the IAM
policy. The portal role's grant on this queue is unconditioned and cannot be otherwise: no SQS
condition key reaches a field inside a message body, so a policy could only deny the browser
``SendMessage`` outright — the same principal on the same action the user actions need. So the
handler compares the ``SenderId`` SQS stamps on every message, which a ``SendMessage`` cannot
set, and refuses a ``create`` that came from browser credentials. A refusal LOGS AND DROPS
rather than raising: raising would cost three invocations and one permanent dead-letter message
per forged request, on the queue whose dead-letter queue is deliberately undrained, which would
hand every signed-in user a way to drown the only operator-facing signal this plane has.

That boundary is narrower than it looks and the limit is worth knowing: a body that is not
valid JSON, or that names an unknown action, still raises from ``_parse_record`` before any of
this runs. This decides who may send a ``create``, not who may reach the queue.

This is the delivery channel for every failure notification in the system, and its dead-letter
queue is deliberately left undrained: draining it would ask the queue that just failed to
deliver to deliver the news about itself. A message that dies here dies silently by design, so
these events are the only account of it that exists.

**Nothing here verifies anything any more, and the two branches were never symmetric.** A user
action carries the API's verified identity block, which ``cpcommon.actor`` reads; the exception
type is the one thing that does not come from the layer, because this handler's SQS
retry-into-DLQ contract is expressed in ``AuthorizationError``.

The ``create`` branch is the trusted-producer path and has never had an actor to establish. It
is written by the control-plane execution roles, never by a browser and never through the API,
and it carries its target ``username`` in the body with no actor and no token — which is why the
reader is called INSIDE the user-action arm and not above the branch. Hoisted, it would refuse
every notification the fleet produces, and it would do it silently: the producers notify
best-effort, so archives and shares would complete and users would simply never be told. Whether
that producer is entitled to be one is a separate question, answered before this by the sender
check in ``process``.

The 46 ms of cold start PyJWT used to cost on both paths is gone with the verifier.

Attributes:
  VALID_ACTIONS: The three actions an envelope may carry.
  USER_ACTIONS: The subset carrying a verified actor. Their complement is ``create``, the
    trusted-producer path, which carries a body username instead.
  USER_SPACE_BUCKET: Set by Terraform.
  NOTIFICATIONS_MAX: Inbox cap, set by Terraform.
  MAX_PAYLOAD_BYTES: Ceiling on one create's serialised ``payload``, enforced here because this
    is the only server-side gate the field will ever have. A producer's own bound is a design
    budget in its own layer and constrains nothing that arrives at this queue — the grant on it
    is unconditioned, and while the sender check above now bounds WHO reaches this function, IAM
    still bounds nobody. Oversize is REFUSED rather than truncated — a truncated structured field
    is a half-object a reader has to defend against, where a refusal dead-letters the one message
    and leaves every other row untouched.
  UNTRUSTED_SENDER_ID: The IAM unique ID of the role the browser assumes, set by Terraform. Empty
    means the check cannot run, and every ``create`` is refused rather than passed.
  CREATE_REFUSAL_*: The three reason codes a refused ``create`` is logged under. They are three
    rather than two because an unset ``UNTRUSTED_SENDER_ID`` is a state neither of the others
    describes — the deploy is broken, not the record and not an attacker — and one code for two
    opposite operational conditions is one log line that cannot tell them apart.
"""

import json
import logging
import os
import time
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from cpcommon import actor as cpactor
from cpcommon import clients, events, observability

observability.init(service="notifications")

VALID_ACTIONS = frozenset({"create", "markRead", "markAllRead"})
USER_ACTIONS = frozenset({"markRead", "markAllRead"})

USER_SPACE_BUCKET = os.environ.get("USER_SPACE_BUCKET", "")
NOTIFICATIONS_MAX = int(os.environ.get("NOTIFICATIONS_MAX", "200"))

MAX_PAYLOAD_BYTES = 16 * 1024

UNTRUSTED_SENDER_ID = os.environ.get("NOTIFICATIONS_UNTRUSTED_SENDER_ID", "")

CREATE_REFUSAL_UNTRUSTED = "untrusted-sender"
CREATE_REFUSAL_NO_SENDER = "sender-id-absent"
CREATE_REFUSAL_UNCONFIGURED = "sender-check-unconfigured"


class ValidationError(Exception):
    """A schema-invalid message. Raising retries the record into the DLQ with no write."""


class AuthorizationError(Exception):
    """A missing or invalid token on a user-originated action. Raising retries into the DLQ."""


def _now_iso():
    """Returns the current time in ISO-8601 UTC with millisecond precision.

    Matches the wire contract's example format.

    Args:
      None.

    Returns:
      The timestamp string.

    Raises:
      None.
    """
    now = time.time()
    base = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now))
    return f"{base}.{int((now % 1) * 1000):03d}Z"


def _inbox_key(username):
    """Builds the S3 key of one user's inbox object.

    Args:
      username: The inbox owner.

    Returns:
      The object key under their own prefix.

    Raises:
      None.
    """
    return f"{username}/user_settings/notifications.json"


def load_inbox(username):
    """Reads a user's notifications list.

    A missing or corrupt object is treated as an empty list rather than an error that would
    block a create.

    Args:
      username: The inbox owner.

    Returns:
      The notifications, or an empty list.

    Raises:
      ClientError: On any S3 fault other than a missing key.
    """
    s3 = clients.s3()
    try:
        obj = s3.get_object(Bucket=USER_SPACE_BUCKET, Key=_inbox_key(username))
    except s3.exceptions.NoSuchKey:
        return []
    try:
        doc = json.loads(obj["Body"].read())
    except (TypeError, ValueError):
        logger.warning("corrupt notifications.json for %s; treating as empty", username)
        return []
    return doc if isinstance(doc, list) else []


def save_inbox(username, notifications):
    """Caps the inbox to the most recent notifications and writes the whole document.

    One put, never an S3 delete.

    Args:
      username: The inbox owner.
      notifications: The full list to write.

    Returns:
      The capped list as written.

    Raises:
      ClientError: On any S3 write fault.
    """
    capped = sorted(notifications, key=lambda n: n.get("timestamp", ""), reverse=True)[
        :NOTIFICATIONS_MAX
    ]
    clients.s3().put_object(
        Bucket=USER_SPACE_BUCKET,
        Key=_inbox_key(username),
        Body=json.dumps(capped).encode(),
        ContentType="application/json",
    )
    return capped


def apply_create(notifications, message, link=None, payload=None):
    """Prepends a new unread notification with a server-assigned id and timestamp.

    The link is written only when a producer supplies a non-empty string, so every existing
    producer keeps writing byte-identical records and every notification already in a user's
    inbox stays valid. Its value is not validated here: the browser decides whether a link is
    safe to turn into an anchor, because that is where it becomes one, and a second opinion in
    this Lambda could only disagree with the one that actually matters.

    **The payload is the same shape of optional field and is written on the same terms**, so a
    producer that supplies none — six of the seven planes — still writes the four keys it always
    wrote. What differs is that a payload is a structured object of the producer's own choosing
    rather than one bounded string, so its SIZE is checked. Its CONTENTS are not: the browser
    rebuilds the row field by field, which is where a shape decision belongs.

    Args:
      notifications: The current list.
      message: The rendered notification body.
      link: Optional in-app path.
      payload: Optional structured object a producer attaches for a reader that knows its shape.

    Returns:
      A new list with the notification at the front.

    Raises:
      ValidationError: When a payload is present and serialises to more than ``MAX_PAYLOAD_BYTES``.
        Raising dead-letters this one message rather than writing an unbounded object into an
        inbox every poll then downloads whole.
    """
    notification = {
        "id": uuid.uuid4().hex,
        "message": message,
        "read": False,
        "timestamp": _now_iso(),
    }
    if isinstance(link, str) and link:
        notification["link"] = link
    if isinstance(payload, dict) and payload:
        size = len(json.dumps(payload).encode())
        if size > MAX_PAYLOAD_BYTES:
            raise ValidationError(
                f"payload is {size} bytes, over the {MAX_PAYLOAD_BYTES}-byte limit"
            )
        notification["payload"] = payload
    return [notification, *notifications]


def apply_mark_read(notifications, notification_id):
    """Marks the matching notification read and reports how many matched.

    An id that matches nothing is not an error — the inbox is capped, so a genuinely old
    notification can age out between the browser reading it and the click landing. But it is
    the one way a mark-read can complete, write and report success while changing nothing, so
    the count is returned rather than letting the two outcomes look identical in the logs.

    Args:
      notifications: The current list, mutated in place.
      notification_id: The id to mark read.

    Returns:
      A ``(notifications, matched count)`` tuple.

    Raises:
      None.
    """
    matched = 0
    for note in notifications:
        if note.get("id") == notification_id:
            note["read"] = True
            matched += 1
    return notifications, matched


def apply_mark_all_read(notifications):
    """Marks every notification read.

    Args:
      notifications: The current list, mutated in place.

    Returns:
      The same list.

    Raises:
      None.
    """
    for note in notifications:
        note["read"] = True
    return notifications


def _parse_record(record):
    """Parses and shape-checks one SQS record's body.

    Args:
      record: The SQS record.

    Returns:
      The parsed request dict.

    Raises:
      ValidationError: On a missing body, a body that is not valid JSON, a body that is not an
        object, or an unknown action.
    """
    body = record.get("body") if isinstance(record, dict) else None
    if not body:
        raise ValidationError("missing message body")
    try:
        req = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"body is not valid JSON: {exc}") from exc
    if not isinstance(req, dict):
        raise ValidationError("message body is not an object")
    action = req.get("action")
    if action not in VALID_ACTIONS:
        raise ValidationError(f"unknown action: {action!r}")
    return req


def sender_id(record):
    """Reads the sender identity SQS stamped on one record.

    A thin name over ``cpcommon.events.sender_id``, kept because this module's call sites and its
    suite both name it. The reader moved to the shared layer when a second control-plane boundary
    came to need it: what it extracts is the SQS record's shape, which is not this domain's to
    own, while the decision below — which senders are refused — is.

    Args:
      record: The SQS record.

    Returns:
      The stamped value, or an empty string when the record carries no usable one.

    Raises:
      None.
    """
    return events.sender_id(record)


def _create_sender_refusal(sender):
    """Decides whether a create's sender may write to somebody else's inbox.

    For a role, ``SenderId`` is the role's unique ID, a colon, and a session name. Only the
    role-id half is compared. The session half is never examined: Cognito's enhanced flow does
    not document what it sets there, so pinning a literal would couple this boundary to an
    undocumented value. The comparison is equality on that half rather than a prefix test —
    a prefix would also match a different role whose unique ID merely starts the same way.

    Order is load-bearing, not stylistic, and the two guards carry different halves of it. The
    empty role-id half is refused BEFORE the comparison, so an absent sender can never compare
    equal to an unset variable and be recorded as a forgery. The configuration is then tested
    FIRST so that an unset variable reports itself in every case, including an absent sender —
    tested last, that case would come back ``sender-id-absent`` and describe a broken message
    where the truth is a broken deploy, which is the one distinction these codes exist to make.

    Args:
      sender: The stamped sender, empty when the record carried none.

    Returns:
      A reason code, or an empty string when the create may proceed.

    Raises:
      None.
    """
    if not UNTRUSTED_SENDER_ID:
        return CREATE_REFUSAL_UNCONFIGURED
    role_id = sender.split(":", 1)[0]
    if not role_id:
        return CREATE_REFUSAL_NO_SENDER
    if role_id == UNTRUSTED_SENDER_ID:
        return CREATE_REFUSAL_UNTRUSTED
    return ""


def _resolve_username(req):
    """Derives the target username for a request.

    User-originated actions require the API's identity block and ignore any body username; creation is
    a trusted producer and uses the body username.

    Whether that producer IS trusted is decided before this function, by the sender check in
    ``process``. It sits above this call rather than inside the create branch on purpose: this
    runs before any branch, so a guard placed lower would let a refused create with no
    ``username`` raise from here and dead-letter — which is the outcome the refusal exists to
    avoid.

    Args:
      req: The parsed request.

    Returns:
      The target username.

    Raises:
      AuthorizationError: When a user-originated action's token cannot be verified.
      ValidationError: When a create carries no username.
    """
    action = req["action"]
    if action in USER_ACTIONS:
        return cpactor.trusted_actor(req, exc=AuthorizationError).username
    username = req.get("username")
    if not username or not isinstance(username, str):
        raise ValidationError("create requires a username")
    return username


def process(req, sender):
    """Validates the request, resolves the trusted target, and applies the read-modify-write.

    A refused create RETURNS rather than raising, because it is the most expected thing in this
    module and an expected refusal is a return value. The caller logs it and treats the message
    as handled, so the event-source mapping deletes it.

    Args:
      req: The parsed request.
      sender: The sender SQS stamped on the record, empty when it carried none.

    Returns:
      A small structured result for logging: the action, the username, the resulting count, and
      the match count for a mark-read. For a refused create, ``{"action", "refused"}`` and
      nothing else — no inbox was read or written, so there is no count to report.

    Raises:
      ValidationError: When a create has no message, a create's payload is oversize, or a
        mark-read has no id.
      AuthorizationError: When a user-originated action's token cannot be verified.
      ClientError: On any S3 fault.
    """
    action = req["action"]
    if action == "create":
        refusal = _create_sender_refusal(sender)
        if refusal:
            return {"action": action, "refused": refusal}
    username = _resolve_username(req)
    matched = None

    if action == "create":
        message = req.get("message")
        if not message or not isinstance(message, str):
            raise ValidationError("create requires a message")
        updated = apply_create(
            load_inbox(username), message, req.get("link"), req.get("payload")
        )
    elif action == "markRead":
        notification_id = req.get("id")
        if not notification_id or not isinstance(notification_id, str):
            raise ValidationError("markRead requires an id")
        updated, matched = apply_mark_read(load_inbox(username), notification_id)
    else:
        updated = apply_mark_all_read(load_inbox(username))

    saved = save_inbox(username, updated)
    result = {"action": action, "username": username, "count": len(saved)}
    if matched is not None:
        result["matched"] = matched
    return result


@observability.traced("write")
def handler(event, context):
    """SQS event-source-mapping entry point, one record per invocation.

    The single-record assumption is code and infrastructure coupling: it holds only because the
    Terraform sets a batch size of one, and raising that is a one-line edit. This used to take
    the first record and discard the rest, so the edit would have silently dropped every
    notification but the first. It now raises instead, and a test pins the Terraform value.
    Raising rather than looping is deliberate: the single-writer model serialises one user's
    inbox per invocation, so a batch is a design change to be made on purpose, not absorbed
    quietly.

    Be clear about where that raise goes. Unlike the four control-plane request queues, this
    dead-letter queue is deliberately undrained, because the drain's only delivery channel is
    this very queue. So the raise does not become a user notification: it fails the invocation,
    retries to the receive limit, and the batch sits in the DLQ until its retention expires. The
    signal is operator-facing — the function's invocation-error metric and the waiting messages —
    which is what a batch-size edit deserves, and strictly better than delivering one of many.
    The real guard is the test that stops the edit reaching production at all.

    A mark-read that matched nothing wrote the inbox back unchanged. That is not a failure, but
    it is the signature of "mark as read did nothing", so it gets its own event rather than
    hiding inside an indistinguishable success.

    A refused create returns here rather than raising, and this event is the ONLY account of it
    that exists — dropping is what keeps a forged request from accumulating in an undrained
    dead-letter queue, and the cost of that is that nothing accumulates to notice. The event
    carries the reason code and the ``messageId``, both service-stamped, and nothing from the
    body: the body is the untrusted thing this refusal exists over, and echoing it would make an
    operator's log the injection channel the inbox no longer is.

    Args:
      event: The SQS event.
      context: The Lambda context, unused.

    Returns:
      The structured result from processing the record, including a refused create's.

    Raises:
      ValidationError: When the event carries no records, more than one record, or the record
        fails validation. No partial write occurs.
      AuthorizationError: When a user-originated action's token cannot be verified.
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
            "the notifications event-source mapping must keep batch_size = 1"
        )
    record = records[0]
    req = _parse_record(record)
    result = process(req, sender_id(record))
    if "refused" in result:
        observability.error(
            "create refused",
            reason=result["refused"],
            message_id=record.get("messageId", ""),
        )
        return result
    logger.info("notifications %(action)s for %(username)s -> %(count)d", result)
    if result.get("matched") == 0:
        observability.warning(
            "markRead matched no notification",
            recipient=result.get("username"),
            notifications=result.get("count"),
        )
    observability.info(
        "notification written",
        action=result.get("action"),
        recipient=result.get("username"),
        notifications=result.get("count"),
        matched=result.get("matched"),
    )
    return result
