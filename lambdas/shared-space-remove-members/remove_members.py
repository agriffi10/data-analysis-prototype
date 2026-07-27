"""remove-members verb: remove each member from the space.

Clears their slot, drops their cache entry, and removes them from the registry. The
owner is never removed (normalized out). Idempotent — removing a non-member is a
no-op. Shared objects/tables are left intact (membership only). Returns {removed}.
"""

import logging

import cache
import membership
import registry as reg
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


def remove_members(space, members, request_id, registry):
    """Remove ``members`` from ``space``; return the list actually removed."""
    owner = registry["owner"]
    current = list(registry.get("members", []))
    current_set = set(current)
    acknowledged = reg.effective_acknowledged(registry)
    removed = []

    for member in membership.normalize_members(members, owner):
        if member not in current_set:
            continue  # not a member (idempotent) — emits nothing
        membership.clear_slot(member, space)
        cache.remove_entry(member, space)
        current = [m for m in current if m != member]
        current_set.discard(member)
        removed.append(member)

    # Drop removed users from acknowledged so a later re-add starts them at `pending`.
    removed_set = set(removed)
    acknowledged = [a for a in acknowledged if a not in removed_set]
    registry["acknowledged"] = acknowledged
    reg.save_members(registry, current, request_id)
    # Removed members' entries were dropped above; fan the reduced roster out to the
    # owner + every remaining member (SPEC-075).
    cache.write_roster_to_all(current, space, owner, acknowledged, registry.get("createdAt"))
    # Notify each removed member only AFTER the registry write lands — a real outcome,
    # not a step that may roll back or retry. The owner gets no roster notification.
    for member in removed:
        emit_notification(
            member,
            f'You\'ve been removed from the shared workspace "{space}".',
            dedup_id=f"{request_id}:remove-member:{member}",
        )
    logger.info("remove_members %s: removed %s", space, removed)
    observability.info(
        "members removed",
        space=space,
        store="registry",
        members_applied=len(removed),
        removed=removed,
        # Removal is immediate in the registry; the principal TAG stops granting access only
        # once the removed user's token is re-minted — the same lag as on the add path, in the
        # direction that matters more.
        principal_tag_needs_token_remint=True,
    )
    return {"status": "ok", "action": "remove_members", "space": space, "removed": removed}


# @traced is the ONLY decorator on this plane: these verbs notify explicitly from inside
# the handler rather than via @notifies_on_failure, so the ordering rule that governs
# data-quality/table-builder/table-share does not apply here (SPEC-134 FR-002).
@observability.traced("remove-members")
def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    request_id = event.get("requestId")
    registry = event["registry"]
    members = (event.get("payload") or {}).get("members", [])
    return remove_members(space, members, request_id, registry)
