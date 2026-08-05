"""Shared resource-teardown helpers for the shared-space control plane.

The idempotent S3 + Glue teardown steps used by BOTH the delete-space cascade and the
forget verb's cleanup of an owner's failed create. Every helper tolerates partial
prior progress / already-absent resources, so a re-run completes a half-done teardown.
Kept in the shared layer so the two verbs share one implementation.
"""

import logging

import config
from cpcommon import clients, errors
from cpcommon import config as cpconfig

logger = logging.getLogger()


class TeardownIncompleteError(Exception):
    """Some resources survived a teardown pass, so the space is NOT gone.

    Raised rather than logged because of what the caller does next: ``delete_space``
    finishes with ``reg.delete(space)``, commented "LAST — the name is now free to
    reuse". Freeing a name whose objects are still in the bucket means the next space
    created with that name inherits another tenant's data, and SPEC-054 states as an
    acceptance criterion that teardown leaves "never a dangling … half-deleted resource".

    Carries COUNTS, never the failed keys or table names: the field rule (SPEC-132) binds
    what a call site chooses to emit, and this message reaches logs and the registry's
    `failed` record. A count is enough to tell a partial failure from a total one.
    """


def delete_shared_prefix(name):
    """Recursively delete every object under ``{name}/`` in the shared-space bucket.

    Paginated list + batched delete, including the marker and every athenaresults/.
    Idempotent — an empty/absent prefix is a no-op.

    ``delete_objects`` RETURNS HTTP 200 WITH A PER-KEY ``Errors`` ARRAY: a key denied or
    failed individually does not raise, and discarding the response (as this did) made a
    partial delete indistinguishable from a complete one. ``Quiet=False`` is set
    explicitly so the array is populated — the same shape the browser's
    ``deleteInBatches`` already relies on (fileBrowser.service.ts:315).
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
        # Every page is attempted before raising: a denial on one key should not strand
        # the rest of the space's objects, and the count is only meaningful whole.
        raise TeardownIncompleteError(f"{failed} object(s) under {name}/ could not be deleted")


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

    ``batch_delete_table`` has the same shape as ``delete_objects``: it succeeds while
    reporting per-table failures in ``Errors``, so discarding the response let a database
    that still holds tables read as dropped. The ``delete_database`` below would then fail
    (or, worse, succeed and orphan the tables) — either way the caller must not go on to
    free the name.
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
    except Exception as err:  # retryable faults mapped; the rest propagate
        # A Glue transient here would otherwise fail the whole cascade permanently, and a
        # cascade that fails does NOT free the name (FR-003) — so the user is left with a
        # space stuck in `failed` over a hiccup the Retry would have absorbed.
        errors.raise_if_transient(err, f"glue get_tables {name}")
        raise
    failed = 0
    for i in range(0, len(tables), 100):
        response = glue.batch_delete_table(DatabaseName=name, TablesToDelete=tables[i : i + 100])
        failed += len((response or {}).get("Errors") or [])
    if failed:
        # Before delete_database, not after: dropping a database whose tables survived is
        # how the catalog and the bucket start disagreeing.
        raise TeardownIncompleteError(f"{failed} table(s) in {name} could not be dropped")
    try:
        glue.delete_database(Name=name)
    except glue.exceptions.EntityNotFoundException:
        pass
