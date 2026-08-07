"""validate-authorize — the Step Function's first task, run once before any verb.

Parses the SQS record, verifies the caller's Cognito ID token, derives the trusted actor rather
than the spoofable body actor, loads the registry, and authorizes the action. A failed check
raises so the Catch routes to the fail state and no verb runs. For an authorized create or
delete it also durably records the in-flight state in the actor's cache and emits a start
notification — the browser reads only that cache, so without it the row reconciles back to
active or vanishes on reload. Verbs trust the context it outputs and never re-verify the token
or re-authorize.

The service name is the control plane, not the function: one shared-space request is up to eight
invocations, and they are only one queryable set if they share it. The per-verb identity rides
as the ``verb`` field, and the verb names are the request action values this plane already uses,
so an event's verb and a request's action are the same string and join without translation.

Attributes:
  _INTENT: The actions that record an in-flight intent before the verb runs, mapped to their
    cache writer, notification template and dedup tag. The other verbs write their terminal
    cache state directly, so they have no separate intent row.
"""

import logging

import auth
import cache
import config
import registry as reg
from cpcommon import events, observability
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


_INTENT = {
    "create": (cache.write_owner_pending, 'Creating shared workspace "{space}"…', "create-pending"),
    "delete": (cache.write_owner_deleting, 'Deleting shared workspace "{space}"…', "delete-pending"),
}


def _record_intent(action, actor, space, request_id):
    """Records an authorized create or delete as in-flight in the actor's cache, and notifies.

    Best-effort: a cache-write failure is logged and swallowed, because it must never block the
    action, and the verb writes the authoritative terminal state at the end.

    Args:
      action: ``create`` or ``delete``.
      actor: The verified actor.
      space: The space name.
      request_id: The run's request id.

    Returns:
      None.

    Raises:
      None.
    """
    write, template, tag = _INTENT[action]
    try:
        write(actor, space)
    except Exception:
        logger.warning("intent cache write failed for %s %s/%s", action, actor, space, exc_info=True)
    emit_notification(actor, template.format(space=space), dedup_id=f"{request_id}:{tag}:{actor}")


def _parse_request(event):
    """Parses the queued request out of the Pipe envelope and checks its schema version.

    The envelope handling is ``cpcommon.events.parse_sqs_request``, which this plane had its
    own copy of — identical bar the exception type, which the shared one now takes as a factory
    (SPEC-156 FR-005). ``AuthorizationError`` is what this plane's Standard Step Function's
    Catch is written against, so it stays the type that leaves here.

    Args:
      event: The Pipe payload — a single-element list of records, or one record dict.

    Returns:
      The parsed request.

    Raises:
      AuthorizationError: On an empty batch, an unrecognised event shape, a missing body, a
        body that is not valid JSON, or an unsupported schema version.
    """
    req = events.parse_sqs_request(
        event, reason=events.MALFORMED, exc=auth.AuthorizationError
    )
    if req.get("schemaVersion") != config.SCHEMA_VERSION:
        raise auth.AuthorizationError(f"unsupported schemaVersion: {req.get('schemaVersion')!r}")
    return req


@observability.traced("validate")
def handler(event, context):
    """Validates and authorizes the queued request, returning the context the verbs consume.

    ``@traced`` is the only decorator on this plane: these verbs notify explicitly from inside
    the handler rather than through a decorator, so the ordering rule that governs the other
    three planes does not apply here.

    The intent is recorded only after authorization, so an unauthorized request mutates nothing.

    The space and the actor are on every event from this plane: they are the first two things
    asked about a shared-space incident, and both are permitted metadata — the username already
    is the S3 prefix, the principal tag and the Glue database name. Whether the intent was
    written is recorded too: that durable pending or deleting write is what stops a request
    vanishing between validation and execution, leaving a space in no list at all, and whether it
    happened is exactly what you want to know when one has.

    Args:
      event: The EventBridge Pipe envelope carrying the SQS record.
      context: The Lambda context, unused.

    Returns:
      The validated context the routing state branches on: action, actor, space, payload,
      registry record and request id.

    Raises:
      AuthorizationError: On a malformed envelope, an unverifiable token, or an action the actor
        may not perform.
      ClientError: On any S3 fault loading the registry.
    """
    req = _parse_request(event)
    action = req.get("action")
    space = req.get("space")

    actor = auth.verified_username(req.get("idToken"))

    registry_doc = None if action == "create" else reg.load(space)
    auth.authorize(action, space, actor, registry_doc)

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
    observability.info(
        "validated",
        action=action,
        space=space,
        actor=actor,
        schema_version=(registry_doc or {}).get("schemaVersion"),
        intent_written=action in _INTENT,
        known_space=registry_doc is not None,
    )
    return validated
