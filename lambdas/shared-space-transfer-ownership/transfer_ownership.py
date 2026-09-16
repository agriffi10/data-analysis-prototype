"""transfer-ownership verb: the owner hands a shared space to an existing member.

Everything about the space survives — the prefix, the Glue database, the roster, the data. What
changes is who holds it, and the bookkeeping derived from that: the outgoing owner stays on as an
ordinary member, and both parties are told.

No Cognito call, no membership slot, no principal tag and no Lake Formation grant. Access here is
membership, membership did not change, so nothing that grants access changes either. That is
asserted rather than described, because the intuition it contradicts — "ownership must be an
entitlement somewhere" — is the one an implementer arrives with.

The service name is the control plane, not the function: one shared-space request is up to eight
invocations, and they are only one queryable set if they share it. The per-verb identity rides as
the ``verb`` field, and the verb names are the request action values this plane already uses, so an
event's verb and a request's action are the same string and join without translation.
"""

import logging

import cache
import messages
import registry as reg
from cpcommon import observability
from cpcommon.errors import TerminalError
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


def _fan_out_roster(space, owner, committed):
    """Publishes the new owner and the corrected roster to every member's cache.

    One existing call does the whole of it, which is why nothing is written here: passing the NEW
    owner makes the outgoing owner take a member entry naming them, and the incoming owner take
    the owner projection. A member whose document is absent has one created, and one member's
    failure is logged and skipped rather than aborting the rest.

    The registry write is the consistency point and has already committed, so nothing here may
    fail the run: a retry would find the owner already changed, refuse, and never reach the caches
    at all. A failure therefore costs a stale roster, which is what the fan-out's own per-member
    handling already accepts.

    Args:
      space: The space name.
      owner: The space's new owner.
      committed: The registry record as saved.

    Returns:
      None.

    Raises:
      None.
    """
    try:
        cache.write_roster_to_all(
            committed["members"],
            space,
            owner,
            committed.get("acknowledged", []),
            committed.get("createdAt"),
        )
    except Exception:
        logger.exception("roster fan-out after transfer of %s failed (best-effort)", space)
        observability.warning("roster fan-out failed after transfer", space=space, store="cache")


def transfer_ownership(space, request_id, registry, new_owner):
    """Moves a space to another member and tells both of them.

    Args:
      space: The space name.
      request_id: The run's request id.
      registry: The registry record from the validator.
      new_owner: The member taking the space.

    Returns:
      The verb result, naming both parties.

    Raises:
      RegistryRecordMissing: When the record went away before the write.
      SpaceAlreadyEmptied: When a delete emptied the space first.
      OwnerChanged: When the space changed hands first.
      TransferTargetNoLongerMember: When a removal took the named member off the roster first.
      CasExhausted: When the registry CAS attempts are exhausted.
      ClientError: On any non-precondition S3 fault.
    """
    outgoing = registry["owner"]

    committed = reg.set_owner(registry, outgoing, new_owner, request_id)
    _fan_out_roster(space, new_owner, committed)

    to_outgoing, to_incoming = messages.transfer_notifications(space, outgoing, new_owner)
    emit_notification(outgoing, to_outgoing, dedup_id=f"{request_id}:transferred-away:{outgoing}")
    emit_notification(new_owner, to_incoming, dedup_id=f"{request_id}:transferred-to:{new_owner}")

    logger.info("transfer_ownership %s: %s -> %s", space, outgoing, new_owner)
    observability.info(
        "ownership transferred",
        space=space,
        actor=outgoing,
        store="registry",
        new_owner=new_owner,
        members=len(committed.get("members", [])),
    )
    return {
        "status": "ok",
        "action": "transfer_ownership",
        "space": space,
        "previousOwner": outgoing,
        "newOwner": new_owner,
    }


@observability.traced("transfer-ownership")
def handler(event, context):
    """Step Functions entry point for the transfer verb.

    ``@traced`` is the only decorator on this plane: these verbs notify explicitly from inside the
    handler rather than through a decorator, so the ordering rule that governs the other three
    planes does not apply here.

    **It refuses a context carrying a refusal, and that is not belt and braces.** The router has a
    branch that sends a refused request to the notifier instead of here, so reaching this line
    means the routing did not hold — and the shape of that failure is the one this project keeps
    paying for: a forged operator message would otherwise complete a real transfer, because the
    compare-and-swap's owner check is a lost-update guard and passes when nothing about the owner
    has changed. The Choice is the fast path; this is the fence.

    ``origin`` is re-stamped because observability baggage is per-invocation and ``traced`` clears
    it: without this the span records the owner transferring their own space away, which is what
    an operator-driven transfer must not look like in the record.

    Args:
      event: The validated context from the validator, carrying the space, request id, registry
        record and the payload naming the new owner.
      context: The Lambda context, unused.

    Returns:
      The verb result.

    Raises:
      TerminalError: When the context carries a refusal, or names no new owner.
      KeyError: When the validated context is missing a required field.
    """
    refusal = event.get("refusal")
    if refusal:
        raise TerminalError(
            "unauthorized",
            f"a refused transfer reached the verb: {refusal.get('code')}",
        )

    origin = event.get("origin")
    if origin:
        observability.stamp(origin=origin)

    space = event["space"]
    request_id = event.get("requestId")
    registry = event["registry"]
    new_owner = (event.get("payload") or {}).get("newOwner")
    if not new_owner:
        raise TerminalError("malformed_event", "the transfer names no new owner")
    return transfer_ownership(space, request_id, registry, new_owner)
