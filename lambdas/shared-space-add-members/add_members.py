"""add-members verb: add each valid username to the space.

Validates each against the User Pool (unknown -> silently ignored), assigns a
membership slot (no free slot -> skipped at-limit), writes the member's cache entry,
and appends to the registry. Idempotent — already-members are skipped. The owner is
never added (normalized out). Returns a summary {added, ignoredUnknown,
skippedAtLimit}.
"""

import logging

import cache
import membership
import registry as reg
from cpcommon import clients, observability
from notify import emit_notification
from registry import ProvisioningError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one shared-space request is up to eight
# invocations, and they are only one queryable set if they share a service name (SPEC-127
# FR-003). The per-verb identity rides as the `verb` field, and the verb names ARE the request
# `action` values this plane already uses, so an event's `verb` and a request's `action` are the
# same string and join without translation (SPEC-134 FR-001).
observability.init(service="shared-space")


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
    # Requested vs applied vs ignored, because the three diverge silently: an unknown username
    # and a user at their workspace limit are both "not added" to a caller reading a count, and
    # they need completely different answers.
    #
    # MEMBER NAMES, not just counts. A username is permitted metadata here (it already IS the
    # S3 prefix, the principal tag and the Glue database name), and "which member" is the whole
    # question when a roster disagrees with a registry.
    #
    # The membership grant is live AT THIS POINT — but the principal TAG only takes effect once
    # the user's token is re-minted, which is the lag that has repeatedly presented as "the
    # grant didn't work" (SPEC-134 FR-006). Said here so the log answers that question instead
    # of prompting it.
    observability.info(
        "members added",
        space=space,
        actor=owner,
        store="registry",
        members_requested=len(list(membership.normalize_members(members, owner))),
        members_applied=len(summary["added"]),
        members_ignored=len(summary["ignoredUnknown"]),
        skipped_at_limit=len(summary["skippedAtLimit"]),
        added=summary["added"],
        access_live_now=True,
        principal_tag_needs_token_remint=True,
    )
    return {"status": "ok", "action": "add_members", "space": space, **summary}


# @traced is the ONLY decorator on this plane: these verbs notify explicitly from inside
# the handler rather than via @notifies_on_failure, so the ordering rule that governs
# data-quality/table-builder/table-share does not apply here (SPEC-134 FR-002).
@observability.traced("add-members")
def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    request_id = event.get("requestId")
    registry = event["registry"]
    members = (event.get("payload") or {}).get("members", [])
    return add_members(space, members, request_id, registry)
