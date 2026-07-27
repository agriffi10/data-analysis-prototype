"""create-space verb: provision a new shared space owned by the actor.

Atomically reserves the globally unique name (registry conditional create), assigns
the creator a membership slot, creates the shared prefix marker + Glue database,
grants the shared portal role on the DB, and writes the registry + the creator's
per-user cache. Every step tolerates "already exists" (replay-safe); a mid-way
failure records a terminal ``failed`` status (registry + the creator's cache) with a
reason, then re-raises -> Fail. Create is creator-only: it provisions only
``members:[actor]`` and takes no member list — members are added later via
add-members.
"""

import logging

import cache
import config
import membership
import registry as reg
from cpcommon import clients, observability
from cpcommon import config as cpconfig
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one shared-space request is up to eight
# invocations, and they are only one queryable set if they share a service name (SPEC-127
# FR-003). The per-verb identity rides as the `verb` field, and the verb names ARE the request
# `action` values this plane already uses, so an event's `verb` and a request's `action` are the
# same string and join without translation (SPEC-134 FR-001).
observability.init(service="shared-space")

# Generic user-facing clause for an unexpected AWS/boto failure — the raw str(exc)
# is kept in logs + the registry `failed` record for operators, never shown.
_GENERIC_REASON = "please try again or contact the Administrator"

# LF-Tag stamped on every shared-space database so the control-plane execution roles
# (table-builder / table-share / data-quality) get CREATE_TABLE on it via TBAC — those
# roles are granted on this tag, not per-DB (infra/modules/analytics/lakeformation.tf).
# Key/value MUST match aws_lakeformation_lf_tag.portal_managed there.
PORTAL_MANAGED_TAG_KEY = "portal-managed"
PORTAL_MANAGED_TAG_VALUE = "true"


def _user_reason(exc):
    """The user-facing failure reason (SPEC-106 FR-009).

    Keep the deliberate, already-friendly ProvisioningError text ("name already
    taken", "membership limit reached"); replace any raw AWS/boto ``str(exc)`` with
    a generic clause so no raw cloud text reaches the notification or the cache
    `reason` the Connections card shows.
    """
    return str(exc) if isinstance(exc, reg.ProvisioningError) else _GENERIC_REASON


def _ensure_marker(name):
    """Create the space's DO_NOT_DELETE.txt marker. Idempotent."""
    clients.s3().put_object(
        Bucket=cpconfig.SHARED_SPACE_BUCKET,
        Key=f"{name}/DO_NOT_DELETE.txt",
        Body=b"This object marks a shared space. Do not delete.\n",
    )


def _ensure_database(name):
    glue = clients.glue()
    try:
        glue.create_database(DatabaseInput={"Name": name})
    except glue.exceptions.AlreadyExistsException:
        pass


def _tag_database(name):
    """Attach the ``portal-managed`` LF-Tag to the shared DB.

    This is what grants the control-plane execution roles (table-builder / table-share
    / data-quality) CREATE_TABLE on the database — they are granted on the tag, not
    per-DB (analytics module). Idempotent. ``add_lf_tags_to_resource`` reports per-tag
    problems in a ``Failures`` list rather than raising, so a non-empty ``Failures`` is
    turned into an exception the create path records as a terminal ``failed``.
    """
    resp = clients.lf().add_lf_tags_to_resource(
        Resource={"Database": {"Name": name}},
        LFTags=[{"TagKey": PORTAL_MANAGED_TAG_KEY, "TagValues": [PORTAL_MANAGED_TAG_VALUE]}],
    )
    failures = resp.get("Failures") or []
    if failures:
        raise RuntimeError(f"failed to tag database {name} {PORTAL_MANAGED_TAG_KEY}: {failures}")


def _grant_portal_role(name):
    """Grant the shared portal role full DB + table access on ``name``.

    Idempotent — LF GrantPermissions re-grants safely. DATA_LOCATION_ACCESS on the
    shared bucket is a one-time Terraform grant (shared-spaces/lakeformation.tf),
    not per-DB.
    """
    lf = clients.lf()
    lf.grant_permissions(
        Principal={"DataLakePrincipalIdentifier": config.PORTAL_ROLE_ARN},
        Resource={"Database": {"Name": name}},
        Permissions=config.DATABASE_PERMISSIONS,
    )
    lf.grant_permissions(
        Principal={"DataLakePrincipalIdentifier": config.PORTAL_ROLE_ARN},
        Resource={"Table": {"DatabaseName": name, "TableWildcard": {}}},
        Permissions=config.TABLE_PERMISSIONS,
    )


def create_space(name, actor, request_id):
    """Provision a new shared space owned by ``actor``.

    Idempotent; records a terminal failed status (registry + the owner's cache) on any
    error before re-raising.
    """
    try:
        outcome = reg.reserve(name, actor, request_id)  # may raise "name already taken"
    except Exception as exc:  # record + notify the actor, then fail
        # Reserve is handled outside the provisioning try/except on purpose: a name
        # collision must NOT rewrite the registry — the name belongs to the space's real
        # owner. The actor's OWN cache is theirs to correct: the validator wrote a
        # `provisioning` entry, so mark it `failed` (best-effort) or the actor is left
        # with a stuck phantom they can't clear. Then notify and re-raise.
        reason = str(exc)  # raw — logs only (registry is untouched on a collision)
        friendly = _user_reason(exc)
        logger.error("create %s reserve failed for %s: %s", name, actor, reason)
        try:
            cache.upsert_entry(
                actor, {"name": name, "role": "owner", "status": "failed", "reason": friendly}
            )
        except Exception:  # best-effort failure recording
            logger.exception("failed to mark reserve-collision failure in cache for %s", name)
        emit_notification(
            actor,
            f'We couldn\'t create shared workspace "{name}": {friendly}.',
            dedup_id=f"{request_id}:create-failed:{actor}",
        )
        raise
    if outcome == "replay" and (reg.load(name) or {}).get("status") == "active":
        observability.info(
            "create replayed",
            space=name,
            actor=actor,
            store="registry",
            already=True,
            provisioned=False,
        )
        return {"status": "active", "space": name, "owner": actor, "replay": True}
    try:
        membership.assign_or_find_slot(actor, name)  # may raise "membership limit reached"
        _ensure_marker(name)
        _ensure_database(name)
        _tag_database(name)
        _grant_portal_role(name)
        # Seed the owner's member projection with just the owner; carry the registry's
        # createdAt so the Connections card meta line can show it.
        created_at = (reg.load(name) or {}).get("createdAt")
        cache.write_owner_projection(actor, name, [actor], [], created_at)
        reg.finalize(name, actor, request_id, "active")
    except Exception as exc:  # record failure, don't leave it dangling
        reason = str(exc)  # raw — kept in logs + the registry `failed` record
        friendly = _user_reason(exc)
        logger.error("create %s failed for %s: %s", name, actor, reason)
        # Record the failure in three INDEPENDENT best-effort steps: a failure in one
        # (e.g. slot rollback) must not skip the others — the cache `failed` write is
        # what the browser reads, so a failed create must never silently vanish.
        try:
            # Roll back the slot assigned above so a failed create doesn't leak one
            # toward the actor's membership cap. Idempotent: clear_slot only clears the
            # slot holding `name`, and is a no-op if none was assigned yet.
            membership.clear_slot(actor, name)
        except Exception:  # best-effort failure recording
            logger.exception("failed to roll back membership slot for %s", name)
        try:
            reg.finalize(name, actor, request_id, "failed", reason)
        except Exception:  # best-effort failure recording
            logger.exception("failed to record registry failure for %s", name)
        try:
            cache.upsert_entry(
                actor, {"name": name, "role": "owner", "status": "failed", "reason": friendly}
            )
        except Exception:  # best-effort failure recording
            logger.exception("failed to record cache failure for %s", name)
        # Emitted after the terminal `failed` status is recorded; best-effort — never
        # changes the Fail outcome. Friendly reason only (raw stays in log + registry).
        emit_notification(
            actor,
            f'We couldn\'t create shared workspace "{name}": {friendly}.',
            dedup_id=f"{request_id}:create-failed:{actor}",
        )
        raise
    emit_notification(
        actor,
        f'Your shared workspace "{name}" is ready.',
        dedup_id=f"{request_id}:create-active:{actor}",
    )
    return {"status": "active", "space": name, "owner": actor}


# @traced is the ONLY decorator on this plane: these verbs notify explicitly from inside
# the handler rather than via @notifies_on_failure, so the ordering rule that governs
# data-quality/table-builder/table-share does not apply here (SPEC-134 FR-002).
@observability.traced("create")
def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    result = create_space(space, actor, request_id)
    logger.info("create %s by %s -> %s", space, actor, result["status"])
    # The four stores this verb writes, named in order, because the plane's characteristic bug
    # is two of them disagreeing and the characteristic debugging session is reconstructing
    # which writes landed (#153-155, #163/#164, #165 were all that session).
    observability.info(
        "space created",
        space=space,
        actor=actor,
        status=result["status"],
        replayed=bool(result.get("replay")),
        stores=["registry", "glue", "lakeformation", "cache"],
    )
    return result
