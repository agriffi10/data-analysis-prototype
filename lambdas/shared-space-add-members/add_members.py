"""add-members verb (SPEC-053; SPEC-062 single-task Lambda).

Add each valid username to the space: validate against the User Pool (unknown ->
silently ignored), assign a membership slot (no free slot -> skipped at-limit), write
the member's cache entry, and append to the registry. Idempotent — already-members are
skipped. The owner is never added (normalized out). Returns a summary {added,
ignoredUnknown, skippedAtLimit}.
"""

import logging

import clients
import cache
import membership
import registry as reg
from registry import ProvisioningError
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def add_members(space, members, request_id, registry):
    owner = registry["owner"]
    current = list(registry.get("members", []))
    current_set = set(current)
    summary = {"added": [], "ignoredUnknown": [], "skippedAtLimit": []}
    # SPEC-061 events 3/4/5: collected during the loop, emitted only AFTER the registry
    # write lands (FR-007 — notify a real outcome, not a step that may roll back/retry).
    pending_notifications = []

    # The registry write below is the consistency point: if a hard error (e.g. a
    # throttle, not unknown/at-limit) aborts mid-loop, some users may hold a slot +
    # cache entry not yet in the registry. The Step Function retries from the top —
    # already-slotted users are idempotent and the registry then catches up.
    for member in membership.normalize_members(members, owner):
        if member in current_set:
            continue  # already a member (idempotent) — emits nothing
        try:
            membership.assign_or_find_slot(member, space)  # admin_get_user = existence check
        except clients.cognito().exceptions.UserNotFoundException:
            summary["ignoredUnknown"].append(member)
            # Event 5 -> the owner who requested the add.
            pending_notifications.append(
                (owner, f'Couldn\'t add "{member}" to "{space}": no such user.', f"add-unknown:{member}")
            )
            continue
        except ProvisioningError:  # only raised for "membership limit reached"
            summary["skippedAtLimit"].append(member)
            # Event 4 -> the owner who requested the add.
            pending_notifications.append(
                (owner, f'Couldn\'t add "{member}" to "{space}": they\'ve reached their workspace limit.', f"add-limit:{member}")
            )
            continue
        cache.upsert_entry(member, {"name": space, "role": "member", "status": "active"})
        current.append(member)
        current_set.add(member)
        summary["added"].append(member)
        # Event 3 -> the newly-added member.
        pending_notifications.append(
            (member, f'You\'ve been added to the shared workspace "{space}".', f"add-member:{member}")
        )

    reg.save_members(registry, current, request_id)
    cache.write_owner_projection(owner, space, current)
    for recipient, message, tag in pending_notifications:
        emit_notification(recipient, message, dedup_id=f"{request_id}:{tag}")
    logger.info("add_members %s: %s", space, summary)
    return {"status": "ok", "action": "add_members", "space": space, **summary}


def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    request_id = event.get("requestId")
    registry = event["registry"]
    members = (event.get("payload") or {}).get("members", [])
    return add_members(space, members, request_id, registry)
