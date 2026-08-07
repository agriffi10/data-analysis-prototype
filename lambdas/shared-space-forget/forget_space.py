"""forget verb: a durable "clear this entry from my list", with no full delete cascade.

Self-service removal of a failed or phantom connection card, enqueued by the browser's dismiss
control. The browser cannot tell a phantom owner entry, written by a collision, from a real one,
so the verb decides from the registry the validator loaded. No notification is emitted: this is
a self-service action with immediate UI feedback.

The service name is the control plane, not the function: one shared-space request is up to eight
invocations, and they are only one queryable set if they share it. The per-verb identity rides
as the ``verb`` field, and the verb names are the request action values this plane already uses,
so an event's verb and a request's action are the same string and join without translation.
"""

import logging

import cache
import membership
import registry as reg
import teardown
from auth import AuthorizationError
from cpcommon import observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


def forget_space(space, actor, request_id, registry):
    """Clears a space from the actor's list, tearing it down when it is their own dead create.

    Three outcomes. An active space the actor still belongs to is refused, because clearing a
    healthy membership's cache entry would recreate the vanishing-space bug — owners delete and
    members leave. The actor's own non-active space is torn down in full and the registry record
    deleted, freeing the name; a failed create is single-member, since creating is creator-only,
    so there is no one else to clear, and every teardown step is idempotent. Everything else — no
    registry record, or a space owned by someone else — is cache-only, touching nothing but the
    caller's own projection and slot.

    What the cache-only path deliberately leaves is the point of its record: this verb exists
    because a space could get stuck in a user's list, and leaving the registry untouched is
    intentional. Without saying so, the next reader sees a half-done teardown.

    Args:
      space: The space name.
      actor: The verified actor.
      request_id: The run's request id, unused.
      registry: The registry record, or None for a phantom space.

    Returns:
      The verb result, whose mode says which path ran.

    Raises:
      AuthorizationError: When the space is active and the actor still belongs to it.
      TeardownIncompleteError: When a teardown pass left resources behind, so the name is not
        freed.
      TransientError: On a retryable Glue fault during teardown.
      ClientError: On any other S3, Glue or Cognito fault.
    """
    if registry is not None:
        owner = registry.get("owner")
        members = registry.get("members", [])
        status = registry.get("status")
        if status == "active" and actor in members:
            raise AuthorizationError(
                f"cannot forget active space {space!r} — use Delete (owner) or Leave (member)"
            )
        if owner == actor and status != "active":
            teardown.delete_shared_prefix(space)
            teardown.revoke_portal_role(space)
            teardown.drop_database(space)
            membership.clear_slot(actor, space)
            cache.remove_entry(actor, space)
            reg.delete(space)
            logger.info("forget %s by %s: tore down own non-active space", space, actor)
            observability.info(
                "space forgotten",
                space=space,
                actor=actor,
                mode="teardown",
                stores=["registry", "glue", "cache"],
            )
            return {"status": "ok", "action": "forget", "space": space, "mode": "teardown"}
    membership.clear_slot(actor, space)
    cache.remove_entry(actor, space)
    logger.info("forget %s by %s: cache-only removal", space, actor)
    observability.info(
        "space forgotten",
        space=space,
        actor=actor,
        mode="cache_only",
        stores=["cache"],
        registry_left_intact=True,
    )
    return {"status": "ok", "action": "forget", "space": space, "mode": "cache_only"}


@observability.traced("forget")
def handler(event, context):
    """Step Functions entry point for the forget verb.

    ``@traced`` is the only decorator on this plane: these verbs notify explicitly from inside
    the handler rather than through a decorator, so the ordering rule that governs the other
    three planes does not apply here.

    Args:
      event: The validated context from the validator, carrying the space, actor, request id and
        the registry record when there is one.
      context: The Lambda context, unused.

    Returns:
      The verb result.

    Raises:
      AuthorizationError: When the space is active and the actor still belongs to it.
      KeyError: When the validated context is missing a required field.
    """
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    registry = event.get("registry")
    return forget_space(space, actor, request_id, registry)
