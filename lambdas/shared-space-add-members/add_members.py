"""add-members verb: adds each valid username to the space.

Validates each name against the user pool, assigns a membership slot, writes the member's
membership index entry, appends to the registry and then fans the roster out to every member's
cache. Idempotent — already-members are skipped, and the owner is never added, being normalised
out.

An unknown username is not silently ignored: the name is collected and the space owner is
notified by name, pinned by test. What is true is that the report is late, asynchronous and
owner-only, which is the cost the username-directory arc reduces by suggesting existing
usernames in the browser.

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
from cpcommon import clients, observability
from cpcommon.errors import TerminalError
from notify import emit_notification
from registry import ProvisioningError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


def _release_grants(space, added):
    """Gives back BOTH grants this run handed out, after the roster write refused them.

    A member's access to a space is two writes, and neither is the registry: the Cognito slot,
    which is the S3 and Glue grant under the claims source, and the membership index entry, which
    is the same grant under the index one. Both are written BEFORE the roster, so a refusal at the
    write leaves every one of them standing. Without this the guard leaves the added user holding
    live access to a space they appear in no roster of, which is strictly worse than the state the
    guard prevents: at least a roster entry is visible.

    A name already on the freshly-read roster is skipped, because both writes are idempotent and a
    concurrent run that legitimately committed the same member would otherwise have their access
    revoked by this rollback.

    Each release is best-effort, **including the roster read**: a fault anywhere here would
    propagate out of the caller's refusal handler and release nothing at all — the orphan this
    function exists to prevent — and the user would get the generic clause instead of the
    refusal's own sentence, since the resolver keys on the raised class. An unreadable roster
    falls back to releasing everything: over-releasing costs a re-add, under-releasing leaves a
    live grant nobody can see. The index drop is best-effort HERE and nowhere else — the module
    raises on every write because a stale index is an authorization input that is wrong, and this
    is the one call whose failure must not replace the refusal the user needs to read.

    Args:
      space: The space name.
      added: The members this run granted.

    Returns:
      None.

    Raises:
      None.
    """
    try:
        committed = set((reg.load(space) or {}).get("members") or [])
    except Exception:
        logger.exception("failed to read the roster before releasing grants on %s", space)
        committed = set()
    for member in added:
        if member in committed:
            continue
        try:
            membership.clear_slot(member, space)
        except Exception:
            logger.exception("failed to release the slot for %s on %s", member, space)
        try:
            membership_index.drop(member, space)
        except Exception:
            logger.exception("failed to release the index entry for %s on %s", member, space)


@observability.step("notify-members")
def _notify_members(pending, request_id):
    """Emits every notification this run collected, under one span.

    **Call bound: at most once per invocation.** The span goes around the WHOLE loop rather than
    around ``emit_notification``, which is called once per recipient and is one of the five
    shared functions that must never carry a step of its own. The loop is extracted rather than
    the send hoisted into a shared helper: the dedup id is this verb's own construction, and
    those ids are FIFO deduplication keys on notifications a user sees.

    Args:
      pending: ``(recipient, message, tag)`` triples collected during the member loop.
      request_id: The run's request id, which prefixes each dedup id.

    Returns:
      None.

    Raises:
      None. ``emit_notification`` catches and logs its own failures, so a missed notification
      cannot fail the membership change that has already committed.
    """
    for recipient, message, tag in pending:
        emit_notification(recipient, message, dedup_id=f"{request_id}:{tag}")


def add_members(space, members, request_id, registry):
    """Adds members to a space and reports which were added, unknown, or at their limit.

    The registry write is the consistency point: a hard error aborting mid-loop can leave users
    holding a slot and cache entry not yet in the registry, and the Step Function retries from
    the top — already-slotted users are idempotent and the registry then catches up. The write is
    a delta, so a concurrent remove is not undone by this add, and the roster is fanned out from
    what actually landed rather than from the list computed here, which would otherwise leave the
    cache carrying a roster the registry disagrees with.

    **Every GRANT is written before that point, and the cosmetic write after it.** The slot and
    the membership index entry are the two things that actually admit a member, and both now land
    ahead of the registry commit; the cache fan-out, which admits nobody, stays behind it. That
    ordering is what makes a concurrent delete safe rather than a matter of timing: a delete that
    empties the space AFTER this commit finds the member in the record ``empty_space`` hands back
    and revokes them as a latecomer, and one that empties it BEFORE makes the commit raise, so
    this verb takes its own grants back. Written the other way round — the index after the
    commit, as the cache fan-out is — the delete's revocation could land between the two and the
    entry be re-created over an emptied space, which grants under the index source what the roster
    denies. Two things that argument does NOT claim: the second branch closes through
    ``_release_grants``, which swallows its own failures, so it is closed modulo a rollback that
    may quietly not happen; and the rollback skips anyone on the roster it reads, so on the
    destroying route a read landing before the record is deleted keeps both grants over a name
    that is then freed. The ordinary cost is that a member briefly holds a grant no roster shows,
    which the slot has always had.

    **The index entry's status is written twice only when the second would NARROW it.** The
    pre-commit write can only use the validator's snapshot, which the authorizer guarantees is
    active — so on its own it would stamp every entry active, including an add that commits onto
    a record a delete has already moved to ``deleting``. That is the granting direction, and the
    status is the one field the API's index source reads to decide whether to stamp a tag. So the
    committed status is written back when it is anything but active, and never when it is: a
    re-write that could only ever downgrade cannot re-create a granting entry a concurrent
    revocation has just dropped, which is the whole reason the first write moved.

    Join status is derived inside that same compare-and-swap from the freshly-read record:
    existing members stay as they are and newly-added users are not acknowledged, so they surface
    as pending until they sign in and acknowledge.

    Notifications are collected during the loop and emitted only after the registry write lands,
    so they report a real outcome rather than a step that may roll back or retry.

    Requested, applied and ignored counts are all recorded, because the three diverge silently:
    an unknown username and a user at their workspace limit are both "not added" to a caller
    reading a count, and they need completely different answers. Member names are recorded too,
    not just counts — a username is permitted metadata here, and which member is the whole
    question when a roster disagrees with a registry. The membership grant is live at that point,
    but the principal tag only takes effect once the user's token is re-minted, which is the lag
    that has repeatedly presented as the grant not working, so the record answers that question
    instead of prompting it.

    Args:
      space: The space name.
      members: The requested member names, normalised here once — an earlier version normalised
        twice, so the reported request count came from a second pass that could in principle
        disagree with the one that did the work.
      request_id: The run's request id.
      registry: The registry record from the validator.

    Returns:
      The verb result, carrying the added, unknown and at-limit names.

    Raises:
      OwnerChanged: When the space changed hands between the validator's read and the commit.
      MembershipRefused: When the freshly-read record forbids the addition. Its grants are given
        back first, whichever subclass it is — as they are for every other failure of the commit,
        since an exhausted CAS or an S3 fault leaves the same orphan a refusal would.
      RuntimeError: When the registry CAS attempts are exhausted.
      CasExhausted: When a member's membership-index CAS attempts are exhausted.
      ClientError: On any non-precondition S3 or Cognito fault.
    """
    owner = registry["owner"]
    current_set = set(registry.get("members", []))
    requested = list(membership.normalize_members(members, owner))
    summary = {"added": [], "ignoredUnknown": [], "skippedAtLimit": []}
    pending_notifications = []

    for member in requested:
        if member in current_set:
            continue
        try:
            membership.assign_or_find_slot(member, space)
        except clients.cognito().exceptions.UserNotFoundException:
            summary["ignoredUnknown"].append(member)
            pending_notifications.append(
                (owner, f'Couldn\'t add "{member}" to "{space}": no such user.', f"add-unknown:{member}")
            )
            continue
        except ProvisioningError:
            summary["skippedAtLimit"].append(member)
            pending_notifications.append(
                (owner, f'Couldn\'t add "{member}" to "{space}": they\'ve reached their workspace limit.', f"add-limit:{member}")
            )
            continue
        current_set.add(member)
        summary["added"].append(member)
        pending_notifications.append(
            (member, f'You\'ve been added to the shared workspace "{space}".', f"add-member:{member}")
        )

    if summary["added"]:
        try:
            membership_index.record_for_all(
                summary["added"], space, registry.get("status", "active")
            )
        except Exception:
            _release_grants(space, summary["added"])
            raise

    try:
        committed = reg.save_members(
            registry, request_id, add=summary["added"], expected_owner=owner
        )
    except Exception:
        _release_grants(space, summary["added"])
        raise
    if summary["added"] and committed.get("status") != "active":
        membership_index.record_for_all(summary["added"], space, committed["status"])
    cache.write_roster_to_all(
        committed["members"],
        space,
        committed.get("owner"),
        committed.get("acknowledged", []),
        committed.get("createdAt"),
    )
    _notify_members(pending_notifications, request_id)
    logger.info("add_members %s: %s", space, summary)
    observability.info(
        "members added",
        space=space,
        actor=owner,
        store="registry",
        members_requested=len(requested),
        members_applied=len(summary["added"]),
        members_ignored=len(summary["ignoredUnknown"]),
        skipped_at_limit=len(summary["skippedAtLimit"]),
        added=summary["added"],
        access_live_now=True,
        principal_tag_needs_token_remint=True,
    )
    return {"status": "ok", "action": "add_members", "space": space, **summary}


@observability.traced("add-members")
def handler(event, context):
    """Step Functions entry point for the add-members verb.

    ``@traced`` is the only decorator on this plane: these verbs notify explicitly from inside
    the handler rather than through a decorator, so the ordering rule that governs the other
    three planes does not apply here.

    **It refuses a context carrying a refusal, and that is not belt and braces.** The router has a
    branch that sends a refused request to the notifier instead of here, so reaching this line
    means the routing did not hold — and one action over, the plane page already records why the
    same fence is not optional for a transfer: without it, any failure of the routing completes a
    real one. The same sentence here is a stranger gaining live access to a space's data.

    ``origin`` is re-stamped because observability baggage is per-invocation and ``traced`` clears
    it: without this the span records the space's own owner adding people
    to their space, which is what an
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
            f"a refused add_members reached the verb: {refusal.get('code')}",
        )

    origin = event.get("origin")
    if origin:
        observability.stamp(origin=origin)

    space = event["space"]
    request_id = event.get("requestId")
    registry = event["registry"]
    members = (event.get("payload") or {}).get("members", [])
    return add_members(space, members, request_id, registry)
