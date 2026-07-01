"""validate-authorize — the Step Function's first task (SPEC-056; SPEC-062).

One task, run once before any verb: parse the SQS record, verify the caller's
Cognito ID token, derive the trusted ``actor``, load the registry, and authorize the
action. A failed check raises AuthorizationError, so the state machine's Catch routes
to Fail and no verb runs.

Mostly read-only, with ONE deliberate side effect for ``create``/``delete``: once the
token is verified (so the actor is the trusted claim, never the spoofable body actor)
AND the action is authorized, it durably records the in-flight state in the actor's
per-user cache (``provisioning`` for create, ``deleting`` for delete) and emits a start
notification. This is the earliest safe point, so the space shows a durable state even
if a downstream step (routing / the verb) fails — the browser reads only that cache, so
without it the row reconciles back to ``active`` (delete) or vanishes on reload (create).
Both are best-effort: a failure here must never block the action (the verb writes the
authoritative terminal state + notification at the end).

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


# The in-flight state + start-notification each accepted-and-authorized create/delete
# records in the actor's cache before the verb runs. (add/remove/leave write their own
# terminal state directly in the verb, so they have no separate "intent" row.)
_INTENT = {
    "create": (cache.write_owner_pending, 'Creating shared workspace "{space}"…', "create-pending"),
    "delete": (cache.write_owner_deleting, 'Deleting shared workspace "{space}"…', "delete-pending"),
}


def _record_intent(action, actor, space, request_id):
    """Durably record a just-accepted, authorized create/delete in the actor's cache
    (``provisioning``/``deleting``) + a start notification, as the first side effect once
    the token is verified and the action authorized — so the space shows a durable state
    instead of the browser's optimistic row reconciling back to ``active``. Fully
    best-effort: a cache-write failure is logged and swallowed (never blocks the action);
    the verb writes the authoritative terminal state (+ notification) at the end."""
    write, template, tag = _INTENT[action]
    try:
        write(actor, space)
    except Exception:  # noqa: BLE001 - never block the action on a cache write
        logger.warning("intent cache write failed for %s %s/%s", action, actor, space, exc_info=True)
    emit_notification(actor, template.format(space=space), dedup_id=f"{request_id}:{tag}:{actor}")


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

    # Authorize against the registry (raises -> Catch -> Fail, no verb runs).
    registry_doc = None if action == "create" else reg.load(space)
    auth.authorize(action, space, actor, registry_doc)

    # First side effect for create/delete: record the in-flight state (+ notify) in the
    # actor's cache now that the action is authorized, so the space shows a durable
    # provisioning/deleting state even if a later step fails (the browser reads only that
    # cache). Done AFTER authorize so an unauthorized request mutates nothing.
    if action in _INTENT:
        _record_intent(action, actor, space, req.get("requestId"))

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
