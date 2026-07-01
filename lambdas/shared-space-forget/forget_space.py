"""forget verb — durable "clear this entry from my list" (no full delete cascade).

Self-service removal of a FAILED / phantom connection card. The browser's Dismiss
enqueues it. The browser can't tell a phantom ``role:owner`` (a collision wrote it)
from a real owner, so the verb decides from the registry (loaded by the validator):

- **Active space the actor still belongs to** -> REFUSE (owners Delete, members Leave;
  clearing a healthy membership would recreate the "vanish" bug).
- **The actor's OWN non-active space** (owner == actor, status != active) -> tear down
  the space (S3 prefix + Glue DB + LF revoke), clear the actor's slot, remove the
  actor's cache entry, delete the registry record (frees the name). Single-member —
  create is creator-only, so a failed create never has other members.
- **Everything else** (no registry record, or owned by someone else — the collision
  phantom / an orphaned member projection) -> CACHE-ONLY: remove the actor's cache
  entry + clear the actor's slot. Touches only the caller's own projection.

No notification — a self-service action with immediate UI feedback, unlike the async
create/delete outcomes.
"""

import logging

import cache
import membership
import registry as reg
import teardown
from auth import AuthorizationError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def forget_space(space, actor, request_id, registry):
    """``registry`` is the loaded record, or None for a phantom/absent space."""
    if registry is not None:
        owner = registry.get("owner")
        members = registry.get("members", [])
        status = registry.get("status")
        if status == "active" and actor in members:
            # A healthy space the actor belongs to — clearing its cache entry would
            # recreate the vanish bug. Owners delete it; members leave it.
            raise AuthorizationError(
                f"cannot forget active space {space!r} — use Delete (owner) or Leave (member)"
            )
        if owner == actor and status != "active":
            # The actor's own failed/stuck create — tear it down so nothing is orphaned
            # and the name is freed. Idempotent: absent resources are no-ops.
            teardown.delete_shared_prefix(space)
            teardown.revoke_portal_role(space)
            teardown.drop_database(space)
            membership.clear_slot(actor, space)
            cache.remove_entry(actor, space)
            reg.delete(space)
            logger.info("forget %s by %s: tore down own non-active space", space, actor)
            return {"status": "ok", "action": "forget", "space": space, "mode": "teardown"}
    # Phantom / not-owned / orphaned projection: cache-only — remove only the caller's
    # own entry + slot. Never touches the registry or another user's space.
    membership.clear_slot(actor, space)
    cache.remove_entry(actor, space)
    logger.info("forget %s by %s: cache-only removal", space, actor)
    return {"status": "ok", "action": "forget", "space": space, "mode": "cache_only"}


def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    registry = event.get("registry")
    return forget_space(space, actor, request_id, registry)
