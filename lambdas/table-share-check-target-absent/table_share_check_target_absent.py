"""check-target-absent — the recipient Map's conflict guard.

For one recipient: short-circuits a recipient the validate verb marked invalid, resolves the
destination by kind, and fails the recipient on a conflict — either the result table name
already exists in the recipient's database, or the destination prefix is non-empty, since
leftover data from a prior partial run must never be mixed into a new copy. Sharing back into
the source database under the same name self-conflicts here naturally. Read-only.

The service name is the control plane, not the function, so one share's invocations and its
Map fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import clients, config, observability
from cpcommon.errors import TerminalError, TransientError
from tscommon import glue as glue_mod
from tscommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-share")


def _resolve_destination(recipient: dict, table_name: str) -> dict:
    """Resolves the recipient's database and destination bucket and prefix by kind.

    Args:
      recipient: The recipient, carrying its kind and name.
      table_name: The result table name, which names the destination folder.

    Returns:
      The recipient enriched with its database, destination bucket and destination prefix.

    Raises:
      None.
    """
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
    """Reports whether a destination prefix holds no objects.

    Args:
      bucket: The destination bucket.
      prefix: The destination prefix.

    Returns:
      True when the prefix is empty.

    Raises:
      TransientError: On any listing fault. A failed check must retry, never pass.
    """
    s3 = clients.s3()
    try:
        page = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
    except Exception as exc:
        raise TransientError(f"list {bucket}/{prefix} failed: {exc}") from exc
    return page.get("KeyCount", 0) == 0


@observability.traced("check-target-absent")
@notify.notifies_on_failure("check")
def handler(event, context) -> dict:
    """Recipient-Map entry point: verifies the target is absent for this recipient.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    Args:
      event: The Map item, carrying the recipient and the request.
      context: The Lambda context, unused.

    Returns:
      The item with the recipient enriched with its resolved destination.

    Raises:
      TerminalError: The annotated reason for an invalid recipient, or ``conflict``. Both
        notify the sender before the per-recipient Catch records it.
      TransientError: On a listing fault.
    """
    return _check_target_absent(event)


def _check_target_absent(event) -> dict:
    """Short-circuits an invalid recipient, resolves the destination, and checks for conflicts.

    The verdict is recorded as an explicit boolean: this is a push with no consent step, so
    "the destination was empty before we wrote to it" is the only record that a share did not
    silently land on top of something.

    Args:
      event: The Map item.

    Returns:
      The item with the recipient enriched.

    Raises:
      TerminalError: The recipient's own annotated reason when the validate verb marked it
        invalid — landing here without touching Glue or S3 — or ``conflict`` when the table
        name is taken or the destination already holds data.
      TransientError: On a listing fault.
    """
    recipient = event.get("recipient") or {}
    request = event.get("request") or {}
    table_name = request.get("tableName")

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
    observability.info(
        "target absent",
        recipient=resolved["name"],
        recipient_kind=resolved["kind"],
        dest_bucket=resolved["destBucket"],
        dest_prefix=resolved["destPrefix"],
        exists=False,
    )
    return {"recipient": resolved, "request": request}
