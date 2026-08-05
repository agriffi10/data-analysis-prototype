"""leave verb: a member revokes only their own access.

Clears the actor's membership slot + per-user cache entry and drops them from the
registry. Shared objects/tables/DB and every OTHER member are untouched. Idempotent —
if the actor isn't a member (e.g. a retry after the registry write) it's a clean no-op
success. The registry write is LAST, so a mid-way failure leaves the actor still
listed and a retry re-runs the (idempotent) slot/cache clears. The validator already
blocks the owner; the guard here is defence in depth.
"""

import logging

import cache
import membership
import registry as reg
from auth import AuthorizationError
from cpcommon import observability
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one shared-space request is up to eight
# invocations, and they are only one queryable set if they share a service name (SPEC-127
# FR-003). The per-verb identity rides as the `verb` field, and the verb names ARE the request
# `action` values this plane already uses, so an event's `verb` and a request's `action` are the
# same string and join without translation (SPEC-134 FR-001).
observability.init(service="shared-space")


def leave_space(space, actor, request_id, registry):
    """Remove ``actor`` from ``space``; a clean no-op success if they aren't a member."""
    owner = registry["owner"]
    members = list(registry.get("members", []))
    if actor == owner:
        raise AuthorizationError("owner cannot leave their own space (delete it instead)")
    if actor not in members:
        # A distinct, LOGGED state rather than an absent event: "the verb ran and there was
        # nothing to do" and "the verb never ran" look identical in a store that only records
        # what happened (SPEC-134 FR-003).
        observability.info(
            "nothing to leave", space=space, actor=actor, already=True, left=False
        )
        return {"status": "ok", "action": "leave", "space": space, "left": False}
    membership.clear_slot(actor, space)
    cache.remove_entry(actor, space)
    # A DELTA (SPEC-151 FR-004): one member leaving must not overwrite a roster another
    # request changed while this one was in flight.
    committed = reg.save_members(registry, request_id, remove=[actor])
    remaining = committed["members"]
    # The leaver's entry was dropped above; fan the reduced roster out to the owner +
    # every remaining member (SPEC-075), from what actually landed.
    cache.write_roster_to_all(
        remaining,
        space,
        owner,
        committed.get("acknowledged", []),
        committed.get("createdAt"),
    )
    # Notify the owner only after the registry write lands; no-op leaves emit nothing.
    emit_notification(
        owner,
        f'"{actor}" left the shared workspace "{space}".',
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


# @traced is the ONLY decorator on this plane: these verbs notify explicitly from inside
# the handler rather than via @notifies_on_failure, so the ordering rule that governs
# data-quality/table-builder/table-share does not apply here (SPEC-134 FR-002).
@observability.traced("leave")
def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    registry = event["registry"]
    return leave_space(space, actor, request_id, registry)
