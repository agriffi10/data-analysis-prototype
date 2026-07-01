"""validate-authorize — the Step Function's first task (SPEC-056; SPEC-062).

One task, run once before any verb: parse the SQS record, verify the caller's
Cognito ID token, derive the trusted ``actor``, load the registry, and authorize the
action. A failed check raises AuthorizationError, so the state machine's Catch routes
to Fail and no verb runs.

Mostly read-only, with ONE deliberate side effect for ``create``: immediately after
the token is verified (so the target prefix comes from the trusted ``actor``, never
the spoofable body actor), it durably records the new space as ``provisioning`` in the
creator's per-user cache and emits a "creating…" notification. This is the earliest
safe point, so the space is recorded even if a downstream step (routing / create-space)
fails — the browser reads only that cache, so an unrecorded create vanishes on reload.
Both are best-effort: a failure here must never block the create (create-space writes
the authoritative ``active``/``failed`` entry + notification at the end).

Outputs the small validated context the Choice state routes on and the verb consumes:
``{action, actor, space, payload, registry, requestId}`` (the verb trusts this and
never re-verifies the token or re-authorizes).
"""

import json
import logging

import config
import auth
import cache
import registry as reg
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _record_pending_create(actor, space, request_id):
    """Durably record a just-accepted create as ``provisioning`` (+ a "creating…"
    notification) as the first side effect, right after the token is verified. Fully
    best-effort — any failure is logged and swallowed so it can never block the create;
    the authoritative ``active``/``failed`` write happens in create-space at the end."""
    try:
        cache.write_owner_pending(actor, space)
    except Exception:  # noqa: BLE001 - never block the create on a cache write
        logger.warning("pending cache write failed for %s/%s", actor, space, exc_info=True)
    emit_notification(
        actor,
        f'Creating shared workspace "{space}"…',
        dedup_id=f"{request_id}:create-pending:{actor}",
    )


def _extract_record(event):
    if isinstance(event, list):
        if not event:
            raise auth.AuthorizationError("empty event")
        return event[0]
    if isinstance(event, dict):
        return event
    raise auth.AuthorizationError("unrecognised event shape")


def _parse_request(record):
    body = record.get("body") if isinstance(record, dict) else None
    if not body:
        raise auth.AuthorizationError("missing message body")
    try:
        req = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise auth.AuthorizationError(f"body is not valid JSON: {exc}") from exc
    if req.get("schemaVersion") != config.SCHEMA_VERSION:
        raise auth.AuthorizationError(f"unsupported schemaVersion: {req.get('schemaVersion')!r}")
    return req


def handler(event, context):
    record = _extract_record(event)
    req = _parse_request(record)
    action = req.get("action")
    space = req.get("space")

    # Trusted-actor binding: derive the actor from the verified token, not the body.
    actor = auth.verified_username(req.get("idToken"))

    # First side effect for create: record the space as `provisioning` (+ notify) now
    # that we have the trusted actor, so it survives a reload even if a later step fails.
    if action == "create":
        _record_pending_create(actor, space, req.get("requestId"))

    # Authorize against the registry (raises -> Catch -> Fail, no verb runs).
    registry_doc = None if action == "create" else reg.load(space)
    auth.authorize(action, space, actor, registry_doc)

    validated = {
        "action": action,
        "actor": actor,
        "space": space,
        "payload": req.get("payload") or {},
        "registry": registry_doc,
        "requestId": req.get("requestId"),
    }
    logger.info("validated %s on %s by %s", action, space, actor)
    return validated
