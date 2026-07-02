"""Shared resource-teardown helpers for the shared-space control plane.

The idempotent S3 + Glue teardown steps used by BOTH the delete-space cascade and the
forget verb's cleanup of an owner's failed create. Every helper tolerates partial
prior progress / already-absent resources, so a re-run completes a half-done teardown.
Kept in the shared layer so the two verbs share one implementation.
"""

import logging

import config
import clients

logger = logging.getLogger()


def delete_shared_prefix(name):
    """Recursively delete every object under ``{name}/`` in the shared-space bucket.

    Paginated list + batched delete, including the marker and every athenaresults/.
    Idempotent — an empty/absent prefix is a no-op.
    """
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


def revoke_portal_role(name):
    """Best-effort revoke of the portal role's LF grants on ``name`` (DB + table wildcard).

    Cleanup only — per-user isolation is the IAM membership tag, not this grant — so a
    failure (e.g. the DB already dropped on a retry) is logged and tolerated, never
    fatal to the cascade.
    """
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


def drop_database(name):
    """Drop every table in Glue database ``name`` (paginated, batched), then the DB itself.

    Idempotent — a missing DB/table is a no-op (already dropped).
    """
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
