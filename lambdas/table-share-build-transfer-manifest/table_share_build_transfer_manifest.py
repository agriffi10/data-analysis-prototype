"""build-transfer-manifest — the Distributed Map's dataset.

Between the guard Map and the transfer: takes the copy plan inspect-source wrote and the
recipients check-target-absent cleared, and writes one JSON Lines item per
``(recipient, object)`` pair to the admin bucket. The Map fans out over those items, so the
share's ceiling stops being one Lambda's timeout and becomes the manifest's length.

A recipient the guard refused contributes no lines and is carried forward untouched — its
terminal outcome was decided before this verb ran and nothing here may overwrite it.

The manifest key is unique to ONE EXECUTION, unlike the copy plan it sits beside. Two
overlapping executions share a request digest, and their accepted-recipient sets can differ,
so a shared key would let one execution's Map Run copy for a recipient the other's guard had
just refused as a conflict.

The service name is the control plane, not the function, so one share's invocations and its
Map fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import config, observability
from cpcommon.transfer import manifest
from tscommon import copy_plan, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-share")


def _accepted(guard_results: list) -> list:
    """Reads the resolved recipients the guard Map cleared.

    Args:
      guard_results: The guard Map's per-recipient records.

    Returns:
      The resolved recipient objects, each carrying its destination bucket and prefix.

    Raises:
      None.
    """
    return [
        entry["recipient"]
        for entry in guard_results
        if isinstance(entry, dict)
        and entry.get("status") == "ok"
        and isinstance(entry.get("recipient"), dict)
    ]


def _items(recipients: list, location: dict, objects: list) -> list:
    """Expands the copy plan across the accepted recipients.

    The destination is the recipient's own resolved prefix plus the object's relative key —
    the same two strings the per-recipient copy concatenated before this spec, so a
    recipient's data lands byte-identically where it always did.

    Args:
      recipients: The accepted, resolved recipients.
      location: The source location, carrying its bucket and prefix.
      objects: The planned source objects, each with a relative key and size.

    Returns:
      One transfer item per (recipient, object) pair.

    Raises:
      None.
    """
    src_bucket, src_prefix = location.get("bucket"), location.get("prefix")
    return [
        {
            "recipient": recipient.get("name"),
            "kind": recipient.get("kind"),
            "srcBucket": src_bucket,
            "srcKey": f"{src_prefix}{obj['relKey']}",
            "destBucket": recipient.get("destBucket"),
            "destKey": f"{recipient.get('destPrefix')}{obj['relKey']}",
            "size": obj.get("size", 0),
        }
        for recipient in recipients
        for obj in objects
    ]


@observability.traced("build-transfer-manifest")
@notify.notifies_on_failure("manifest")
def handler(event, context) -> dict:
    """Step Functions entry point: writes the transfer manifest and reports its item count.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    Args:
      event: The request, carrying the copy plan key, the source location, the guard Map's
        results and the stamped execution.
      context: The Lambda context, unused.

    Returns:
      The request with a ``transfer`` block naming the manifest, the results prefix and the
      item count the Choice gates the Map on.

    Raises:
      TerminalError: ``copy_failed`` when the copy plan cannot be read.
      TransientError: On a retryable S3 fault writing the manifest.
    """
    return _build_transfer_manifest(event)


def _build_transfer_manifest(event) -> dict:
    """Expands the plan across the accepted recipients and writes the manifest.

    Nothing is written when no recipient was accepted: the object would be an empty file the
    Map is about to be told to skip, and the copy plan is not even read, so a request whose
    recipients all conflicted costs one S3 call less than it did.

    Args:
      event: The request with its guard results and stamped execution.

    Returns:
      The request with its ``transfer`` block.

    Raises:
      TerminalError: ``copy_failed`` when the copy plan cannot be read.
      TransientError: On a retryable S3 fault writing the manifest.
    """
    execution_name = (event.get("execution") or {}).get("name")
    recipients = _accepted(event.get("guardResults") or [])
    results_prefix = copy_plan.transfer_results_prefix(event, execution_name)

    if not recipients:
        logger.info("no recipient cleared the guard; no transfer manifest written")
        observability.info("transfer manifest skipped", recipients=0, items=0)
        return {
            **event,
            "transfer": {
                "manifestBucket": config.ADMIN_BUCKET,
                "manifestKey": "",
                "resultsBucket": config.ADMIN_BUCKET,
                "resultsPrefix": results_prefix,
                "itemCount": 0,
            },
        }

    objects = copy_plan.load(event.get("copyPlanKey"))
    items = _items(recipients, event.get("location") or {}, objects)
    key = copy_plan.transfer_manifest_key(event, execution_name)
    count = manifest.write_manifest(config.ADMIN_BUCKET, key, items)

    logger.info("transfer manifest %s: %d items for %d recipients", key, count, len(recipients))
    observability.info(
        "transfer manifest built",
        recipients=len(recipients),
        objects=len(objects),
        items=count,
    )
    return {
        **event,
        "transfer": {
            "manifestBucket": config.ADMIN_BUCKET,
            "manifestKey": key,
            "resultsBucket": config.ADMIN_BUCKET,
            "resultsPrefix": results_prefix,
            "itemCount": count,
        },
    }
