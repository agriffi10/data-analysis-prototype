"""build-transfer-manifest — the Distributed Map's dataset, and the last gate before bytes move.

Between the destination guard and the copy: takes the plan the expansion wrote and the outcome list
every verb before has carried, and writes one JSON Lines item per object of every item still
``cleared``. The Map fans out over those items, so an operation's ceiling is the manifest's length
rather than one Lambda's timeout.

**An item with any other outcome contributes ZERO lines.** Its terminal was decided before this verb
ran and nothing here may overwrite it — which is also why this verb re-checks no destination: the
guard is the only place that question is asked, and it has now been asked twice.

**THE DELETABILITY CHECK RUNS HERE, BEFORE THE TRANSFER, AND THAT PLACEMENT IS THE POINT.** For a
``move`` or a ``delete``, every one of an item's source keys is checked against what this plane may
actually remove — and an item that fails is refused having copied nothing. Run after the copy
instead, the same refusal would leave the item fully duplicated in the destination and undeletable
at the source, which is a state the user cannot resolve through this plane at all. The case is real
rather than theoretical: a personal-space folder holding a nested ``athenaresults/`` passes the
front door, because the browser's rule is root-anchored there, and expands with those objects in the
plan. The post-copy assertion in ``delete-source`` stays as defence in depth; this is the line of
defence that costs nothing.

A ``copy`` is not checked, deliberately: it deletes nothing, so what this plane may remove is not a
question about it.

**Every destination comes from the PLAN.** This verb composes no key — the expansion derived them
all, the guard checked exactly those, and a builder that derived its own would put objects
somewhere nobody checked rather than fail.

The service name is the control plane, not the function, so one operation's invocations and its Map
fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  _DELETING_OPERATIONS: The operations whose source is removed, and therefore the ones whose items
    must be deletable before anything is copied.
"""

import logging

from cpcommon import config, observability
from cpcommon.errors import TerminalError
from cpcommon.transfer import manifest as manifest_mod
from focommon import delete, notify, outcomes, plan

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-ops")

_DELETING_OPERATIONS = ("move", "delete")


def _cleared_keys(existing) -> set:
    """Returns the item keys still provisionally cleared after both guard passes.

    Args:
      existing: The outcome list as it arrived.

    Returns:
      The item keys whose current outcome is ``cleared``.

    Raises:
      None.
    """
    return {
        record["itemKey"]
        for record in (existing or [])
        if isinstance(record, dict) and record.get("outcome") == outcomes.CLEARED
    }


def _source_keys(item: dict) -> list:
    """Returns one planned item's absolute source keys.

    Args:
      item: One plan item.

    Returns:
      The source keys, in plan order.

    Raises:
      None.
    """
    return [obj["srcKey"] for obj in item["objects"] if obj.get("srcKey")]


def _refusal(item: dict, err: TerminalError) -> dict:
    """Turns a per-item deletability refusal into the outcome record that replaces its ``cleared``.

    Args:
      item: The plan item that was refused.
      err: The refusal, whose reason code is what the notification is worded from.

    Returns:
      The outcome record.

    Raises:
      None.
    """
    logger.info("item %s cannot be deleted: %s", item["itemKey"], err)
    return outcomes.outcome(item["itemKey"], item["label"], outcomes.PROTECTED, err.reason)


def _lines(item: dict) -> list:
    """Returns one item's manifest lines, one per object.

    **``size`` is not optional and is not defaulted here.** ``copy_batch`` reads
    ``item.get("size") or 0`` and takes the single ``CopyObject`` path below the multipart
    threshold, so an absent size sends every object down the single-copy path — and anything over
    5 GiB then comes back ``InvalidRequest``. The plan measured it; it travels.

    Args:
      item: One plan item, whose objects already carry their derived destinations.

    Returns:
      The transfer items, in the shape ``cpcommon.transfer`` copies and attributes. ``itemKey`` is
      the echoed attribution field, and it is bounded — a key, once, per line, never a list.

    Raises:
      KeyError: When a planned object is missing a location field. The plan reader has already
        refused a plan short of its objects, so this names a corruption rather than a shape the
        expansion can produce.
    """
    return [
        {
            "itemKey": item["itemKey"],
            "srcBucket": obj["srcBucket"],
            "srcKey": obj["srcKey"],
            "destBucket": obj["destBucket"],
            "destKey": obj["destKey"],
            "size": obj["size"],
        }
        for obj in item["objects"]
    ]


@observability.traced("build-transfer-manifest")
@notify.notifies_on_failure("build-transfer-manifest")
def handler(event, context) -> dict:
    """Step Functions entry point: writes the transfer manifest and reports its item count.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out, so
    if it were outermost the span would close as successful on an invocation that actually failed
    and notified.

    Args:
      event: The request, carrying the plan key, the execution's name and the outcome list.
      context: The Lambda context, unused.

    Returns:
      The request with a ``transfer`` block naming the manifest, the results prefix, the item count
      the Choice gates the Map on and the per-item line counts the collector reconciles against.

    Raises:
      TerminalError: ``plan_unreadable`` or ``plan_superseded`` when the plan is not this run's, or
        ``malformed_event`` when the execution name is absent.
      TransientError: On a retryable S3 fault writing the manifest.
    """
    return _build_transfer_manifest(event)


def _build_transfer_manifest(event) -> dict:
    """Expands the cleared items into manifest lines and writes them.

    Nothing is written when no item is cleared, and the manifest object is not created at all: it
    would be an empty file the Map is about to be told to skip. That path is the ordinary "every
    item was already refused" run, and — for a ``delete`` — the ordinary run full stop, since a
    delete copies nothing.

    Args:
      event: The validated request with its outcome list.

    Returns:
      The request with its ``transfer`` block and the COMPLETE outcome list, including any item
      this verb refused as undeletable.

    Raises:
      TerminalError: ``plan_unreadable``, ``plan_superseded`` or ``malformed_event``.
      TransientError: On a retryable S3 fault.
    """
    operation = event.get("operation")
    loaded = plan.load(event.get("planKey"), event)
    cleared = _cleared_keys(event.get("outcomes"))
    root = (loaded.get("source") or {}).get("root") or ""

    decided, items, lines = [], [], []
    for item in loaded["items"]:
        if item["itemKey"] not in cleared:
            continue
        if operation in _DELETING_OPERATIONS:
            try:
                delete.assert_item_deletable(_source_keys(item), root)
            except TerminalError as err:
                decided.append(_refusal(item, err))
                continue
        items.append(item)
        lines.extend(_lines(item) if operation != "delete" else [])

    results_prefix = plan.transfer_results_prefix(event)
    item_lines = [
        {"itemKey": item["itemKey"], "lines": item["objectCount"] if operation != "delete" else 0}
        for item in items
    ]

    key = ""
    if lines:
        key = plan.transfer_manifest_key(event, (event.get("execution") or {}).get("name"))
        manifest_mod.write_manifest(config.ADMIN_BUCKET, key, lines)

    logger.info(
        "transfer manifest for %s: %d line(s) from %d cleared item(s), %d refused",
        operation,
        len(lines),
        len(items),
        len(decided),
    )
    observability.info(
        "transfer manifest built",
        actor=(event.get("actor") or {}).get("username"),
        operation=operation,
        items=len(items),
        refused=len(decided),
        lines=len(lines),
    )
    return {
        **event,
        "transfer": {
            "manifestBucket": config.ADMIN_BUCKET,
            "manifestKey": key,
            "resultsBucket": config.ADMIN_BUCKET,
            "resultsPrefix": results_prefix,
            "itemCount": len(lines),
            "itemLines": item_lines,
        },
        "outcomes": outcomes.carry_forward(event.get("outcomes"), decided),
    }
