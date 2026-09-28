"""remove-members verb: removes each member from the space.

Clears their membership slot, drops their membership index entry and their cache entry, and
removes them from the registry. The
owner is never removed: normalised out against the validator's record, and refused against the
current one. Idempotent — removing a non-member is a no-op.
Shared objects and tables are left intact; this is membership only.

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
from cpcommon import observability
from cpcommon.errors import TerminalError
from notify import emit_notification, send_budget

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


@observability.step("notify-members")
def _notify_members(removed, space, request_id):
    """Tells every removed member, under one span.

    **Call bound: at most once per invocation.** The span goes around the WHOLE loop rather than
    around ``emit_notification``, which runs once per recipient and is one of the five shared
    functions that must never carry a step. The message and the dedup id stay here rather than
    moving to a shared emitter: the dedup id is a FIFO deduplication key on a notification a
    user sees, and each verb's is built differently.

    **Every send shares one budget**, from ``send_budget``: the loop runs after the change has
    committed, and a stalled queue holding each send for a cap of its own would carry a large
    request past the verb's timeout, which the Catch records as a failed run although the change
    committed and some of its members were already told.

    Args:
      removed: The members the registry write actually removed.
      space: The space's name, for the message.
      request_id: The run's request id, which prefixes each dedup id.

    Returns:
      None.

    Raises:
      None. ``emit_notification`` catches and logs its own failures.
    """
    sends = send_budget()
    for member in removed:
        emit_notification(
            member,
            f'You\'ve been removed from the shared space "{space}".',
            dedup_id=f"{request_id}:remove-member:{member}",
            budget=sends,
        )


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

    **A transfer that made one of the names the owner refuses the whole removal**, as the
    validator's own refusal of a removal naming the owner does, because partly serving it is
    worse than saying so. A fresh read refuses it before anything is cleared; the roster write
    refuses it again for a transfer landing after that read, and then gives only the new owner
    back their slot and card — ``membership.reinstate_owner`` says why the others are not.

    **Each removed name's slot and card are cleared on both sides of the commit.** Before it, so
    a fault leaves them listed and a retry repeats the clears; after it, so no grant written in
    between — an owner restore, while the space went to that member and back — outlives the
    removal. The second pass is what ``membership.reinstate_owner``'s confirming read relies on.

    Args:
      space: The space name.
      members: The requested member names, normalised here.
      request_id: The run's request id.
      registry: The registry record from the validator.

    Returns:
      The verb result, carrying the members actually removed.

    Raises:
      OwnerChanged: When a transfer after the request was authorized made one of the names the
        owner.
      RuntimeError: When the registry CAS attempts are exhausted.
      ClientError: On any non-precondition S3 or Cognito fault.
    """
    owner = registry["owner"]
    current_set = set(registry.get("members", []))
    removed = []
    targets = membership.normalize_members(members, owner)
    reg.refuse_removing_owner(reg.load(space), targets)

    for member in targets:
        if member not in current_set:
            continue
        membership.clear_slot(member, space)
        cache.remove_entry(member, space)
        current_set.discard(member)
        removed.append(member)

    try:
        committed = reg.save_members(registry, request_id, remove=removed)
    except reg.OwnerChanged:
        membership.reinstate_owner(removed, space)
        raise
    for member in removed:
        membership.clear_slot(member, space)
        cache.remove_entry(member, space)
    membership_index.drop_for_all(removed, space)
    cache.write_roster_to_all(
        committed["members"],
        space,
        committed.get("owner"),
        committed.get("acknowledged", []),
        committed.get("createdAt"),
    )
    _notify_members(removed, space, request_id)
    logger.info("remove_members %s: removed %s", space, removed)
    observability.info(
        "members removed",
        space=space,
        actor=owner,
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

    **It refuses a context carrying a refusal, and that is not belt and braces.** The router has a
    branch that sends a refused request to the notifier instead of here, so reaching this line
    means the routing did not hold — and one action over, the plane page already records why the
    same fence is not optional for a transfer: without it, any failure of the routing completes a
    real one. The same sentence here is a stranger gaining live access to a space's data.

    ``origin`` is re-stamped because observability baggage is per-invocation and ``traced`` clears
    it: without this the span records the space's own owner removing people
    from their space, which is what an
    operator-driven change must not look like in the record.

    Args:
      event: The validated context from the validator, carrying the space, request id, registry
        record and the requested members.
      context: The Lambda context, unused.

    Returns:
      The verb result.

    Raises:
      TerminalError: When the context carries a refusal.
      KeyError: When the validated context is missing a required field.
    """
    refusal = event.get("refusal")
    if refusal:
        raise TerminalError(
            "unauthorized",
            f"a refused remove_members reached the verb: {refusal.get('code')}",
        )

    origin = event.get("origin")
    if origin:
        observability.stamp(origin=origin)

    space = event["space"]
    request_id = event.get("requestId")
    registry = event["registry"]
    members = (event.get("payload") or {}).get("members", [])
    return remove_members(space, members, request_id, registry)
