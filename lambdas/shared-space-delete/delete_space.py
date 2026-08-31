"""delete-space verb: the owner's irreversible cascade delete.

Flags the registry as deleting first, then tears down in a safe order: remove all shared
objects, revoke the Lake Formation grant, drop all tables and the database, clear every
member's slot, membership index entry and cache entry, and finally delete the registry object,
which frees the name. The index drop sits in that member loop and therefore BEFORE the record is
deleted: the record is the name lock, so an index still naming a space whose name is free would
be an entitlement to whatever is created next.
Every step is idempotent and tolerant of partial prior progress, so a re-run completes a
half-done teardown, and the registry never returns to active mid-cascade.

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
import teardown
from cpcommon import observability
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


def delete_space(space, actor, request_id, registry):
    """Cascade-deletes a space, recording a terminal failed status before re-raising.

    On a hard error the failure is recorded in both the registry and the owner's cache, with a
    reason, for the screen's retry affordance, and the owner is notified — the retry affordance
    reads that failed cache entry, and the success fan-out is never reached. Teardown failures
    are all raw service text, so the user-facing reason is a generic friendly clause while the
    raw text stays in the logs and the registry record. Both failure recordings are best-effort:
    the raise is what matters.

    On success one notification goes to each member, from the list captured before the cascade
    cleared the registry, de-duplicated so each user gets exactly one, with a distinct message
    for the deleter. Each emit is best-effort, so one failure never aborts the fan-out.

    Args:
      space: The space name.
      actor: The verified owner.
      request_id: The run's request id.
      registry: The registry record from the validator.

    Returns:
      The verb result, carrying the members whose access was revoked.

    Raises:
      TeardownIncompleteError: When a teardown pass left resources behind, so the name is not
        freed.
      TransientError: On a retryable Glue fault during teardown.
      ClientError: On any other S3, Glue or Cognito fault.
    """
    owner = registry["owner"]
    members = list(registry.get("members", []))
    reg.set_status(registry, "deleting", request_id)
    try:
        teardown.delete_shared_prefix(space)
        teardown.revoke_portal_role(space)
        teardown.drop_database(space)
        for member in members:
            membership.clear_slot(member, space)
            membership_index.drop(member, space)
            cache.remove_entry(member, space)
        reg.delete(space)
    except Exception as exc:
        reason = str(exc)
        friendly = "please try again or contact the Administrator"
        logger.error("delete %s failed: %s", space, reason)
        try:
            reg.set_status(registry, "failed", request_id, reason)
        except Exception:
            logger.exception("failed to record registry delete failure for %s", space)
        try:
            cache.upsert_entry(
                owner, {"name": space, "role": "owner", "status": "failed", "reason": friendly}
            )
        except Exception:
            logger.exception("failed to record cache delete failure for %s", space)
        emit_notification(
            owner,
            f'We couldn\'t delete the shared workspace "{space}": {friendly}.',
            dedup_id=f"{request_id}:delete-failed:{owner}",
        )
        raise
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
        stores=["registry", "cognito", "glue", "cache", "membership-index"],
    )
    return {"status": "ok", "action": "delete", "space": space, "revokedMembers": members}


@observability.traced("delete")
def handler(event, context):
    """Step Functions entry point for the delete verb.

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
      TeardownIncompleteError: When the cascade left resources behind.
      KeyError: When the validated context is missing a required field.
    """
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    registry = event["registry"]
    return delete_space(space, actor, request_id, registry)
