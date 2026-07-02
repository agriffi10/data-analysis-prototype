"""forget verb: durable "clear this entry from my list" (no full delete cascade).

Self-service removal of a failed/phantom connection card, enqueued by the browser's
Dismiss. The browser can't tell a phantom ``role:owner`` (written by a collision) from
a real owner, so the verb decides from the registry loaded by the validator:

- Active space the actor still belongs to -> refuse (owners Delete, members Leave).
- The actor's OWN non-active space -> tear it down (S3 prefix + Glue DB + LF revoke),
  clear the actor's slot + cache entry, delete the registry record (frees the name).
  A failed create is single-member (create is creator-only), so no one else to clear.
- Everything else (no registry record, or owned by someone else) -> cache-only:
  remove the actor's cache entry + slot, touching only the caller's own projection.

No notification — a self-service action with immediate UI feedback.
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
    """Clear ``space`` from the actor's list; ``registry`` is None for a phantom space."""
    if registry is not None:
        owner = registry.get("owner")
        members = registry.get("members", [])
        status = registry.get("status")
        if status == "active" and actor in members:
            # Clearing a healthy membership's cache entry would recreate the vanish bug.
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
