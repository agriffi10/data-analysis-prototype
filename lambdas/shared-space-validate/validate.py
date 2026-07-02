"""validate-authorize — the Step Function's first task, run once before any verb.

Parses the SQS record, verifies the caller's Cognito ID token, derives the trusted
``actor`` (never the spoofable body actor), loads the registry, and authorizes the
action; a failed check raises AuthorizationError so the Catch routes to Fail and no
verb runs. For an authorized ``create``/``delete`` it also durably records the
in-flight state (``provisioning``/``deleting``) in the actor's per-user cache and
emits a start notification — the browser reads only that cache, so without it the row
reconciles back to ``active`` or vanishes on reload. Outputs the validated context
``{action, actor, space, payload, registry, requestId}`` that the Choice state routes
on; verbs trust it and never re-verify the token or re-authorize.
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


# Only create/delete record an in-flight intent before the verb runs; the other verbs
# write their terminal cache state directly, so they have no separate intent row.
_INTENT = {
    "create": (cache.write_owner_pending, 'Creating shared workspace "{space}"…', "create-pending"),
    "delete": (cache.write_owner_deleting, 'Deleting shared workspace "{space}"…', "delete-pending"),
}


def _record_intent(action, actor, space, request_id):
    """Record an authorized create/delete as in-flight in the actor's cache and notify.

    Best-effort: a cache-write failure is logged and swallowed (it must never block the
    action); the verb writes the authoritative terminal state at the end.
    """
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
    """Validate and authorize the queued request; return the context the verbs consume."""
    record = _extract_record(event)
    req = _parse_request(record)
    action = req.get("action")
    space = req.get("space")

    # Trusted-actor binding: derive the actor from the verified token, not the body.
    actor = auth.verified_username(req.get("idToken"))

    # Authorize against the registry (raises -> Catch -> Fail, no verb runs).
    registry_doc = None if action == "create" else reg.load(space)
    auth.authorize(action, space, actor, registry_doc)

    # Recorded only AFTER authorize, so an unauthorized request mutates nothing.
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
