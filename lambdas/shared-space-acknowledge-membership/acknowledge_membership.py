"""acknowledge-membership verb: a member confirms they have picked up the space.

The owner's projection lists each member as pending — invited by the owner but not yet signed
in — or active. A member's browser enqueues this request the first time it resolves a shared
space they belong to, and the verb flips them to active by recording the actor in the registry's
acknowledged set and fanning the promoted roster out to the owner and every member. Idempotent:
an already-active member is a clean no-op with no registry or cache write. The validator has
already verified the token and authorized membership, so the guards here are defence in depth.

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


def _fan_out_roster(space, owner, committed):
    """Publishes the promoted roster to the owner and to every member's own cache.

    This used to write the owner's projection alone, which left every member's
    copy — including the acknowledging member's own — frozen at the status it held when they were
    added. The roster is the only member-facing view of who is in a space, so one member could
    read ``Pending`` about themselves on the same page whose connections row said ``Active``, and
    Refresh could not reconcile it because no writer ever ran.

    The registry write is the consistency point and it has already committed, so nothing here may
    fail the run: the retry would find the member already acknowledged, no-op, and never write
    the caches at all. A failure therefore costs a stale roster, which is what the fan-out's own
    per-member best-effort handling already accepts.

    Args:
      space: The space name.
      owner: The space's owner.
      committed: The registry record as saved, carrying the members, acknowledged set and
        creation date.

    Returns:
      None.

    Raises:
      None.
    """
    try:
        cache.write_roster_to_all(
            committed["members"],
            space,
            owner,
            committed.get("acknowledged", []),
            committed.get("createdAt"),
        )
    except Exception:
        logger.exception("roster fan-out after acknowledge for %s failed (best-effort)", space)
        observability.warning("roster fan-out failed after acknowledge", space=space, store="cache")


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
    _fan_out_roster(space, committed.get("owner"), committed)
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
