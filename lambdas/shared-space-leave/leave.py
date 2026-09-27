"""leave verb: a member revokes only their own access.

Clears the actor's membership slot, membership index entry and cache entry, and drops them from
the registry. Shared
objects, tables, the database and every other member are untouched. Idempotent — if the actor
is not a member, such as on a retry after the registry write, it is a clean no-op success. The
slot and card are cleared before the registry write, so a mid-way failure leaves the actor still
listed and a retry re-runs the idempotent clears, and again after it. The validator already
blocks the owner; the guards here re-check it against the record as it is now.

The service name is the control plane, not the function: one shared-space request is up to eight
invocations, and they are only one queryable set if they share it. The per-verb identity rides
as the ``verb`` field, and the verb names are the request action values this plane already uses,
so an event's verb and a request's action are the same string and join without translation.
"""

import logging

import cache
import membership
import membership_index
import registry as reg
from auth import AuthorizationError
from cpcommon import observability
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


def leave_space(space, actor, request_id, registry):
    """Removes an actor from a space, or reports cleanly that there was nothing to do.

    The no-op is a distinct, recorded state rather than an absent event: "the verb ran and there
    was nothing to do" and "the verb never ran" look identical in a store that only records what
    happened.

    The registry write is a delta, so one member leaving cannot overwrite a roster another
    request changed while this one was in flight, and the reduced roster is fanned out from what
    actually landed. The owner is notified only after that write lands; a no-op leave emits
    nothing.

    **A transfer to the actor refuses the leave.** The validator's owner check read an older
    record, and completing the leave wrote an owner who is not a member. A fresh read refuses it
    before anything is cleared; the roster write refuses it again for a transfer landing after
    that read, and then gives the new owner back the slot and card cleared ahead of the write.

    **The slot and card are cleared on both sides of the commit.** Before it, so a fault leaves
    the actor listed and a retry repeats the clears; after it, so no grant written in between —
    an owner restore, while the space went to the actor and back — outlives the removal. The
    second pass is what ``membership.reinstate_owner``'s confirming read relies on.

    Args:
      space: The space name.
      actor: The verified member leaving.
      request_id: The run's request id.
      registry: The registry record from the validator.

    Returns:
      The verb result, whose left flag is False when the actor was not a member.

    Raises:
      AuthorizationError: When the actor is the owner, who must delete the space instead.
      OwnerChanged: When the space was transferred to the actor after the request was authorized.
      RuntimeError: When the registry CAS attempts are exhausted.
      ClientError: On any non-precondition S3 or Cognito fault.
    """
    owner = registry["owner"]
    members = list(registry.get("members", []))
    if actor == owner:
        raise AuthorizationError("owner cannot leave their own space (delete it instead)")
    if actor not in members:
        observability.info(
            "nothing to leave", space=space, actor=actor, already=True, left=False
        )
        return {"status": "ok", "action": "leave", "space": space, "left": False}
    reg.refuse_removing_owner(reg.load(space), [actor])
    membership.clear_slot(actor, space)
    cache.remove_entry(actor, space)
    try:
        committed = reg.save_members(registry, request_id, remove=[actor])
    except reg.OwnerChanged:
        membership.reinstate_owner([actor], space)
        raise
    membership.clear_slot(actor, space)
    cache.remove_entry(actor, space)
    membership_index.drop(actor, space)
    remaining = committed["members"]
    cache.write_roster_to_all(
        remaining,
        space,
        committed.get("owner"),
        committed.get("acknowledged", []),
        committed.get("createdAt"),
    )
    told = committed.get("owner") or owner
    emit_notification(
        told,
        f'"{actor}" left the shared space "{space}".',
        dedup_id=f"{request_id}:leave:{actor}",
    )
    logger.info("leave %s: %s left (%d remaining)", space, actor, len(remaining))
    observability.info(
        "member left",
        space=space,
        actor=actor,
        store="registry",
        remaining=len(remaining),
        left=True,
    )
    return {"status": "ok", "action": "leave", "space": space, "left": True}


@observability.traced("leave")
def handler(event, context):
    """Step Functions entry point for the leave verb.

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
    return leave_space(space, actor, request_id, registry)
