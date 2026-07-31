"""Notifications writer — the single writer of each user's notifications inbox.

The notifications FIFO queue triggers this Lambda directly (SQS event-source mapping,
batch size 1), so each invocation carries exactly one action-discriminated envelope
(``create`` | ``markRead`` | ``markAllRead``). The handler read-modify-writes
``{username}/user_settings/notifications.json`` in the user-space bucket and is the
ONLY writer of that object; per-user serialization comes from FIFO
MessageGroupId=username plus batch size 1. There is no delete — notifications are only
ever marked read.

Actor binding: markRead/markAllRead carry the caller's Cognito ID token, and the
target username is the verified ``cognito:username`` claim (any body ``username`` is
ignored). ``create`` is trusted-producer-only (gated by sqs:SendMessage; the portal
role has none) and uses the body ``username``. A schema-invalid or unauthorized
message raises, so the record retries and then lands in the DLQ — never a partial
write.
"""

import json
import logging
import os
import time
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)

from cpcommon import observability  # after the logger, before any handler

# THE DELIVERY CHANNEL FOR EVERY FAILURE NOTIFICATION IN THE SYSTEM, and the notifications DLQ
# is deliberately left undrained — draining it would ask the queue that just failed to deliver
# to deliver the news about itself (SPEC-126 FR-006). A message that dies here dies silently by
# design, so these events are the only account of it that exists.
observability.init(service="notifications")

VALID_ACTIONS = frozenset({"create", "markRead", "markAllRead"})
USER_ACTIONS = frozenset({"markRead", "markAllRead"})

# Set by Terraform (lambda.tf). AWS_REGION is provided by the Lambda runtime.
USER_SPACE_BUCKET = os.environ.get("USER_SPACE_BUCKET", "")
USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID", "")
NOTIFICATIONS_MAX = int(os.environ.get("NOTIFICATIONS_MAX", "200"))
REGION = os.environ.get("AWS_REGION", "")

_ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"
_JWKS_URL = f"{_ISSUER}/.well-known/jwks.json"

# Lazily-initialised, cached across warm invocations. Module-level so tests patch them.
_s3 = None
_jwk_client = None


class ValidationError(Exception):
    """Schema-invalid message — raise so the record retries then lands in the DLQ; no write."""


class AuthorizationError(Exception):
    """Missing/invalid token on a user-originated action — raise -> retry -> DLQ; no write."""


def _s3c():
    global _s3
    if _s3 is None:
        import boto3

        _s3 = boto3.client("s3")
    return _s3


def _get_jwk_client():
    global _jwk_client
    if _jwk_client is None:
        from jwt import PyJWKClient

        _jwk_client = PyJWKClient(_JWKS_URL)
    return _jwk_client


def verified_username(id_token):
    """Verify a Cognito ID token and return the trusted ``cognito:username`` claim.

    Offline JWKS verification of issuer, audience, expiry, and signature — the
    server-side, unspoofable username decision.
    """
    import jwt

    if not id_token:
        raise AuthorizationError("missing idToken")
    try:
        signing_key = _get_jwk_client().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=APP_CLIENT_ID,
            issuer=_ISSUER,
            options={"require": ["exp", "iss", "aud"]},
        )
    except Exception as exc:  # any verify failure = untrusted
        raise AuthorizationError(f"token verification failed: {exc}") from exc

    if claims.get("token_use") != "id":
        raise AuthorizationError("not an ID token")
    username = claims.get("cognito:username")
    if not username:
        raise AuthorizationError("token missing cognito:username")
    return username


def _now_iso():
    """ISO-8601 UTC with millisecond precision, matching the wire contract example."""
    now = time.time()
    base = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now))
    return f"{base}.{int((now % 1) * 1000):03d}Z"


def _inbox_key(username):
    return f"{username}/user_settings/notifications.json"


def load_inbox(username):
    """Return the user's notifications list.

    A missing or corrupt object is treated as an empty array — never an error that
    would block a ``create``.
    """
    s3 = _s3c()
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
    """Cap to the most-recent NOTIFICATIONS_MAX by timestamp and write the whole document.

    One PutObject; never an S3 delete.
    """
    capped = sorted(notifications, key=lambda n: n.get("timestamp", ""), reverse=True)[
        :NOTIFICATIONS_MAX
    ]
    _s3c().put_object(
        Bucket=USER_SPACE_BUCKET,
        Key=_inbox_key(username),
        Body=json.dumps(capped).encode(),
        ContentType="application/json",
    )
    return capped


def apply_create(notifications, message, link=None):
    """Prepend a new notification with a server-assigned id/timestamp and read=false.

    ``link`` is a CONTRACT CHANGE TO A SHIPPED PIPELINE (SPEC-113 FR-008), which is why
    it is called out rather than assumed: the SPEC-058 record gains one optional field
    and nothing else. It is written only when a producer supplies a non-empty string, so
    every existing producer — table-builder, table-share, the shared-space verbs — keeps
    writing byte-identical records, and every notification already in a user's inbox
    stays valid.

    The value is NOT validated here. The browser decides whether a link is safe to turn
    into an anchor (``isSafeInAppPath``), because that is where it becomes one; a second
    opinion in this Lambda could only disagree with the one that actually matters.
    """
    notification = {
        "id": uuid.uuid4().hex,
        "message": message,
        "read": False,
        "timestamp": _now_iso(),
    }
    if isinstance(link, str) and link:
        notification["link"] = link
    return [notification, *notifications]


def apply_mark_read(notifications, notification_id):
    """Set read=true on the matching id; returns ``(notifications, matched)``.

    An id that matches nothing is NOT an error — the inbox is capped, so a genuinely
    old notification can age out between the browser reading it and the click landing.
    But it is the one way a markRead can complete, write, and report success while
    changing nothing, so the caller reports ``matched`` rather than letting the two
    outcomes look identical in the logs.
    """
    matched = 0
    for note in notifications:
        if note.get("id") == notification_id:
            note["read"] = True
            matched += 1
    return notifications, matched


def apply_mark_all_read(notifications):
    """Set read=true on every notification."""
    for note in notifications:
        note["read"] = True
    return notifications


def _parse_record(record):
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
    """Derive the target username.

    User-originated actions REQUIRE a verified token and ignore any body username;
    ``create`` is a trusted producer and uses the body username.
    """
    action = req["action"]
    if action in USER_ACTIONS:
        return verified_username(req.get("idToken"))
    username = req.get("username")
    if not username or not isinstance(username, str):
        raise ValidationError("create requires a username")
    return username


def process(req):
    """Validate the request, resolve the trusted target user, apply the read-modify-write.

    Returns:
        A small structured result for logging.
    """
    action = req["action"]
    username = _resolve_username(req)
    matched = None

    if action == "create":
        message = req.get("message")
        if not message or not isinstance(message, str):
            raise ValidationError("create requires a message")
        updated = apply_create(load_inbox(username), message, req.get("link"))
    elif action == "markRead":
        notification_id = req.get("id")
        if not notification_id or not isinstance(notification_id, str):
            raise ValidationError("markRead requires an id")
        updated, matched = apply_mark_read(load_inbox(username), notification_id)
    else:  # markAllRead
        updated = apply_mark_all_read(load_inbox(username))

    saved = save_inbox(username, updated)
    result = {"action": action, "username": username, "count": len(saved)}
    if matched is not None:
        result["matched"] = matched
    return result


@observability.traced("write")
def handler(event, context):
    """SQS event-source-mapping entry point (batch size 1 → one record per invocation).

    A raised exception fails the invocation so the record retries then lands in the
    DLQ; no partial write occurs.
    """
    records = event.get("Records", []) if isinstance(event, dict) else []
    if not records:
        observability.error("no SQS records in event", reason="malformed-event")
        raise ValidationError("no SQS records in event")
    record = records[0]
    req = _parse_record(record)
    result = process(req)
    logger.info("notifications %(action)s for %(username)s -> %(count)d", result)
    # A markRead that matched nothing wrote the inbox back unchanged. It is not a failure
    # (see apply_mark_read), but it is the signature of "mark as read did nothing", so it
    # gets its own event rather than hiding inside an indistinguishable success.
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
