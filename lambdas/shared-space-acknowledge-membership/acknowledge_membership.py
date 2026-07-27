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
from cpcommon import observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one shared-space request is up to eight
# invocations, and they are only one queryable set if they share a service name (SPEC-127
# FR-003). The per-verb identity rides as the `verb` field, and the verb names ARE the request
# `action` values this plane already uses, so an event's `verb` and a request's `action` are the
# same string and join without translation (SPEC-134 FR-001).
observability.init(service="shared-space")


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
    observability.info(
        "membership acknowledged",
        space=space,
        actor=actor,
        store="registry",
        status="active",
        already=False,
    )
    return {"status": "ok", "action": "acknowledge_membership", "space": space, "activated": True}


# @traced is the ONLY decorator on this plane: these verbs notify explicitly from inside
# the handler rather than via @notifies_on_failure, so the ordering rule that governs
# data-quality/table-builder/table-share does not apply here (SPEC-134 FR-002).
@observability.traced("acknowledge-membership")
def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    registry = event["registry"]
    return acknowledge_membership(space, actor, request_id, registry)
