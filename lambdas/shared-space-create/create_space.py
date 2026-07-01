"""create-space verb (SPEC-051; SPEC-062 single-task Lambda).

Provisions a new shared space owned by the actor: atomically reserve the globally
unique name (registry conditional create), assign the creator a membership slot,
create the shared prefix marker + Glue database, grant the shared portal role on the
DB, and write the registry + the creator's per-user cache. Every step tolerates
"already exists" (replay-safe); a mid-way failure records a terminal ``failed``
status (registry + the creator's cache) with a reason, then re-raises -> Fail.

Create is **creator-only** (SPEC-062 FR-006): it provisions only ``members:[actor]``
and takes no member list — members are added later via add-members (SPEC-053).
"""

import logging

import config
import clients
import cache
import membership
import registry as reg
from notify import emit_notification

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _ensure_marker(name):
    """Create the space's DO_NOT_DELETE.txt marker (mirrors SPEC-014). Idempotent."""
    clients.s3().put_object(
        Bucket=config.SHARED_SPACE_BUCKET,
        Key=f"{name}/DO_NOT_DELETE.txt",
        Body=b"This object marks a shared space. Do not delete.\n",
    )


def _ensure_database(name):
    glue = clients.glue()
    try:
        glue.create_database(DatabaseInput={"Name": name})
    except glue.exceptions.AlreadyExistsException:
        pass


def _grant_portal_role(name):
    """Grant the shared portal role full DB + table access on ``name`` (idempotent —
    LF GrantPermissions re-grants safely). DATA_LOCATION_ACCESS on the shared bucket
    is a one-time Terraform grant (shared-spaces/lakeformation.tf), not per-DB."""
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
    """Provision a new shared space owned by ``actor``. Idempotent; records a terminal
    failed status (registry + the owner's cache) on any error before re-raising."""
    try:
        outcome = reg.reserve(name, actor, request_id)  # may raise "name already taken"
    except Exception as exc:  # noqa: BLE001 - notify the actor, then fail
        # Reserve runs OUTSIDE the provisioning try/except below on purpose: a name
        # collision must NOT rewrite the registry/cache (the name isn't ours to record
        # `failed` against). But the actor still deserves to hear it failed, so emit the
        # failure notification here before re-raising (best-effort; never changes Fail).
        reason = str(exc)
        logger.error("create %s reserve failed for %s: %s", name, actor, reason)
        emit_notification(
            actor,
            f'We couldn\'t create shared workspace "{name}": {reason}.',
            dedup_id=f"{request_id}:create-failed:{actor}",
        )
        raise
    if outcome == "replay" and (reg.load(name) or {}).get("status") == "active":
        return {"status": "active", "space": name, "owner": actor, "replay": True}
    try:
        membership.assign_or_find_slot(actor, name)  # may raise "membership limit reached"
        _ensure_marker(name)
        _ensure_database(name)
        _grant_portal_role(name)
        # Seed the owner's member projection (SPEC-053) — just the owner at create.
        # Carry the registry's createdAt so the Connections card meta line can show it.
        created_at = (reg.load(name) or {}).get("createdAt")
        cache.write_owner_projection(actor, name, [actor], created_at)
        reg.finalize(name, actor, request_id, "active")
    except Exception as exc:  # noqa: BLE001 - record failure, don't leave it dangling
        reason = str(exc)
        logger.error("create %s failed for %s: %s", name, actor, reason)
        # Record the failure in three INDEPENDENT best-effort steps: a failure in one
        # (e.g. slot rollback) must not skip the others — the cache `failed` write in
        # particular is what the browser reads, so a create that failed must always be
        # recorded there rather than silently vanishing.
        try:
            # Roll back the membership slot assigned above so a failed create doesn't
            # leak a slot toward the actor's MAX_SHARED_MEMBERSHIPS cap (the slot was
            # claimed before the step that failed). Idempotent: clear_slot only clears
            # the slot holding `name`, and is a no-op if none was assigned yet.
            membership.clear_slot(actor, name)
        except Exception:  # noqa: BLE001 - best-effort failure recording
            logger.exception("failed to roll back membership slot for %s", name)
        try:
            reg.finalize(name, actor, request_id, "failed", reason)
        except Exception:  # noqa: BLE001 - best-effort failure recording
            logger.exception("failed to record registry failure for %s", name)
        try:
            cache.upsert_entry(
                actor, {"name": name, "role": "owner", "status": "failed", "reason": reason}
            )
        except Exception:  # noqa: BLE001 - best-effort failure recording
            logger.exception("failed to record cache failure for %s", name)
        # SPEC-061 event 2: notify the creator the create failed (after the terminal
        # `failed` status is recorded; best-effort — never changes the Fail outcome).
        emit_notification(
            actor,
            f'We couldn\'t create shared workspace "{name}": {reason}.',
            dedup_id=f"{request_id}:create-failed:{actor}",
        )
        raise
    # SPEC-061 event 1: notify the creator the workspace is ready (terminal `active`).
    emit_notification(
        actor,
        f'Your shared workspace "{name}" is ready.',
        dedup_id=f"{request_id}:create-active:{actor}",
    )
    return {"status": "active", "space": name, "owner": actor}


def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    result = create_space(space, actor, request_id)
    logger.info("create %s by %s -> %s", space, actor, result["status"])
    return result
