"""acknowledge-membership verb: a member confirms they've picked up the space.

The owner's projection lists each member as ``pending`` (invited by the owner but not
yet signed in) or ``active`` (SPEC-073). A member's browser enqueues this request the
first time it resolves a shared space they belong to; the verb flips them to ``active``
by recording the actor in the registry's ``acknowledged`` set and rewriting the owner's
projection. Idempotent — an already-active member is a clean no-op with no registry or
projection write. The validator has already verified the token and authorized
membership (member-only, owner-exempt); the guards here are defence in depth.
"""

import logging

import cache
import registry as reg
from auth import AuthorizationError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def acknowledge_membership(space, actor, request_id, registry):
    """Mark ``actor`` active in ``space``'s owner projection; no-op if already active."""
    owner = registry["owner"]
    members = list(registry.get("members", []))
    if actor == owner:
        raise AuthorizationError("owner does not acknowledge membership")
    if actor not in members:
        # Removed between enqueue and processing — nothing to acknowledge.
        return {"status": "ok", "action": "acknowledge_membership", "space": space, "activated": False}

    acknowledged = reg.effective_acknowledged(registry)
    if actor in acknowledged:
        return {"status": "ok", "action": "acknowledge_membership", "space": space, "activated": False}

    acknowledged.append(actor)
    registry["acknowledged"] = acknowledged
    reg.save_members(registry, members, request_id)
    cache.write_owner_projection(owner, space, members, acknowledged, registry.get("createdAt"))
    logger.info("acknowledge_membership %s: %s now active", space, actor)
    return {"status": "ok", "action": "acknowledge_membership", "space": space, "activated": True}


def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    registry = event["registry"]
    return acknowledge_membership(space, actor, request_id, registry)
