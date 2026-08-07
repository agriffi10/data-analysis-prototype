"""acknowledge-membership verb: a member confirms they have picked up the space.

The owner's projection lists each member as pending — invited by the owner but not yet signed
in — or active. A member's browser enqueues this request the first time it resolves a shared
space they belong to, and the verb flips them to active by recording the actor in the registry's
acknowledged set and rewriting the owner's projection. Idempotent: an already-active member is a
clean no-op with no registry or projection write. The validator has already verified the token
and authorized membership, so the guards here are defence in depth.

The service name is the control plane, not the function: one shared-space request is up to eight
invocations, and they are only one queryable set if they share it. The per-verb identity rides
as the ``verb`` field, and the verb names are the request action values this plane already uses,
so an event's verb and a request's action are the same string and join without translation.
"""

import logging

import cache
import registry as reg
from auth import AuthorizationError
from cpcommon import observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


def acknowledge_membership(space, actor, request_id, registry):
    """Marks an actor active in a space's owner projection.

    The promotion is applied as a delta: moving one member from pending to active must not
    rewrite the whole roster from a snapshot read before this request began.

    Args:
      space: The space name.
      actor: The verified member acknowledging.
      request_id: The run's request id.
      registry: The registry record from the validator.

    Returns:
      The verb result, whose activated flag is False when there was nothing to do — either the
      member was already active, or they were removed between enqueue and processing.

    Raises:
      AuthorizationError: When the actor is the owner, who is always active.
      RuntimeError: When the registry CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """
    owner = registry["owner"]
    members = list(registry.get("members", []))
    if actor == owner:
        raise AuthorizationError("owner does not acknowledge membership")
    if actor not in members:
        return {"status": "ok", "action": "acknowledge_membership", "space": space, "activated": False}

    acknowledged = reg.effective_acknowledged(registry)
    if actor in acknowledged:
        return {"status": "ok", "action": "acknowledge_membership", "space": space, "activated": False}

    committed = reg.save_members(registry, request_id, acknowledge=[actor])
    cache.write_owner_projection(
        owner,
        space,
        committed["members"],
        committed.get("acknowledged", []),
        committed.get("createdAt"),
    )
    logger.info("acknowledge_membership %s: %s now active", space, actor)
    observability.info(
        "membership acknowledged",
        space=space,
        actor=actor,
        store="registry",
        status="active",
        already=False,
    )
    return {"status": "ok", "action": "acknowledge_membership", "space": space, "activated": True}


@observability.traced("acknowledge-membership")
def handler(event, context):
    """Step Functions entry point for the acknowledge verb.

    ``@traced`` is the only decorator on this plane: these verbs notify explicitly from inside
    the handler rather than through a decorator, so the ordering rule that governs the other
    three planes does not apply here.

    Args:
      event: The validated context from the validator, carrying the space, actor, request id and
        registry record.
      context: The Lambda context, unused.

    Returns:
      The verb result.

    Raises:
      AuthorizationError: When the actor is the owner.
      KeyError: When the validated context is missing a required field.
    """
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    registry = event["registry"]
    return acknowledge_membership(space, actor, request_id, registry)
