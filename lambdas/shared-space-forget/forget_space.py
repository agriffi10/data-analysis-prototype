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
import membership_index
import registry as reg
import teardown
from auth import AuthorizationError
from cpcommon import observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


def forget_space(space, actor, request_id, registry):
    """Clears a space from the actor's list, tearing it down when it is their own dead create.

    Both paths clear the actor's membership slot and their membership index entry, because both
    are the actor's own claim on the space and this verb exists to end it. The cache-only path
    leaves the registry alone by design; it does not leave the entitlement behind.

    **The teardown path clears the WHOLE roster — every member's slot, index entry and cache card,
    not just the actor's** — because it calls ``reg.delete`` and the record is the name lock: a
    claim still naming a space whose name is free is an entitlement to whatever gets created under
    it next, since the portal role's shared-space policy is scoped on the membership tag value and
    not on any space identity. Reasoning that a never-active space has only its creator is what
    once left the other members' slots standing, and it is wrong: a space that never provisioned
    can still have been added to, before additions to such a space were refused. The roster is
    therefore the union of the validator's copy and a fresh read, and the clearing runs BEFORE
    ``reg.delete``, so a fault partway through leaves the name locked rather than free with tags
    still standing.

    The actor's own cache card is removed LAST, out of step with the loop, because it is the row
    the Connections page renders and therefore the only affordance for retrying this verb. A fault
    anywhere in the fan-out has to leave that card standing, or the space is stranded: torn down,
    still holding its name, and invisible to the one user who could ask again. The other members'
    cards go inside the loop, since their access is what is being withdrawn.

    **Four outcomes, and the order between them is the requirement.** An active space the actor
    still belongs to is refused, because clearing a healthy membership's cache entry would
    recreate the vanishing-space bug — owners delete and members leave. The actor's own space is
    then split on whether it was ever usable: a space that never was is torn down in full and its
    record deleted, freeing the name; one that WAS is **kept, and this verb clears nothing at all
    for it** — not the slot, not the card, not the index entry. Everything else — no registry
    record, or a space owned by someone else — is cache-only.

    That third branch is the one worth explaining, because "clear the caller's own card" looks
    harmless. The Connections page derives every row from the cache, so clearing the card deletes
    the row, and the row is the only affordance for retrying a delete that failed. With create
    refused on an ever-used name and delete needing a row that no longer renders, one dismiss
    would strand the space permanently. It returns a no-op rather than raising, so the row simply
    survives.

    A branch that only guarded the OWNER's case would leave a member dismissing a failed-delete
    row falling through to cache-only and clearing their own slot — which is what leaving means
    and is fine; only the owner's row is load-bearing.

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
      RegistryRecordMissing: When the actor owns the space but its record has gone. Unlike the
        delete verb this is a live path, because the authorizer returns early for this action so
        that a phantom card stays dismissible.
      RegistryRecordResurrected: When a membership write re-created the record after the name
        was freed.
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
        if owner == actor:
            fresh = reg.load(space)
            if fresh is None:
                raise reg.RegistryRecordMissing(f"space {space!r} has no registry record")
            if not reg.is_destroyable(fresh):
                logger.info("forget %s by %s: kept, the space was usable", space, actor)
                observability.info(
                    "space forgotten",
                    space=space,
                    actor=actor,
                    mode="kept",
                    stores=[],
                    registry_left_intact=True,
                )
                return {"status": "ok", "action": "forget", "space": space, "mode": "kept"}
            teardown.delete_shared_prefix(space)
            teardown.revoke_portal_role(space)
            teardown.drop_database(space)
            roster = list(dict.fromkeys([actor, *members, *fresh.get("members", [])]))
            for member in roster:
                membership.clear_slot(member, space)
                if member != actor:
                    cache.remove_entry(member, space)
            membership_index.drop_for_all(roster, space)
            cache.remove_entry(actor, space)
            reg.delete(space)
            if reg.load(space) is not None:
                raise reg.RegistryRecordResurrected(
                    f"space {space!r} reappeared after its name was freed"
                )
            logger.info("forget %s by %s: tore down own never-active space", space, actor)
            observability.info(
                "space forgotten",
                space=space,
                actor=actor,
                mode="teardown",
                members_applied=len(roster),
                stores=["registry", "cognito", "glue", "cache", "membership-index"],
            )
            return {"status": "ok", "action": "forget", "space": space, "mode": "teardown"}
    membership.clear_slot(actor, space)
    membership_index.drop(actor, space)
    cache.remove_entry(actor, space)
    logger.info("forget %s by %s: cache-only removal", space, actor)
    observability.info(
        "space forgotten",
        space=space,
        actor=actor,
        mode="cache_only",
        stores=["cognito", "cache", "membership-index"],
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
