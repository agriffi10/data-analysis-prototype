"""validate-authorize — the Step Function's first task (SPEC-056; SPEC-062).

One task, run once before any verb: parse the SQS record, verify the caller's
Cognito ID token, derive the trusted ``actor``, load the registry, and authorize the
action. Read-only — no provisioning side effects. A failed check raises
AuthorizationError, so the state machine's Catch routes to Fail and no verb runs.

Outputs the small validated context the Choice state routes on and the verb consumes:
``{action, actor, space, payload, registry, requestId}`` (the verb trusts this and
never re-verifies the token or re-authorizes).
"""

import json
import logging

import config
import auth
import registry as reg

logger = logging.getLogger()
logger.setLevel(logging.INFO)


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
