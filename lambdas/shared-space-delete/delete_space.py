"""delete-space verb (SPEC-054 cascade; SPEC-062 single-task Lambda).

Owner cascade-delete (irreversible). Flags the registry ``deleting`` first, then tears
down in a safe order: remove all shared objects, revoke the LF grant, drop all tables +
the Glue DB, clear every member's slot + cache entry, and finally delete the registry
object (LAST -> name freed). Every step is idempotent and tolerant of partial prior
progress, so a re-run completes a half-done teardown; the registry never returns to
``active`` mid-cascade. On a hard error it records a terminal ``failed`` status (registry
+ the owner's cache, with a reason) for the screen's Retry affordance, then re-raises
-> Fail.
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


def _delete_shared_prefix(name):
    """Recursively delete every object under ``{name}/`` in the shared-space bucket
    (paginated list + batched delete, incl. the marker and every athenaresults/).
    Idempotent — an empty/absent prefix is a no-op."""
    s3 = clients.s3()
    prefix = f"{name}/"
    token = None
    while True:
        kwargs = {"Bucket": config.SHARED_SPACE_BUCKET, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objects:
            s3.delete_objects(Bucket=config.SHARED_SPACE_BUCKET, Delete={"Objects": objects})
        if page.get("IsTruncated"):
            token = page.get("NextContinuationToken")
        else:
            break


def _revoke_portal_role(name):
    """Best-effort revoke of the shared portal role's LF grants on ``name`` (DB +
    table wildcard). Cleanup only — per-user isolation is the IAM membership tag, not
    this grant — so a failure (e.g. the DB already dropped on a retry) is logged and
    tolerated, never fatal to the cascade."""
    lf = clients.lf()
    for resource, permissions in (
        ({"Database": {"Name": name}}, config.DATABASE_PERMISSIONS),
        ({"Table": {"DatabaseName": name, "TableWildcard": {}}}, config.TABLE_PERMISSIONS),
    ):
        try:
            lf.revoke_permissions(
                Principal={"DataLakePrincipalIdentifier": config.PORTAL_ROLE_ARN},
                Resource=resource,
                Permissions=permissions,
            )
        except Exception:  # noqa: BLE001 - best-effort cleanup
            logger.warning("LF revoke on %s (%s) failed; continuing", name, next(iter(resource)))


def _drop_database(name):
    """Drop every table in the Glue database ``name`` (paginated, batched) then the
    database itself. Idempotent — a missing DB/table is a no-op (already dropped)."""
    glue = clients.glue()
    try:
        tables = []
        token = None
        while True:
            kwargs = {"DatabaseName": name}
            if token:
                kwargs["NextToken"] = token
            page = glue.get_tables(**kwargs)
            tables.extend(t["Name"] for t in page.get("TableList", []))
            token = page.get("NextToken")
            if not token:
                break
    except glue.exceptions.EntityNotFoundException:
        return  # database already gone
    for i in range(0, len(tables), 100):
        glue.batch_delete_table(DatabaseName=name, TablesToDelete=tables[i : i + 100])
    try:
        glue.delete_database(Name=name)
    except glue.exceptions.EntityNotFoundException:
        pass


def delete_space(space, actor, request_id, registry):
    owner = registry["owner"]
    members = list(registry.get("members", []))
    reg.set_status(registry, "deleting", request_id)
    try:
        _delete_shared_prefix(space)
        _revoke_portal_role(space)
        _drop_database(space)
        for member in members:
            membership.clear_slot(member, space)
            cache.remove_entry(member, space)
        reg.delete(space)  # LAST — the name is now free to reuse
    except Exception as exc:  # noqa: BLE001 - record failure, don't leave it dangling
        reason = str(exc)
        logger.error("delete %s failed: %s", space, reason)
        try:
            reg.set_status(registry, "failed", request_id, reason)
        except Exception:  # noqa: BLE001 - best-effort failure recording
            logger.exception("failed to record registry delete failure for %s", space)
        try:
            cache.upsert_entry(
                owner, {"name": space, "role": "owner", "status": "failed", "reason": reason}
            )
        except Exception:  # noqa: BLE001 - best-effort failure recording
            logger.exception("failed to record cache delete failure for %s", space)
        # Notify the owner the delete failed (parity with create-failed) — the delete
        # card's Retry affordance reads the failed cache entry, and the owner otherwise
        # hears nothing because the success fan-out below is never reached.
        emit_notification(
            owner,
            f'We couldn\'t delete the shared workspace "{space}": {reason}.',
            dedup_id=f"{request_id}:delete-failed:{owner}",
        )
        raise
    # SPEC-061 event 7: fan out one notification per member (the list was captured
    # BEFORE the cascade cleared the registry; owner ∈ members), deduplicated so each
    # user gets exactly one. The deleter (actor) gets a distinct "you deleted" message;
    # every other member gets "was deleted". Emitted only here — past the terminal
    # success; a failed/partial cascade re-raises above and emits nothing. Each emit is
    # best-effort (FR-002), so one failure never aborts the fan-out to the rest.
    for recipient in dict.fromkeys(members):
        message = (
            f'You deleted the shared workspace "{space}".'
            if recipient == actor
            else f'The shared workspace "{space}" was deleted.'
        )
        emit_notification(recipient, message, dedup_id=f"{request_id}:delete:{recipient}")
    logger.info("delete %s by %s: cascade complete (%d members revoked)", space, actor, len(members))
    return {"status": "ok", "action": "delete", "space": space, "revokedMembers": members}


def handler(event, context):
    """``event`` is the validated context from the validator (via the Choice state)."""
    space = event["space"]
    actor = event["actor"]
    request_id = event.get("requestId")
    registry = event["registry"]
    return delete_space(space, actor, request_id, registry)
