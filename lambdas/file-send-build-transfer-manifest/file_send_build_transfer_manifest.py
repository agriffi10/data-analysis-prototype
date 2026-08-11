"""build-transfer-manifest — the Distributed Map's dataset.

Between the guard and the copy: takes the copy plan inspect-source wrote and the recipients the
guard cleared, and writes one JSON Lines item per ``(recipient, object)`` pair to the admin
bucket. The Map fans out over those items, so a send's ceiling is the manifest's length rather
than one Lambda's timeout.

A recipient the guard refused contributes NO lines. Its terminal outcome was decided before this
verb ran and nothing here may overwrite it — which is also why this verb never re-checks a
destination: the guard is the only place that question is asked.

**Every destination comes from ``fscommon.paths.destination_key``**, called once per
``(recipient, object)`` pair with the root the guard resolved. This verb composes no key of its
own, and an AST sweep enforces that rather than trusting it: the layout is what a recipient sees
forever, and a builder that disagreed would put files in the wrong inbox rather than fail.

The service name is the control plane, not the function, so one send's invocations and its Map
fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import config, observability
from cpcommon.transfer import manifest
from fscommon import copy_plan, notify, paths

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-send")


def _accepted(guard_results) -> list:
    """Reads the resolved recipients the guard Map cleared.

    Args:
      guard_results: The guard Map's per-recipient records.

    Returns:
      The resolved recipient objects, each carrying the destination bucket and root
      check-target-absent worked out.

    Raises:
      None.
    """
    return [
        entry["recipient"]
        for entry in guard_results or []
        if isinstance(entry, dict)
        and entry.get("status") == "ok"
        and isinstance(entry.get("recipient"), dict)
    ]


def _items(recipients: list, plan: dict) -> list:
    """Expands the copy plan across the accepted recipients.

    The recipient loop is the OUTER one so a recipient's objects are adjacent in the manifest,
    which is what makes an ``ItemBatcher`` batch usually belong to one recipient — a batch that
    fails as a whole then costs one recipient rather than eight.

    Args:
      recipients: The accepted, resolved recipients.
      plan: The copy plan, carrying its source location, its sender and its objects.

    Returns:
      One transfer item per (recipient, object) pair, in the shape ``cpcommon.transfer`` copies
      and attributes: the recipient's ``(kind, name)`` pair travels with every line, because a
      destination is that pair and nothing stops a shared space being named after a user.

    Raises:
      TerminalError: ``forbidden`` from the destination builder for a recipient with no resolved
        root or an object with no item name.
    """
    src_bucket = (plan.get("source") or {}).get("bucket")
    sender = plan["sender"]
    return [
        {
            "recipient": recipient.get("name"),
            "kind": recipient.get("kind"),
            "srcBucket": src_bucket,
            "srcKey": obj["srcKey"],
            "destBucket": recipient.get("destBucket"),
            "destKey": paths.destination_key(
                recipient.get("destRoot") or "", sender, obj["item"], obj.get("relKey") or ""
            ),
            "size": obj.get("size") or 0,
        }
        for recipient in recipients
        for obj in plan["objects"]
    ]


@observability.traced("build-transfer-manifest")
@notify.notifies_on_failure("manifest")
def handler(event, context) -> dict:
    """Step Functions entry point: writes the transfer manifest and reports its item count.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Args:
      event: The request, carrying the copy plan key and the guard Map's results.
      context: The Lambda context, unused.

    Returns:
      The request with a ``transfer`` block naming the manifest, the results prefix and the item
      count the Choice gates the Map on.

    Raises:
      TerminalError: ``copy_failed`` when the copy plan cannot be read, or ``forbidden`` from
        the destination builder. Whole-request either way — a manifest that cannot be built
        completely must not be built partially.
      TransientError: On a retryable S3 fault writing the manifest.
    """
    return _build_transfer_manifest(event)


def _build_transfer_manifest(event) -> dict:
    """Expands the plan across the accepted recipients and writes the manifest.

    Nothing is written when no recipient was accepted, and the plan is not even read: the object
    would be an empty file the Map is about to be told to skip. That path is the ordinary
    "everybody already had it" send, not an error.

    Args:
      event: The request with its guard results.

    Returns:
      The request with its ``transfer`` block. The guard results are carried through untouched:
      the collector reads them to shape every recipient's outcome, including the refused ones
      that contributed no lines here.

    Raises:
      TerminalError: ``copy_failed`` or ``forbidden``.
      TransientError: On a retryable S3 fault.
    """
    recipients = _accepted(event.get("guardResults"))
    results_prefix = copy_plan.transfer_results_prefix(event)

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

    plan = copy_plan.load(event.get("copyPlanKey"))
    items = _items(recipients, plan)
    key = copy_plan.transfer_manifest_key(event)
    count = manifest.write_manifest(config.ADMIN_BUCKET, key, items)

    logger.info("transfer manifest %s: %d items for %d recipients", key, count, len(recipients))
    observability.info(
        "transfer manifest built",
        recipients=len(recipients),
        objects=len(plan["objects"]),
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
