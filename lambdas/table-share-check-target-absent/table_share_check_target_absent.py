"""check-target-absent — the recipient Map's conflict guard (SPEC-091).

For one recipient: short-circuit a recipient validate-authorize marked invalid
(unknown user/space → per-recipient terminal), resolve the destination
(user → {name}/shared_tables/{tableName}/ in the user-space bucket;
space → the shared-space bucket), and fail the recipient on a conflict — the
result table name already exists in the recipient database, OR the destination
prefix is non-empty (leftover data from a prior partial run must never be mixed
into a new copy). Sharing back into the source DB under the same name
self-conflicts here naturally (the source table exists). Read-only.

Emits the item state with the recipient enriched:
{recipient: {kind, name, valid, database, destBucket, destPrefix}, request: {…}}.
"""

import logging

from cpcommon import clients, config
from tscommon import notify
from tscommon import glue as glue_mod
from cpcommon.errors import TerminalError, TransientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _resolve_destination(recipient: dict, table_name: str) -> dict:
    """The recipient's database + destination bucket/prefix, by kind."""
    name = recipient.get("name")
    if recipient.get("kind") == "user":
        bucket = config.USER_SPACE_BUCKET
    else:
        bucket = config.SHARED_SPACE_BUCKET
    return {
        **recipient,
        "database": name,
        "destBucket": bucket,
        "destPrefix": f"{name}/shared_tables/{table_name}/",
    }


def _prefix_is_empty(bucket: str, prefix: str) -> bool:
    s3 = clients.s3()
    try:
        page = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
    except Exception as exc:  # noqa: BLE001 - a failed check must retry, never pass
        raise TransientError(f"list {bucket}/{prefix} failed: {exc}") from exc
    return page.get("KeyCount", 0) == 0


@notify.notifies_on_failure("check")
def handler(event, context) -> dict:
    # A terminal conflict / invalid-recipient failure notifies the sender before
    # the per-recipient Catch records it (SPEC-094, best-effort).
    try:
        return _check_target_absent(event)
    except TerminalError as err:
        notify.emit_failure(event, err, "check")
        raise


def _check_target_absent(event) -> dict:
    recipient = event.get("recipient") or {}
    request = event.get("request") or {}
    table_name = request.get("tableName")

    # SPEC-089 annotated this recipient invalid — its per-recipient terminal
    # failure lands here, without touching Glue/S3 (FR-001).
    if not recipient.get("valid"):
        raise TerminalError(
            recipient.get("reason") or "unknown_target",
            f"recipient {recipient.get('kind')}:{recipient.get('name')} is not a valid target",
        )

    resolved = _resolve_destination(recipient, table_name)

    if glue_mod.table_exists(resolved["database"], table_name):
        raise TerminalError(
            "conflict",
            f"a table named {table_name!r} already exists in {resolved['database']!r}",
        )
    if not _prefix_is_empty(resolved["destBucket"], resolved["destPrefix"]):
        raise TerminalError(
            "conflict",
            f"the destination {resolved['destPrefix']!r} already holds data",
        )

    logger.info(
        "target clear for %s:%s — %s/%s",
        resolved["kind"],
        resolved["name"],
        resolved["destBucket"],
        resolved["destPrefix"],
    )
    return {"recipient": resolved, "request": request}
