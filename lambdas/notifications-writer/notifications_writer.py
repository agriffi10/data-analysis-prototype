"""Notifications writer — the single writer of each user's notifications inbox.

The notifications FIFO queue triggers this Lambda directly with a batch size of one, so each
invocation carries exactly one action-discriminated envelope. The handler read-modify-writes
the user's inbox object and is the only writer of it; per-user serialization comes from the
FIFO message group plus that batch size. There is no delete — notifications are only ever
marked read.

Actor binding differs by action. The user-originated actions carry the caller's Cognito ID
token and the target is the verified username claim, so any body username is ignored. Creation
is trusted-producer-only, gated by send permission the portal role does not hold, and uses the
body username. A schema-invalid or unauthorized message raises, so the record retries and then
lands in the dead-letter queue — never a partial write.

This is the delivery channel for every failure notification in the system, and its dead-letter
queue is deliberately left undrained: draining it would ask the queue that just failed to
deliver to deliver the news about itself. A message that dies here dies silently by design, so
these events are the only account of it that exists.

Verification is ``cpcommon.auth``'s, not this module's. It used to be a second copy of the
issuer and JWKS URLs, the cached client and the claim checks, because the layer's config
required six environment variables at import and this function sets three — that read
made that config resolve lazily, which removed the reason for the copy. The exception type is
the one thing that does not come from the layer: this handler's SQS retry-into-DLQ contract is
expressed in ``AuthorizationError``, so the seam maps ``AuthError`` onto it.

That import costs about 46 ms of cold start (PyJWT pulls cryptography), and it is paid on the
``create`` path too — the trusted-producer path that carries every failure notification in the
system and verifies no token. Accepted: delivery is asynchronous, nothing user-facing waits on
it, and a deferred import would trade the duplication back for the saving.

Attributes:
  VALID_ACTIONS: The three actions an envelope may carry.
  USER_ACTIONS: The subset that requires a verified token.
  USER_SPACE_BUCKET: Set by Terraform.
  NOTIFICATIONS_MAX: Inbox cap, set by Terraform.
  MAX_PAYLOAD_BYTES: Ceiling on one create's serialised ``payload``, enforced here because this
    is the only server-side gate the field will ever have. A producer's own bound is a design
    budget in its own layer and constrains nothing that arrives at this queue: the portal role
    holds an unconditioned ``sqs:SendMessage`` on it. Oversize is REFUSED rather than truncated —
    a truncated structured field is a half-object a reader has to defend against, where a refusal
    dead-letters the one message and leaves every other row untouched.
"""

import json
import logging
import os
import time
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from cpcommon import auth, clients, observability
from cpcommon.errors import AuthError

observability.init(service="notifications")

VALID_ACTIONS = frozenset({"create", "markRead", "markAllRead"})
USER_ACTIONS = frozenset({"markRead", "markAllRead"})

USER_SPACE_BUCKET = os.environ.get("USER_SPACE_BUCKET", "")
NOTIFICATIONS_MAX = int(os.environ.get("NOTIFICATIONS_MAX", "200"))

MAX_PAYLOAD_BYTES = 16 * 1024


class ValidationError(Exception):
    """A schema-invalid message. Raising retries the record into the DLQ with no write."""


class AuthorizationError(Exception):
    """A missing or invalid token on a user-originated action. Raising retries into the DLQ."""


def verified_username(id_token):
    """Verifies a Cognito ID token and returns the trusted username claim.

    The fleet's one offline JWKS verification of issuer, audience, expiry and signature — the
    server-side, unspoofable username decision — wrapped only to carry this handler's
    exception type. Every rejection message is the layer's, unchanged.

    Args:
      id_token: The raw JWT.

    Returns:
      The verified ``cognito:username``.

    Raises:
      AuthorizationError: When the token is absent, fails any verification step, is not an ID
        token, or carries no username claim.
      RuntimeError: When ``COGNITO_USER_POOL_ID`` or ``COGNITO_APP_CLIENT_ID`` is unset. The
        local verifier read these with a default and degraded into a verification failure;
        the layer requires them and says which is missing, which is the better signal for a
        misconfigured function. Either way the invocation fails and the record dead-letters.
    """
    try:
        return auth.verify_id_token(id_token)["cognito:username"]
    except AuthError as exc:
        raise AuthorizationError(str(exc)) from exc


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


def _resolve_username(req):
    """Derives the target username for a request.

    User-originated actions require a verified token and ignore any body username; creation is
    a trusted producer and uses the body username.

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
        return verified_username(req.get("idToken"))
    username = req.get("username")
    if not username or not isinstance(username, str):
        raise ValidationError("create requires a username")
    return username


def process(req):
    """Validates the request, resolves the trusted target, and applies the read-modify-write.

    Args:
      req: The parsed request.

    Returns:
      A small structured result for logging: the action, the username, the resulting count, and
      the match count for a mark-read.

    Raises:
      ValidationError: When a create has no message, a create's payload is oversize, or a
        mark-read has no id.
      AuthorizationError: When a user-originated action's token cannot be verified.
      ClientError: On any S3 fault.
    """
    action = req["action"]
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

    Args:
      event: The SQS event.
      context: The Lambda context, unused.

    Returns:
      The structured result from processing the record.

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
    result = process(req)
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
