"""remove-members verb: removes each member from the space.

Clears their membership slot, drops their cache entry, and removes them from the registry. The
owner is never removed, being normalised out. Idempotent — removing a non-member is a no-op.
Shared objects and tables are left intact; this is membership only.

The service name is the control plane, not the function: one shared-space request is up to eight
invocations, and they are only one queryable set if they share it. The per-verb identity rides
as the ``verb`` field, and the verb names are the request action values this plane already uses,
so an event's verb and a request's action are the same string and join without translation.
"""

import logging

import cache
import membership
import registry as reg
from cpcommon import observability
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


def remove_members(space, members, request_id, registry):
    """Removes members from a space and reports which were actually removed.

    The registry write is a delta, which also drops removed users from the acknowledged list so
    a later re-add still starts them at pending — derived inside the compare-and-swap from the
    freshly-read record rather than from this request's stale snapshot. The reduced roster is
    then fanned out from what actually landed.

    Each removed member is notified only after the registry write lands, so the notification
    reports a real outcome rather than a step that may roll back or retry. The owner gets no
    roster notification.

    Removal is immediate in the registry; the principal tag stops granting access only once the
    removed user's token is re-minted — the same lag as on the add path, in the direction that
    matters more, which is why it is recorded.

    Args:
      space: The space name.
      members: The requested member names, normalised here.
      request_id: The run's request id.
      registry: The registry record from the validator.

    Returns:
      The verb result, carrying the members actually removed.

    Raises:
      RuntimeError: When the registry CAS attempts are exhausted.
      ClientError: On any non-precondition S3 or Cognito fault.
    """
    owner = registry["owner"]
    current_set = set(registry.get("members", []))
    removed = []

    for member in membership.normalize_members(members, owner):
        if member not in current_set:
            continue
        membership.clear_slot(member, space)
        cache.remove_entry(member, space)
        current_set.discard(member)
        removed.append(member)

    committed = reg.save_members(registry, request_id, remove=removed)
    cache.write_roster_to_all(
        committed["members"],
        space,
        owner,
        committed.get("acknowledged", []),
        committed.get("createdAt"),
    )
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
        principal_tag_needs_token_remint=True,
    )
    return {"status": "ok", "action": "remove_members", "space": space, "removed": removed}


@observability.traced("remove-members")
def handler(event, context):
    """Step Functions entry point for the remove-members verb.

    ``@traced`` is the only decorator on this plane: these verbs notify explicitly from inside
    the handler rather than through a decorator, so the ordering rule that governs the other
    three planes does not apply here.

    Args:
      event: The validated context from the validator, carrying the space, request id, registry
        record and the requested members.
      context: The Lambda context, unused.

    Returns:
      The verb result.

    Raises:
      KeyError: When the validated context is missing a required field.
    """
    space = event["space"]
    request_id = event.get("requestId")
    registry = event["registry"]
    members = (event.get("payload") or {}).get("members", [])
    return remove_members(space, members, request_id, registry)
