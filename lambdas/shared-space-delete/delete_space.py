"""delete-space verb: the owner ends everyone's access, and usually destroys nothing.

Deleting a space removes PEOPLE, not things. Every member's access ends, the owner's included,
and the space vanishes from every list — but the objects, the Glue database and the registry
record all survive, and the record keeps an active status with an empty roster. What that buys
is a mistake an administrator can undo, on a bucket with no versioning where the old behaviour
could not be undone at all; what it costs is stated where users can see it, because the name is
never released and the data is retained.

One route still destroys, and it is narrow: a space that never finished provisioning was
reachable only by its creator, so this is that creator discarding their own failed create. It
tears down in the old order — objects, the Lake Formation grant, the tables and database, every
member's slot, index entry and cache card, then the registry object, which frees the name. The
member loop runs BEFORE that last step because the record is the name lock, so a claim still
naming a space whose name is free would be an entitlement to whatever is created under it next.

Every step on both routes is idempotent and tolerant of partial prior progress, so a re-run
completes a half-done pass, and the registry never returns to active mid-cascade.

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


def _revoke(members, space):
    """Ends a set of members' access to a space, in the order the grants were given.

    Three stores, all idempotent, so a re-run after a partial pass completes it: the Cognito
    slot, which IS the S3 and Glue grant; the membership index a session's tags are built from;
    and the card the browser renders.

    Args:
      members: The usernames whose access ends.
      space: The space name.

    Returns:
      None.

    Raises:
      ClientError: On any S3 or Cognito fault.
    """
    for member in members:
        membership.clear_slot(member, space)
        membership_index.drop(member, space)
        cache.remove_entry(member, space)


def delete_space(space, actor, request_id, registry):
    """Ends everyone's access to a space, destroying it only if it was never usable.

    **Two routes off one predicate, and the predicate is shared with the guard that refuses new
    members**, so the two cannot disagree about which spaces are destroyable. A space anybody
    could ever have used is EMPTIED: every member's access ends, the owner's included, and the
    objects, the database and the record all survive. A space that never finished provisioning
    is destroyed exactly as before — it was reachable only by its creator, and this route is
    that creator discarding their own failed create.

    The route is decided from a FRESH read, not from the record the validator loaded. Delivery
    is ordered and executions are not, so an add, a leave or a competing delete can land in
    between; and the verb has no status guard in the authorizer to lean on. A record that has
    gone missing refuses rather than proceeding.

    The roster it revokes is the union of the validator's copy and that fresh read, because both
    are snapshots and a member on either holds a live grant. On the emptying route the rewrite
    hands back the record it replaced, and anyone appearing only there is a latecomer whose slot
    is cleared afterwards and who is told the same thing as everyone else.

    A fault after the rewrite is repaired rather than recorded, because by then the owner field
    is gone and the ordinary failed state would be one nobody can act on: no owner to delete, no
    roster to leave, and a retry the authorizer refuses. The repair restores the ROSTER as well
    as the owner, tracked in ``unrevoked``: the rewrite blanks the roster, so a latecomer this
    run had not reached yet exists in no record at all — holding the slot that is their grant,
    never told, and removable by nobody.

    **The actor is revoked on the way out whether or not the roster named them**, because the
    actor is by definition the person who asked. A retry after a repaired failure runs against an
    empty roster, so the loop clears nobody — and the one card that must not survive is the
    requester's own, since the screen renders a deleting row from it for a workspace that is
    already gone, which is the state the retry existed to leave.

    Args:
      space: The space name.
      actor: The verified owner.
      request_id: The run's request id.
      registry: The registry record from the validator.

    Returns:
      The verb result, carrying every member whose access was revoked.

    Raises:
      RegistryRecordMissing: When the fresh read finds no record.
      RegistryRecordResurrected: When a membership write re-created the record after the name
        was freed.
      MembersRemainAfterEmpty: When the roster is not empty after every revocation pass.
      TeardownIncompleteError: When a teardown pass left resources behind, so the name is not
        freed. Reachable on the destroying route only.
      TransientError: On a retryable Glue fault during teardown.
      ClientError: On any other S3, Glue or Cognito fault.
    """
    fresh = reg.load(space)
    if fresh is None:
        raise reg.RegistryRecordMissing(f"space {space!r} has no registry record")
    destroying = reg.is_destroyable(fresh)
    owner = fresh.get("owner") or registry.get("owner")
    members = list(dict.fromkeys([*registry.get("members", []), *fresh.get("members", [])]))
    if not destroying:
        reg.mark_ever_active(space, request_id)
    reg.set_status(registry, "deleting", request_id)
    emptied = False
    unrevoked = []
    try:
        if destroying:
            teardown.delete_shared_prefix(space)
            teardown.revoke_portal_role(space)
            teardown.drop_database(space)
        _revoke(members, space)
        if destroying:
            reg.delete(space)
            if reg.load(space) is not None:
                raise reg.RegistryRecordResurrected(
                    f"space {space!r} reappeared after its name was freed"
                )
        else:
            _committed, replaced = reg.empty_space(space, request_id)
            emptied = True
            latecomers = [m for m in replaced.get("members", []) if m not in members]
            unrevoked = latecomers
            _revoke(latecomers, space)
            unrevoked = []
            members.extend(latecomers)
            if (reg.load(space) or {}).get("members"):
                raise reg.MembersRemainAfterEmpty(
                    f"space {space!r} still lists members after being emptied"
                )
    except Exception as exc:
        reason = str(exc)
        friendly = "please try again or contact the Administrator"
        logger.error("delete %s failed: %s", space, reason)
        try:
            if emptied:
                reg.restore_owner(space, "failed", request_id, reason, members=unrevoked)
            else:
                reg.set_status(registry, "failed", request_id, reason)
        except Exception:
            logger.exception("failed to record registry delete failure for %s", space)
        if owner:
            try:
                cache.upsert_entry(
                    owner,
                    {
                        "name": space,
                        "role": "owner",
                        "status": "failed",
                        "reason": friendly,
                        "failedAction": "delete",
                    },
                )
            except Exception:
                logger.exception("failed to record cache delete failure for %s", space)
            emit_notification(
                owner,
                f'We couldn\'t delete the shared workspace "{space}": {friendly}.',
                dedup_id=f"{request_id}:delete-failed:{owner}",
            )
        raise
    _revoke([actor] if actor not in members else [], space)
    for recipient in dict.fromkeys(members):
        message = (
            f'You deleted the shared workspace "{space}".'
            if recipient == actor
            else f'The shared workspace "{space}" was deleted.'
        )
        emit_notification(recipient, message, dedup_id=f"{request_id}:delete:{recipient}")
    logger.info("delete %s by %s: %d members revoked", space, actor, len(members))
    observability.info(
        "space deleted",
        space=space,
        actor=actor,
        route="destroyed" if destroying else "emptied",
        members_applied=len(members),
        revoked=members,
        stores=(
            ["registry", "cognito", "glue", "cache", "membership-index"]
            if destroying
            else ["registry", "cognito", "cache", "membership-index"]
        ),
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
