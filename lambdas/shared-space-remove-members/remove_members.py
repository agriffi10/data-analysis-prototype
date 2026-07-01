"""remove-members verb (SPEC-053; SPEC-062 single-task Lambda).

Remove each member from the space: clear their slot, drop their cache entry, and
remove them from the registry. The owner is never removed (normalized out).
Idempotent — removing a non-member is a no-op. Shared objects/tables are left intact
(membership only). Returns {removed}.
"""

import logging

import cache
import membership
import registry as reg
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def remove_members(space, members, request_id, registry):
    owner = registry["owner"]
    current = list(registry.get("members", []))
    current_set = set(current)
    removed = []

    for member in membership.normalize_members(members, owner):
        if member not in current_set:
            continue  # not a member (idempotent) — emits nothing
        membership.clear_slot(member, space)
        cache.remove_entry(member, space)
        current = [m for m in current if m != member]
        current_set.discard(member)
        removed.append(member)

    reg.save_members(registry, current, request_id)
    cache.write_owner_projection(owner, space, current, registry.get("createdAt"))
    # Notify each removed member AFTER the registry write lands (notify a real outcome,
    # not a step that may roll back/retry — the add_members pattern). Only real removals
    # are notified; the owner gets no roster-rewrite notification.
    for member in removed:
        emit_notification(
            member,
            f'You\'ve been removed from the shared workspace "{space}".',
            dedup_id=f"{request_id}:remove-member:{member}",
        )
    logger.info("remove_members %s: removed %s", space, removed)
    return {"status": "ok", "action": "remove_members", "space": space, "removed": removed}


def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    request_id = event.get("requestId")
    registry = event["registry"]
    members = (event.get("payload") or {}).get("members", [])
    return remove_members(space, members, request_id, registry)
