"""Notifications writer — the single writer of each user's notifications inbox.

The notifications FIFO queue triggers this Lambda directly (SQS event-source mapping,
batch size 1 — SPEC-058). Each invocation carries exactly one SQS record whose body is
an `action`-discriminated envelope (`create` | `markRead` | `markAllRead`). The handler
read-modify-writes the target user's inbox document at
``{username}/user_settings/notifications.json`` in the user-space bucket and is the ONLY
writer of that object, so two producers never race on it (per-user serialization comes
from FIFO: MessageGroupId = username + batch size 1).

There is NO delete/deleteAll — notifications are never removed, only marked read.

Actor binding (SPEC-058 FR-005): for user-originated actions (markRead/markAllRead) the
message carries the caller's Cognito ID token; we verify it against the pool JWKS and
derive the target ``username`` from the verified ``cognito:username`` claim — any body
``username`` is ignored for those actions. ``create`` is a trusted-producer action
(only identities granted sqs:SendMessage can enqueue it; the portal role is not) and
uses the body ``username``.

A schema-invalid or unauthorized message raises, so the SQS event-source mapping retries
it and, after the queue's maxReceiveCount, routes it to the DLQ — never a partial write.
"""

import json
import logging
import os
import time
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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

    Mirrors the shared-space provisioner's offline-JWKS verification (issuer, audience,
    expiry, signature) — the unspoofable server-side username decision (CLAUDE.md Auth).
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
    except Exception as exc:  # noqa: BLE001 - any verify failure = untrusted
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


# ── Storage I/O ───────────────────────────────────────────────────────────────
def _inbox_key(username):
    return f"{username}/user_settings/notifications.json"


def load_inbox(username):
    """Return the user's notifications list. A missing or corrupt object is treated as
    an empty array — never an error that would block a ``create`` (FR-004)."""
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
    """Cap to the most-recent NOTIFICATIONS_MAX by timestamp (newest kept) and write the
    whole document in one PutObject. Never an S3 delete (FR-002/FR-004)."""
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


# ── Actions (pure transforms over the inbox list) ─────────────────────────────
def apply_create(notifications, message):
    """Prepend a new notification with a server-assigned id/timestamp and read=false."""
    notification = {
        "id": uuid.uuid4().hex,
        "message": message,
        "read": False,
        "timestamp": _now_iso(),
    }
    return [notification, *notifications]


def apply_mark_read(notifications, notification_id):
    """Set read=true on the matching id (no-op if absent)."""
    for note in notifications:
        if note.get("id") == notification_id:
            note["read"] = True
    return notifications


def apply_mark_all_read(notifications):
    """Set read=true on every notification."""
    for note in notifications:
        note["read"] = True
    return notifications


# ── Parse + dispatch ──────────────────────────────────────────────────────────
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
    """Derive the target username. User-originated actions REQUIRE a verified token and
    ignore any body username; ``create`` is a trusted producer and uses the body
    username (FR-005)."""
    action = req["action"]
    if action in USER_ACTIONS:
        return verified_username(req.get("idToken"))
    username = req.get("username")
    if not username or not isinstance(username, str):
        raise ValidationError("create requires a username")
    return username


def process(req):
    """Validate the action's required fields, resolve the trusted target user, and apply
    the read-modify-write. Returns a small structured result for logging."""
    action = req["action"]
    username = _resolve_username(req)

    if action == "create":
        message = req.get("message")
        if not message or not isinstance(message, str):
            raise ValidationError("create requires a message")
        updated = apply_create(load_inbox(username), message)
    elif action == "markRead":
        notification_id = req.get("id")
        if not notification_id or not isinstance(notification_id, str):
            raise ValidationError("markRead requires an id")
        updated = apply_mark_read(load_inbox(username), notification_id)
    else:  # markAllRead
        updated = apply_mark_all_read(load_inbox(username))

    saved = save_inbox(username, updated)
    return {"action": action, "username": username, "count": len(saved)}


def handler(event, context):
    """SQS event-source-mapping entry point (batch size 1 → one record per invocation).
    A raised exception fails the invocation so the record retries then lands in the DLQ;
    no partial write occurs."""
    records = event.get("Records", []) if isinstance(event, dict) else []
    if not records:
        raise ValidationError("no SQS records in event")
    record = records[0]
    req = _parse_record(record)
    result = process(req)
    logger.info("notifications %(action)s for %(username)s -> %(count)d", result)
    return result
