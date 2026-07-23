"""delete-space verb: owner cascade-delete (irreversible).

Flags the registry ``deleting`` first, then tears down in a safe order: remove all
shared objects, revoke the LF grant, drop all tables + the Glue DB, clear every
member's slot + cache entry, and finally delete the registry object (LAST -> name
freed). Every step is idempotent and tolerant of partial prior progress, so a re-run
completes a half-done teardown; the registry never returns to ``active`` mid-cascade.
On a hard error it records a terminal ``failed`` status (registry + the owner's cache,
with a reason) for the screen's Retry affordance, then re-raises -> Fail.
"""

import logging

from cpcommon import observability

import cache
import membership
import registry as reg
import teardown
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one shared-space request is up to eight
# invocations, and they are only one queryable set if they share a service name (SPEC-127
# FR-003). The per-verb identity rides as the `verb` field, and the verb names ARE the request
# `action` values this plane already uses, so an event's `verb` and a request's `action` are the
# same string and join without translation (SPEC-134 FR-001).
observability.init(service="shared-space")


def delete_space(space, actor, request_id, registry):
    """Cascade-delete ``space``; records a terminal failed status before re-raising."""
    owner = registry["owner"]
    members = list(registry.get("members", []))
    reg.set_status(registry, "deleting", request_id)
    try:
        teardown.delete_shared_prefix(space)
        teardown.revoke_portal_role(space)
        teardown.drop_database(space)
        for member in members:
            membership.clear_slot(member, space)
            cache.remove_entry(member, space)
        reg.delete(space)  # LAST — the name is now free to reuse
    except Exception as exc:  # noqa: BLE001 - record failure, don't leave it dangling
        reason = str(exc)  # raw — kept in logs + the registry `failed` record
        # SPEC-106 FR-009: teardown failures are all raw AWS/boto text, so the
        # user-facing reason (cache + notification) is a generic friendly clause.
        friendly = "please try again or contact the Administrator"
        logger.error("delete %s failed: %s", space, reason)
        try:
            reg.set_status(registry, "failed", request_id, reason)
        except Exception:  # noqa: BLE001 - best-effort failure recording
            logger.exception("failed to record registry delete failure for %s", space)
        try:
            cache.upsert_entry(
                owner, {"name": space, "role": "owner", "status": "failed", "reason": friendly}
            )
        except Exception:  # noqa: BLE001 - best-effort failure recording
            logger.exception("failed to record cache delete failure for %s", space)
        # Notify the owner of the failure — the delete card's Retry affordance reads the
        # failed cache entry, and the success fan-out below is never reached.
        emit_notification(
            owner,
            f'We couldn\'t delete the shared workspace "{space}": {friendly}.',
            dedup_id=f"{request_id}:delete-failed:{owner}",
        )
        raise
    # Fan out one notification per member, using the list captured BEFORE the cascade
    # cleared the registry (owner ∈ members), deduplicated so each user gets exactly
    # one; the deleter gets a distinct message. Emitted only past the terminal success —
    # a failed cascade re-raises above and emits nothing. Each emit is best-effort, so
    # one failure never aborts the fan-out to the rest.
    for recipient in dict.fromkeys(members):
        message = (
            f'You deleted the shared workspace "{space}".'
            if recipient == actor
            else f'The shared workspace "{space}" was deleted.'
        )
        emit_notification(recipient, message, dedup_id=f"{request_id}:delete:{recipient}")
    logger.info("delete %s by %s: cascade complete (%d members revoked)", space, actor, len(members))
    observability.info(
        "space deleted",
        space=space,
        actor=actor,
        members_applied=len(members),
        revoked=members,
        stores=["registry", "cognito", "glue", "cache"],
    )
    return {"status": "ok", "action": "delete", "space": space, "revokedMembers": members}


# @traced is the ONLY decorator on this plane: these verbs notify explicitly from inside
# the handler rather than via @notifies_on_failure, so the ordering rule that governs
# data-quality/table-builder/table-share does not apply here (SPEC-134 FR-002).
@observability.traced("delete")
def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    registry = event["registry"]
    return delete_space(space, actor, request_id, registry)
