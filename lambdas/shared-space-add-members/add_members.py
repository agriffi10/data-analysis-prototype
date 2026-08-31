"""add-members verb: adds each valid username to the space.

Validates each name against the user pool, assigns a membership slot, writes the member's cache
entry and membership index entry, and appends to the registry. Idempotent — already-members are skipped, and the owner is
never added, being normalised out.

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
from notify import emit_notification
from registry import ProvisioningError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")


def add_members(space, members, request_id, registry):
    """Adds members to a space and reports which were added, unknown, or at their limit.

    The registry write is the consistency point: a hard error aborting mid-loop can leave users
    holding a slot and cache entry not yet in the registry, and the Step Function retries from
    the top — already-slotted users are idempotent and the registry then catches up. The write is
    a delta, so a concurrent remove is not undone by this add, and the roster is fanned out from
    what actually landed rather than from the list computed here, which would otherwise leave the
    cache carrying a roster the registry disagrees with.

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
      RuntimeError: When the registry CAS attempts are exhausted.
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

    committed = reg.save_members(registry, request_id, add=summary["added"])
    membership_index.record_for_all(
        summary["added"], space, committed.get("status", "active")
    )
    cache.write_roster_to_all(
        committed["members"],
        space,
        owner,
        committed.get("acknowledged", []),
        committed.get("createdAt"),
    )
    for recipient, message, tag in pending_notifications:
        emit_notification(recipient, message, dedup_id=f"{request_id}:{tag}")
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
    return add_members(space, members, request_id, registry)
