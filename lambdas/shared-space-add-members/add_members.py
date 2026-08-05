"""add-members verb: add each valid username to the space.

Validates each against the User Pool, assigns a membership slot (no free slot -> skipped
at-limit), writes the member's cache entry, and appends to the registry. Idempotent —
already-members are skipped. The owner is never added (normalized out). Returns a summary
{added, ignoredUnknown, skippedAtLimit}.

**An unknown username is NOT silently ignored** — this docstring said it was, and had been
wrong since the notification landed. The name is collected into ``ignoredUnknown`` and the
space OWNER is notified by name ("Couldn't add 'bob' to 'sales': no such user"), pinned by
``test_add_unknown_notifies_owner``. What is true is that the report is late, asynchronous and
owner-only, which is the cost SPEC-146→148 reduce by suggesting existing usernames in the
browser. Corrected under SPEC-146: a wrong comment about error handling is how a later design
gets built on a premise that stopped being true.
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
    # Join status (SPEC-073) is now derived inside save_members' CAS, from the freshly
    # read record: existing members stay as-is and newly-added users are NOT acknowledged,
    # so they surface as `pending` until they sign in and ack.
    # Computed ONCE (SPEC-151 FR-009). It was called again at the log site below, so the
    # normalisation ran twice per request and `members_requested` was derived from a second
    # pass that could in principle disagree with the one that actually did the work.
    requested = list(membership.normalize_members(members, owner))
    summary = {"added": [], "ignoredUnknown": [], "skippedAtLimit": []}
    # Collected during the loop, emitted only AFTER the registry write lands — notify a
    # real outcome, not a step that may roll back or retry.
    pending_notifications = []

    # The registry write below is the consistency point: a hard error (e.g. a throttle)
    # aborting mid-loop can leave users holding a slot + cache entry not yet in the
    # registry. The Step Function retries from the top — already-slotted users are
    # idempotent and the registry then catches up.
    for member in requested:
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

    # A DELTA, not `current`: the roster is derived inside the CAS from the freshly-read
    # record, so a concurrent remove is not undone by this add (SPEC-151 FR-004).
    committed = reg.save_members(registry, request_id, add=summary["added"])
    # Fan out from what actually LANDED, not from the list computed here — otherwise the
    # cache would carry a roster the registry disagrees with, which is the same stale-read
    # defect one layer down.
    cache.write_roster_to_all(
        committed["members"],
        space,
        owner,
        committed.get("acknowledged", []),
        committed.get("createdAt", created_at),
    )
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
        members_requested=len(requested),
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
