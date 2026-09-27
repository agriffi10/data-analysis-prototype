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


def _revoke(members, space, remaining=None):
    """Ends a set of members' access to a space, in the order the grants were given.

    Three stores, all idempotent, so a re-run after a partial pass completes it: the Cognito
    slot, which IS the S3 and Glue grant; the membership index a session's tags are built from;
    and the card the browser renders.

    ``remaining`` is how the emptying route knows who it never reached. The rewrite blanks the
    roster before this runs, so a member left half-revoked when a fault lands exists in no record
    at all — holding the slot that is their grant, never told, and removable by nobody. Each name
    is struck off only once all three of its stores are done, so the list the repair restores is
    the one the repair is for.

    Args:
      members: The usernames whose access ends.
      space: The space name.
      remaining: A list to strike each member from as their revocation completes, passed by the
        LATECOMER pass alone. The main pass needs none — the record still carries the roster
        while it runs, so a fault there is repaired from the record itself — and the destroying
        route frees the name and has no roster to put anyone back on.

    Returns:
      None.

    Raises:
      CasExhausted: When a member's membership-index compare-and-swap is exhausted.
      MembershipIndexUnreadable: When a member's stored index does not parse.
      ClientError: On any S3 or Cognito fault.
    """
    for member in members:
        membership.clear_slot(member, space)
        membership_index.drop(member, space)
        cache.remove_entry(member, space)
        if remaining is not None and member in remaining:
            remaining.remove(member)


def _hand_the_space_back(space, actor, registry, request_id):
    """Leaves a space this delete may no longer touch exactly as it found it.

    Reached only when the space changed hands after the request was authorized. Everything here
    is best-effort and nothing raises: the caller is about to re-raise the refusal, and a fault
    in the tidy-up must not replace the sentence the actor needs to read.

    **It runs before anything is revoked, which is what keeps it this small.** The only owner
    check the cascade makes is on its first write, and a refusal there writes nothing, so the most
    reaching here can find is a deleting status an earlier attempt of this request left. A check on the emptying rewrite would have caught a transfer
    landing later, during the revocation loop; ``empty_space``'s docstring says why that was tried
    and abandoned rather than repaired from here.

    Two things are undone. The deleting status, when this run wrote it — the record belongs to
    the new owner now, and leaving it deleting, or writing the ordinary ``failed``, freezes a
    healthy space: the authorizer refuses an addition, a transfer and a retry on anything that
    is not active, so the new owner would hold a space nobody could use or repair. **Only this
    run's own write is undone**, keyed on the status still being ``deleting`` AND the record
    still naming this request: the new owner may have started a delete of their own in the same
    window, and restoring ``active`` over that would hide their cascade or their failure rather
    than repair ours. That pair of conditions is the whole gate: a flag saying this run got as far
    as writing would add nothing the record does not already say, and would stop a retry repairing
    a status its own earlier attempt left behind. And the actor's own cache card, which the
    validator stamped *deleting*
    before the verb ran. The actor is still a MEMBER — a transfer leaves the outgoing owner on
    the roster — so the card is rewritten as the member card it should now be, rather than as a
    failure the screen offers a Retry on that this verb would refuse again.

    The refusal itself is told by the plane's failure path, which resolves ``OwnerChanged`` to
    its own sentence, so nothing here notifies.

    Args:
      space: The space name.
      actor: The requester, who is no longer the owner.
      registry: The registry record from the validator, for the space name.
      request_id: The run's request id.

    Returns:
      None.

    Raises:
      None.
    """
    try:
        current = reg.load(space) or {}
        if current.get("status") == "deleting" and current.get("lastRequestId") == request_id:
            reg.set_status(registry, "active", request_id)
    except Exception:
        logger.exception("failed to clear the deleting status on %s after a refusal", space)
    try:
        record = reg.load(space) or {}
        roster = membership.roster(record)
        owner = record.get("owner")
        if owner and actor in roster:
            cache.write_member_entry(
                actor,
                space,
                owner,
                roster,
                reg.effective_acknowledged(record),
                record.get("createdAt"),
            )
        else:
            cache.remove_entry(actor, space)
    except Exception:
        logger.exception("failed to restore the card for %s on %s after a refusal", actor, space)


@observability.step("notify-members")
def _notify_members(members, space, actor, request_id):
    """Tells everyone the space is gone, under one span.

    **Call bound: at most once per invocation.** The span goes around the WHOLE loop rather than
    around ``emit_notification``, which runs once per recipient and is one of the five shared
    functions that must never carry a step.

    Covers the SUCCESS fan-out only. The failure path emits its own single notification to the
    owner and is deliberately outside this helper: it is one send rather than a loop, it says
    something different, and folding it in here would put it under a span named for a fan-out
    that did not happen.

    ``dict.fromkeys`` rather than a set, and it stays here rather than moving to a shared
    emitter: it dedupes recipients while preserving order, and the message depends on whether
    the recipient is the actor.

    Args:
      members: The space's members at deletion, possibly with repeats.
      space: The space's name, for the message.
      actor: Who deleted it — they are told they did it, everyone else that it happened.
      request_id: The run's request id, which prefixes each dedup id.

    Returns:
      None.

    Raises:
      None. ``emit_notification`` catches and logs its own failures.
    """
    for recipient in dict.fromkeys(members):
        message = (
            f'You deleted the shared space "{space}".'
            if recipient == actor
            else f'The shared space "{space}" was deleted.'
        )
        emit_notification(recipient, message, dedup_id=f"{request_id}:delete:{recipient}")


def delete_space(space, actor, request_id, registry):
    """Ends everyone's access to a space, destroying it only if it was never usable.

    **Two routes off one predicate, and the predicate is shared with the guard that refuses new
    members**, so the two cannot disagree about which spaces are destroyable. A space anybody
    could ever have used is EMPTIED: every member's access ends, the owner's included, and the
    objects, the database and the record all survive. A space that never finished provisioning
    is destroyed exactly as before — it was reachable only by its creator, and this route is
    that creator discarding their own failed create.

    **The route and the owner are both decided on the cascade's FIRST WRITE**, the
    ``begin_delete`` claim, and not on the record the validator loaded or on a read of the verb's
    own. Delivery is ordered and executions are not, so an add, a leave, a transfer, the owner's
    create retry or a competing delete can land in between, and a read can only be re-checked by
    the write that follows it. A route decided on a read tore down a space the create had turned
    active after it; an owner checked on one emptied a space that had changed hands. Inside the
    swap, a refusal has written nothing to a record it may not touch, and a space found
    destroyable stays that way, because the claim is what ``finalize`` refuses. A record that has
    gone missing refuses rather than proceeding. What a refusal still owes is the requester's own
    card, which the validator stamped before the verb ran.

    **That is the ONLY owner check, and a transfer landing later is not caught.** The emptying
    rewrite could carry one, and for a while it did; ``empty_space``'s docstring records why it
    does not. The cost is stated rather than repaired: a transfer that commits while the
    revocation loop runs loses its space, which is a state this system can undo — the objects,
    the database and the name all survive an emptying — where the half-repairs tried in its place
    were not.

    **Emptying before revoking was also tried, and reverted.** It closes that refusal cleanly and
    clears the owner and the roster before anyone is revoked, so a Lambda killed mid-loop — a
    timeout is none of the four errors the machine retries — leaves every unreached member
    holding a live grant on a record naming nobody, unreachable even by a retry, since deleting
    is owner-only and the field is gone. Revoking first shrinks that population to the LATECOMER
    pass and does not empty it: a kill between the rewrite and a latecomer's revocation strands
    that latecomer the same way, because the rewrite has already blanked the roster and the
    replay reads it back empty. What the order does buy is that a FAULT anywhere in the main loop
    leaves the record untouched and the retry idempotent, and one after the rewrite is repaired
    by ``restore_owner`` putting the unreached names back.

    The roster it revokes is the union of the validator's copy and the record the claim read, because both
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
      RegistryRecordMissing: When the claim finds no record.
      OwnerChanged: When the space changed hands before the claim.
      RegistryRecordResurrected: When a membership write re-created the record after the name
        was freed.
      MembersRemainAfterEmpty: When the roster is not empty after every revocation pass.
      TeardownIncompleteError: When a teardown pass left resources behind, so the name is not
        freed. Reachable on the destroying route only.
      TransientError: On a retryable Glue fault during teardown.
      ClientError: On any other S3, Glue or Cognito fault.
    """
    try:
        fresh, destroying = reg.begin_delete(registry, actor, request_id)
    except reg.OwnerChanged:
        _hand_the_space_back(space, actor, registry, request_id)
        raise
    owner = fresh.get("owner") or registry.get("owner")
    members = list(dict.fromkeys([*registry.get("members", []), *fresh.get("members", [])]))
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
            replaced_members = replaced.get("members")
            replaced_members = replaced_members if isinstance(replaced_members, list) else []
            emptied = True
            latecomers = [m for m in replaced_members if m not in members]
            unrevoked = list(latecomers)
            _revoke(latecomers, space, remaining=unrevoked)
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
                f'We couldn\'t delete the shared space "{space}": {friendly}.',
                dedup_id=f"{request_id}:delete-failed:{owner}",
            )
        raise
    _revoke([actor] if actor not in members else [], space)
    _notify_members(members, space, actor, request_id)
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
