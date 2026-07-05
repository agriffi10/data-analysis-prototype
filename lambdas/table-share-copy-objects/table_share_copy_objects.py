"""copy-objects — the recipient Map's data copy (SPEC-091).

For one (conflict-cleared) recipient: server-side-copy every planned object from
the source location to {recipient}/shared_tables/{tableName}/{relKey}, layout
preserved (flat files and key=value/ partition dirs land identically), with a
bounded parallel pool and multipart copy for objects over S3's 5 GiB single-copy
limit (tscommon.copy). Idempotent: a Step Function retry re-copies the same keys
harmlessly — check-target-absent already guaranteed the destination held no
foreign data. No object bytes pass through the Lambda.
"""

import logging

from tscommon import copy as copy_mod

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context) -> dict:
    recipient = event.get("recipient") or {}
    request = event.get("request") or {}
    location = request.get("location") or {}
    objects = request.get("objects") or []

    copied = copy_mod.copy_prefix(
        src_bucket=location.get("bucket"),
        src_prefix=location.get("prefix"),
        objects=objects,
        dest_bucket=recipient.get("destBucket"),
        dest_prefix=recipient.get("destPrefix"),
    )
    logger.info(
        "copied %d objects to %s/%s",
        copied,
        recipient.get("destBucket"),
        recipient.get("destPrefix"),
    )
    return {"recipient": recipient, "request": request, "copiedObjects": copied}
