"""add-members verb: add each valid username to the space.

Validates each against the User Pool (unknown -> silently ignored), assigns a
membership slot (no free slot -> skipped at-limit), writes the member's cache entry,
and appends to the registry. Idempotent — already-members are skipped. The owner is
never added (normalized out). Returns a summary {added, ignoredUnknown,
skippedAtLimit}.
"""

import logging

from cpcommon import clients
import cache
import membership
import registry as reg
from registry import ProvisioningError
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def add_members(space, members, request_id, registry):
    """Add ``members`` to ``space``; return {added, ignoredUnknown, skippedAtLimit}."""
    owner = registry["owner"]
    created_at = registry.get("createdAt")
    current = list(registry.get("members", []))
    current_set = set(current)
    # Join status (SPEC-073): existing members stay as-is; newly-added users are NOT
    # added to `acknowledged`, so they surface as `pending` until they sign in and ack.
    acknowledged = reg.effective_acknowledged(registry)
    summary = {"added": [], "ignoredUnknown": [], "skippedAtLimit": []}
    # Collected during the loop, emitted only AFTER the registry write lands — notify a
    # real outcome, not a step that may roll back or retry.
    pending_notifications = []

    # The registry write below is the consistency point: a hard error (e.g. a throttle)
    # aborting mid-loop can leave users holding a slot + cache entry not yet in the
    # registry. The Step Function retries from the top — already-slotted users are
    # idempotent and the registry then catches up.
    for member in membership.normalize_members(members, owner):
        if member in current_set:
            continue  # already a member (idempotent) — emits nothing
        try:
            membership.assign_or_find_slot(member, space)  # admin_get_user = existence check
        except clients.cognito().exceptions.UserNotFoundException:
            summary["ignoredUnknown"].append(member)
            pending_notifications.append(
                (owner, f'Couldn\'t add "{member}" to "{space}": no such user.', f"add-unknown:{member}")
            )
            continue
        except ProvisioningError:  # only raised for "membership limit reached"
            summary["skippedAtLimit"].append(member)
            pending_notifications.append(
                (owner, f'Couldn\'t add "{member}" to "{space}": they\'ve reached their workspace limit.', f"add-limit:{member}")
            )
            continue
        current.append(member)
        current_set.add(member)
        summary["added"].append(member)
        pending_notifications.append(
            (member, f'You\'ve been added to the shared workspace "{space}".', f"add-member:{member}")
        )

    registry["acknowledged"] = acknowledged
    reg.save_members(registry, current, request_id)
    # Fan the new roster out to the owner + every member (SPEC-075) — newly-added
    # members get their cache entry here, with the full roster, in one pass.
    cache.write_roster_to_all(current, space, owner, acknowledged, created_at)
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
