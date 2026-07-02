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
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def leave_space(space, actor, request_id, registry):
    """Remove ``actor`` from ``space``; a clean no-op success if they aren't a member."""
    owner = registry["owner"]
    members = list(registry.get("members", []))
    if actor == owner:
        raise AuthorizationError("owner cannot leave their own space (delete it instead)")
    if actor not in members:
        return {"status": "ok", "action": "leave", "space": space, "left": False}
    membership.clear_slot(actor, space)
    cache.remove_entry(actor, space)
    remaining = [m for m in members if m != actor]
    reg.save_members(registry, remaining, request_id)
    cache.write_owner_projection(owner, space, remaining, registry.get("createdAt"))
    # Notify the owner only after the registry write lands; no-op leaves emit nothing.
    emit_notification(
        owner,
        f'"{actor}" left the shared workspace "{space}".',
        dedup_id=f"{request_id}:leave:{actor}",
    )
    logger.info("leave %s: %s left (%d remaining)", space, actor, len(remaining))
    return {"status": "ok", "action": "leave", "space": space, "left": True}


def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    registry = event["registry"]
    return leave_space(space, actor, request_id, registry)
