"""Shared resource-teardown helpers for the shared-space control plane.

The idempotent S3 and Glue teardown steps used by both the delete cascade and the forget verb's
cleanup of an owner's failed create. Every helper tolerates partial prior progress and
already-absent resources, so a re-run completes a half-done teardown. Kept in the shared layer
so the two verbs share one implementation.
"""

import logging

import config
from cpcommon import clients, errors
from cpcommon import config as cpconfig

logger = logging.getLogger()


class TeardownIncompleteError(Exception):
    """Some resources survived a teardown pass, so the space is not gone.

    Raised rather than logged because of what the caller does next: the delete verb finishes by
    deleting the registry record, which frees the name for reuse. Freeing a name whose objects
    are still in the bucket means the next space created with that name inherits another
    tenant's data, and teardown is specified to leave no half-deleted resource behind.

    Carries counts, never the failed keys or table names: the field rule binds what a call site
    chooses to emit, and this message reaches the logs and the registry's failure record. A
    count is enough to tell a partial failure from a total one.
    """


def delete_shared_prefix(name):
    """Recursively deletes every object under a space's prefix in the shared-space bucket.

    Paginated list plus batched delete, including the marker and every results folder.
    Idempotent — an empty or absent prefix is a no-op.

    The batch delete returns success with a per-key error array: a key denied or failed
    individually does not raise, and discarding the response made a partial delete
    indistinguishable from a complete one. The non-quiet mode is set explicitly so that array is
    populated.

    Args:
      name: The space name, which is also its prefix.

    Returns:
      None.

    Raises:
      TeardownIncompleteError: When any object could not be deleted. Every page is attempted
        first: a denial on one key should not strand the rest of the space's objects, and the
        count is only meaningful whole.
      ClientError: On any listing fault.
    """
    s3 = clients.s3()
    prefix = f"{name}/"
    token = None
    failed = 0
    while True:
        kwargs = {"Bucket": cpconfig.SHARED_SPACE_BUCKET, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objects:
            response = s3.delete_objects(
                Bucket=cpconfig.SHARED_SPACE_BUCKET,
                Delete={"Objects": objects, "Quiet": False},
            )
            failed += len(response.get("Errors") or [])
        if page.get("IsTruncated"):
            token = page.get("NextContinuationToken")
        else:
            break
    if failed:
        raise TeardownIncompleteError(f"{failed} object(s) under {name}/ could not be deleted")


def revoke_portal_role(name):
    """Best-effort revoke of the portal role's Lake Formation grants on a space.

    Cleanup only — per-user isolation is the IAM membership tag, not this grant — so a failure,
    such as the database already having been dropped on a retry, is logged and tolerated rather
    than fatal to the cascade.

    Args:
      name: The space name, which is also its database name.

    Returns:
      None.

    Raises:
      None.
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
        except Exception:  # noqa: BLE001
            logger.warning("LF revoke on %s (%s) failed; continuing", name, next(iter(resource)))


def drop_database(name):
    """Drops every table in a space's Glue database, then the database itself.

    Idempotent — a missing database or table is a no-op, already dropped.

    The batch table delete has the same shape as the object delete: it succeeds while reporting
    per-table failures, so discarding the response let a database that still holds tables read
    as dropped. The database delete would then fail, or worse succeed and orphan the tables —
    either way the caller must not go on to free the name.

    Args:
      name: The space name, which is also its database name.

    Returns:
      None.

    Raises:
      TeardownIncompleteError: When any table could not be dropped. Raised before the database
        delete, not after: dropping a database whose tables survived is how the catalog and the
        bucket start disagreeing.
      TransientError: On a retryable Glue fault while listing. Without that mapping a hiccup
        would fail the whole cascade permanently, and a failed cascade does not free the name,
        so the user would be left with a space stuck in a failed state over something the Retry
        would have absorbed.
      ClientError: On any deterministic Glue fault.
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
        return
    except Exception as err:
        errors.raise_if_transient(err, f"glue get_tables {name}")
        raise
    failed = 0
    for i in range(0, len(tables), 100):
        response = glue.batch_delete_table(DatabaseName=name, TablesToDelete=tables[i : i + 100])
        failed += len((response or {}).get("Errors") or [])
    if failed:
        raise TeardownIncompleteError(f"{failed} table(s) in {name} could not be dropped")
    try:
        glue.delete_database(Name=name)
    except glue.exceptions.EntityNotFoundException:
        pass
