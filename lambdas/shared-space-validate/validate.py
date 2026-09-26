"""validate-authorize — the Step Function's first task, run once before any verb.

Parses the SQS record, reads the trusted actor out of the API's identity block rather
than from any body field, loads the registry, and authorizes the action. A failed check
raises so the Catch routes to the fail state and no verb runs.

**This queue now has two producers.** The API is one, and everything above describes it. The
other is the scheduled reader that turns an operator's CSV of membership changes into requests,
and it has no bearer to present — so its messages declare an ``origin`` and carry no identity
block, and the only thing that can be trusted about one is the ``SenderId`` SQS stamps on the
record. That comparison is the boundary; ``auth.operator_refusal`` is where it lives.

**A create's, a transfer's and a member change's refusals are RETURNED on the context, not
raised**, and the router has one branch for them all. The refusals that still raise are caught by
a state whose input was the raw queue batch — so it seeds a null actor and a null space, and the
notifier reads a null actor as no trustworthy recipient and stays silent. All four of those
actions have to say which space they are refusing about, and three of them which member, so they
cannot travel that way. The key is
set only when there IS a refusal:
``IsPresent`` is true for a field that is present and null, so seeding one would route every
request on this plane into the refusal branch. A create is refused here on its NAME alone, and
only a create is — the catalog rule the whole system reads a space name through was applied
nowhere when one was chosen, and a space already carrying a name it does not admit has to stay
deletable. For an authorized create or
delete it also durably records the in-flight state in the actor's cache and emits a start
notification — the browser reads only that cache, so without it the row reconciles back to
active or vanishes on reload. Verbs trust the context it outputs and never re-read the identity
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
import registry as reg
from cpcommon import actor as cpactor
from cpcommon import events, observability
from notify import emit_notification

import config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


_INTENT = {
    "create": (cache.write_owner_pending, 'Creating shared space "{space}"…', "create-pending"),
    "delete": (cache.write_owner_deleting, 'Deleting shared space "{space}"…', "delete-pending"),
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


def _record(event):
    """Returns the raw SQS record the Pipe forwarded, for the attributes the body cannot carry.

    The body is what every other read goes through; this exists for ``SenderId``, which is a
    message SYSTEM attribute rather than a field, and is therefore the one thing in the envelope
    a sender cannot choose. The Pipe declares no input template, so the record arrives whole —
    the same property that lets the body be read off it at all.

    Args:
      event: The Pipe payload — a single-element list of records, or one record dict.

    Returns:
      The record, or an empty mapping when the shape is unrecognisable. Empty yields an empty
      sender, which every caller refuses on.

    Raises:
      None.
    """
    if isinstance(event, list):
        return event[0] if event else {}
    return event if isinstance(event, dict) else {}


def _parse_request(event):
    """Parses the queued request out of the Pipe envelope and checks its schema version.

    The envelope handling is ``cpcommon.events.parse_sqs_request``, which this plane had its
    own copy of — identical bar the exception type, which the shared one now takes as a factory
    . ``AuthorizationError`` is what this plane's Standard Step Function's
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

    **Both predicates run INSIDE the ``refusal is None`` guard, which is load-bearing.**
    ``requester`` is set to None for ANY non-None origin, before ``operator_refusal``'s verdict
    has been read — so a member predicate called outside that guard, or one whose result
    overwrote the origin refusal, would let a message declaring any origin string at all skip
    the owner check.

    The acting identity for an operator-origin request is recorded as ``origin``, and the
    context's ``actor`` is the space's own current owner. That split is deliberate: on this plane
    ``actor`` decides who is notified, and the notifications writer builds an S3 key straight out
    of it with no validation — so a sentinel like ``operator`` would address a prefix a real user
    could own, and it passes the catalog rule that would otherwise catch it. The owner is also the
    right recipient: for a forged operator message they are the named victim, and for a fault
    mid-transfer it is their space. A space with no owner yields no recipient, which is honest —
    there is nobody to tell. The span records the DECLARED origin, not one this service accepts:
    a message claiming some other origin is refused, and a span recording it as an operator
    request would describe something that never happened.

    **A registry record that is not a dict is read as no record at all**, and that has to happen
    here rather than only in the authorizer. The authorizer already answers a malformed record
    with the refusal that says what happened — an unknown space — but this function then reads
    the same record twice more, for the operator path's acting identity and for the span's
    schema version. Both are ``(registry_doc or {}).get(...)``, which a truthy non-dict walks
    straight into: the refusal is computed correctly and then thrown away by an ``AttributeError``
    that reaches nobody, because the catch that receives it nulls the actor and the notifier
    stays silent. Normalising once, at the load, is what makes the refusal arrive.

    Args:
      event: The EventBridge Pipe envelope carrying the SQS record.
      context: The Lambda context, unused.

    Returns:
      The validated context the routing state branches on: action, actor, space, payload,
      registry record and request id, plus ``origin`` on an operator request and ``refusal``
      when the request is refused.

    Raises:
      AuthorizationError: On a malformed envelope, a missing identity block, or an action the actor
        may not perform.
      ClientError: On any S3 fault loading the registry.
    """
    req = _parse_request(event)
    action = req.get("action")
    space = req.get("space")
    origin = req.get("origin")
    is_operator = origin is not None

    refusal = auth.operator_refusal(
        origin, action, space, "identity" in req, events.sender_id(_record(event))
    )

    if is_operator:
        observability.stamp(origin=origin)
        requester = None
    else:
        who = cpactor.trusted_actor(req, exc=auth.AuthorizationError)
        observability.stamp(
            actor=who.username, assurance=who.assurance, delegated_by=who.delegated_by
        )
        requester = who.username

    registry_doc = None if action == "create" else reg.load(space)
    if not isinstance(registry_doc, dict):
        registry_doc = None
    actor = requester if requester is not None else ((registry_doc or {}).get("owner") or "")
    if is_operator:
        observability.stamp(actor=actor)

    if refusal is None:
        if action == "create":
            refusal = auth.create_refusal(space)
        elif action == "transfer_ownership":
            refusal = auth.transfer_refusal(
                requester, space, (req.get("payload") or {}).get("newOwner"), registry_doc
            )
        elif events.in_vocabulary(action, config.MEMBER_ACTIONS):
            refusal = auth.member_refusal(
                requester, space, action, (req.get("payload") or {}).get("members"), registry_doc
            )
        if refusal is None:
            auth.authorize(action, space, actor, registry_doc)
            if events.in_vocabulary(action, _INTENT):
                _record_intent(action, actor, space, req.get("requestId"))

    validated = {
        "traceparent": observability.run_traceparent(),
        "action": action,
        "actor": actor,
        "space": space,
        "payload": req.get("payload") or {},
        "registry": registry_doc,
        "requestId": req.get("requestId"),
    }
    if is_operator:
        validated["origin"] = origin
    if refusal is not None:
        validated["refusal"] = {"code": refusal[0], "message": refusal[1]}

    logger.info("validated %s on %s by %s", action, space, actor)
    observability.info(
        "validated",
        action=action,
        space=space,
        actor=actor,
        schema_version=(registry_doc or {}).get("schemaVersion"),
        intent_written=events.in_vocabulary(action, _INTENT) and refusal is None,
        known_space=registry_doc is not None,
        refused=refusal[0] if refusal is not None else None,
    )
    return validated
