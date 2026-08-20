"""inspect-source — resolves the validated selection into the copy plan.

Given the validated request: expands each selected item under the authorized source root, lists
folders through their pagination boundary, applies this plane's exclusions, derives where every
object lands, enforces the expansion caps and writes the plan to S3. Read-only, with no copy or
delete side effect.

**Nothing it produces rides on the state.** At ``FILE_OPS_MAX_OBJECTS`` the object list is tens of
megabytes against a 256 KB payload limit, so the plan goes to the admin bucket and its key is
threaded onward. What stays on the state is the counts and the per-item outcome list.

**THE ITEMS AN EARLIER VERB DECIDED ARE NEVER SEEN HERE, AND THAT IS A RULE RATHER THAN AN
OPTIMISATION.** validate-authorize owns the same-key comparison — it is one of its ordered checks —
and re-deriving it here would be a second implementation of a security-adjacent rule. Worse, an
item whose destination IS its source has a destination subtree that is its own source subtree, so
expanding it would have the destination guard report every one of its objects as a collision and
flip a reported success into a refusal.

**A REFUSAL IS PER ITEM UNLESS IT IS A STATEMENT ABOUT THE REQUEST.** A missing file and an item
that holds nothing fail alone and every other item proceeds — the browser has always carried on
with the rest, and a select-all delete must still delete what it may. Two selected items where one
contains the other, and every cap, fail the whole request: neither of the overlapping items is the
wrong one, and a cap read per item would let a request approach the bound by attrition.

The service name is the control plane, not the function, so one operation's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  _PORTAL_MANAGED_FOLDERS: The folders the portal owns AT A SPACE ROOT, swept out of an expansion
    that reaches them from above. The rule is a deliberate SECOND one rather than a duplicate of
    the selection rule: that one anchors on the item the user named, and selecting an ANCESTOR is
    not covered by it. Different anchor, different question.
"""

import logging

from cpcommon import clients, errors, observability, s3_listing
from cpcommon.errors import TerminalError
from cpcommon.paths import assert_inside_root, normalize_root
from focommon import notify, outcomes, paths, plan
from focommon.config import (
    ATHENA_RESULTS_FOLDER,
    FILE_OPS_MAX_OBJECT_BYTES,
    FILE_OPS_MAX_OBJECTS,
    FILE_OPS_MAX_TOTAL_BYTES,
    MARKER_BASENAME,
    USER_SETTINGS_FOLDER,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-ops")

_PORTAL_MANAGED_FOLDERS = (ATHENA_RESULTS_FOLDER, USER_SETTINGS_FOLDER)


def _excluder(root: str, item_key: str):
    """Builds the ignore predicate for one selected item.

    **A closed enumeration of four rules, two of which the shared helper would otherwise decide by
    default.** Every omission here is silent, so they are stated rather than inherited:

      - the undeletable marker, at any depth, is EXCLUDED rather than refused. Both bucket policies
        deny deleting it, ``saved_queries/`` ships one, and the browser partitions the root marker
        out as a per-key error and deletes everything else — so failing a whole folder on a nested
        marker is a regression the browser never had;
      - the portal-managed folders at the SPACE ROOT are excluded, so an expansion reaching them
        from above does not sweep the notification inbox and the connections cache into a move;
      - **zero-byte folder placeholders are KEPT**, so an empty subfolder survives an operation
        that is meant to preserve a folder's shape;
      - **hidden segments are KEPT**, because a user's own ``_drafts/`` is theirs.

    The last two are why ``cpcommon.s3_listing.is_ignored`` — the DEFAULT predicate — cannot be
    used: it drops every ``size == 0`` object and every ``_``- or ``.``-prefixed segment, and taking
    the default would lose both without a refusal or a message.

    **The managed-folder rule does not fire when the item IS one of those folders or sits inside
    one**, and that carve-out is the whole difference between a rule and a silent capability
    removal. Copying *out of* ``athenaresults/`` is permitted on purpose — the selection rules
    refuse it as a delete or move source and deliberately not as a copy source — so a root-anchored
    exclusion applied to a legally selected ``alice/athenaresults/`` would list its every object,
    exclude every one of them, and report the item as empty.

    Args:
      root: The normalised authorized space root.
      item_key: The selected item's key, which is also the listing prefix.

    Returns:
      A predicate matching ``list_data_records``' ``ignore`` contract.

    Raises:
      None.
    """
    managed = tuple(
        anchored
        for folder in _PORTAL_MANAGED_FOLDERS
        for anchored in (f"{root}{folder}/",)
        if not item_key.startswith(anchored)
    )

    def ignore(key: str, size: int, prefix: str) -> bool:
        """Reports whether a listed object is something other than data this operation moves.

        Args:
          key: The absolute object key.
          size: The object's byte size, unused — a folder placeholder is carried, not dropped.
          prefix: The listing prefix, unused: both rules are anchored elsewhere.

        Returns:
          True for the undeletable marker at any depth, or a portal-managed folder at the root.

        Raises:
          None.
        """
        del size, prefix
        if key.rsplit("/", 1)[-1] == MARKER_BASENAME:
            return True
        return key.startswith(managed)

    return ignore


def _collapse(items: list) -> list:
    """Drops repeats of the same item, preserving the order the request gave.

    A repeat is a duplicate, not an overlap: the same item listed twice has exactly one right
    answer and no ambiguity about what the user meant.

    **The identity is ``(kind, key)``, and the key alone is not enough.** validate-authorize
    normalises a ``folder`` key to a trailing slash and leaves a ``file`` key exactly as it arrived,
    so one key can arrive with two kinds. Collapsing on the key kept whichever came first and
    dropped the other — a request naming both then carried one zero-byte placeholder and none of
    the folder's contents, reported success, and the outcome depended on the order of the list.
    Keyed on the pair, both survive to the overlap rule, which refuses them.

    Args:
      items: The normalised selection.

    Returns:
      The selection with repeated items removed.

    Raises:
      None.
    """
    seen, collapsed = set(), []
    for entry in items:
        identity = (entry["kind"], entry["key"])
        if identity in seen:
            continue
        seen.add(identity)
        collapsed.append(entry)
    return collapsed


def _assert_no_overlap(items: list) -> None:
    """Refuses a selection in which one item contains another.

    Both alternatives are worse than a refusal. Copying an object twice writes it once inside its
    folder's destination and once beside it, which nobody asked for; silently dropping one means
    the operation quietly did less than it said. The user can express either intention exactly by
    selecting differently.

    A WHOLE-REQUEST refusal, because it is a property of the request rather than of an item:
    neither of the two is the wrong one, so there is no item to fail.

    Args:
      items: The collapsed selection.

    Returns:
      None.

    Raises:
      TerminalError: ``overlapping_items`` naming both keys.
    """
    for outer in items:
        if not outer["key"].endswith("/"):
            continue
        for inner in items:
            if inner is outer or not inner["key"].startswith(outer["key"]):
                continue
            raise TerminalError(
                "overlapping_items", f"{inner['key']!r} is already inside {outer['key']!r}"
            )


def _head(bucket: str, key: str) -> tuple[int, str]:
    """Reads one selected file's size and ETag.

    **The shared helper cannot serve this, twice over.** ``cpcommon.s3_listing.object_size`` returns
    an ``int`` and discards the ETag from the very response that carried it, and it raises a
    WHOLE-REQUEST terminal where this plane owes a per-item outcome.

    Args:
      bucket: The source bucket.
      key: The selected file's key.

    Returns:
      ``(size, etag)``.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the verb.
      TerminalError: ``source_missing`` naming the key, which the caller catches and records
        against the one item rather than the request.
    """
    try:
        head = clients.s3().head_object(Bucket=bucket, Key=key)
    except Exception as err:
        errors.raise_if_transient(err, f"head {bucket}/{key}")
        raise TerminalError("source_missing", f"{key!r}: {err}") from err
    return int(head["ContentLength"]), head.get("ETag")


def _assert_within_caps(objects: int, total_bytes: int, size: int) -> None:
    """Refuses an expansion that has grown past what the run can carry.

    **Checked INSIDE the walk, not after it.** The object list accumulates in memory as it grows,
    so a cap checked afterwards is one the verb has already paid for — a folder of ten million
    objects would exhaust the Lambda before the check that exists to refuse it ever ran. The cost is
    that a refusal cannot name the true total, since nothing counted the rest; it names what it had
    reached and says it was still counting.

    Args:
      objects: How many objects the expansion has reached.
      total_bytes: How many bytes those objects hold.
      size: The object just added, which the per-object cap is about.

    Returns:
      None.

    Raises:
      TerminalError: ``object_too_large``, ``too_many_objects`` or
        ``selection_too_large_to_expand``, each naming the measured value and the cap.
    """
    if size > FILE_OPS_MAX_OBJECT_BYTES:
        raise TerminalError(
            "object_too_large",
            f"an object of {size} bytes is over the per-object cap of {FILE_OPS_MAX_OBJECT_BYTES}",
        )
    if objects > FILE_OPS_MAX_OBJECTS:
        raise TerminalError(
            "too_many_objects",
            f"the selection reached {objects} objects and was still counting, over the cap of "
            f"{FILE_OPS_MAX_OBJECTS}",
        )
    if total_bytes > FILE_OPS_MAX_TOTAL_BYTES:
        raise TerminalError(
            "selection_too_large_to_expand",
            f"the selection reached {total_bytes} bytes and was still counting, over the cap of "
            f"{FILE_OPS_MAX_TOTAL_BYTES}",
        )


def _object(source: dict, destination: dict | None, item: dict, record: dict, rel_key: str) -> dict:
    """Builds one plan entry, destination included.

    The fields are enumerated rather than described as "what the transfer needs": the copy reads
    the two bucket names per item, the deletion reads the source key and its ETag, and "what the
    manifest builder needs" is not a testable phrase.

    The ETag comes from the listing that found the object, at zero marginal cost, and it is what
    lets the deletion be conditional — an object mutated between the plan and the copy fails its
    own precondition and becomes one item's failure rather than a silent overwrite.

    Args:
      source: The authorized source, carrying the bucket.
      destination: The authorized destination, or None for a delete.
      item: The selected item, carrying its kind and its destination name.
      record: The listing's own ``{"key", "size", "etag"}``.
      rel_key: The object's key relative to the selected item.

    Returns:
      The plan entry.

    Raises:
      TerminalError: ``invalid_target_name`` from the destination builder.
    """
    entry = {
        "srcBucket": source["bucket"],
        "srcKey": record["key"],
        "relKey": rel_key,
        "size": record["size"],
        "etag": record["etag"],
    }
    if destination is None:
        return entry
    entry["destBucket"] = destination["bucket"]
    entry["destKey"] = paths.destination_key(
        destination["prefix"], item["targetName"], rel_key, is_folder=item["kind"] == "folder"
    )
    return entry


def _expand_item(
    source: dict, destination: dict | None, item: dict, reached: tuple[int, int]
) -> tuple[list, int]:
    """Resolves one selected item into its objects, in plan order.

    A ``file`` resolves to exactly itself with an empty relative key; a ``folder`` is walked
    recursively through the shared paginator, never assuming one page is the whole folder — S3
    returns at most 1,000 keys per page, and a folder over that boundary is the realistic case this
    plane exists for.

    **Every key that comes back from S3 is re-checked for containment.** validate-authorize checked
    the REQUEST's keys, which the caller supplied; these arrive from a ``ListObjectsV2`` response,
    and the two are not the same assurance. Nothing known makes S3 return a key outside the prefix
    it was asked for — the value of the check is that the rule holds for what is actually planned.

    Args:
      source: The authorized source, carrying the bucket and root.
      destination: The authorized destination, or None for a delete.
      item: One normalised selection item, carrying its resolved destination name.
      reached: ``(objects, bytes)`` the walk had already reached before this item, so the caps
        bound the whole selection rather than each item separately — ten folders of three thousand
        objects is over the cap, and per-item arithmetic would admit it.

    Returns:
      ``(objects, total_bytes)`` for this item alone.

    Raises:
      TerminalError: ``source_missing`` for an absent file, a cap reason, or ``forbidden`` for a
        listed key that fails the re-check.
      TransientError: On a retryable S3 fault.
    """
    bucket, root = source["bucket"], normalize_root(source["root"])
    key = item["key"]
    objects: list = []
    total_bytes = 0

    if item["kind"] == "file":
        size, etag = _head(bucket, key)
        records = [({"key": key, "size": size, "etag": etag}, "")]
    else:
        records = (
            (record, paths.relative_key(key, assert_inside_root(root, record["key"])))
            for record in s3_listing.list_data_records(bucket, key, ignore=_excluder(root, key))
        )

    for record, rel_key in records:
        objects.append(_object(source, destination, item, record, rel_key))
        total_bytes += record["size"]
        _assert_within_caps(
            reached[0] + len(objects), reached[1] + total_bytes, record["size"]
        )
    return objects, total_bytes


def _expand(event: dict, items: list) -> tuple[list, list]:
    """Expands every item that reached this verb, and decides each one's outcome.

    Args:
      event: The validated request.
      items: The collapsed selection, minus everything an earlier verb decided.

    Returns:
      ``(plan_items, decided)`` — the items that expanded to something, and one outcome record per
      item this verb saw.

    Raises:
      TerminalError: A cap or containment reason, which fails the whole request.
      TransientError: On a retryable S3 fault.
    """
    source, destination = event["source"], event.get("destination")
    plan_items, decided = [], []
    total_objects = 0
    total_bytes = 0

    for item in items:
        label = paths.item_name(item["key"])
        requested = item.get("targetName")
        resolved = {
            **item,
            "targetName": paths.validate_target_name(requested) if requested is not None else label,
        }
        try:
            objects, item_bytes = _expand_item(
                source, destination, resolved, (total_objects, total_bytes)
            )
        except TerminalError as err:
            if err.reason != "source_missing":
                raise
            decided.append(outcomes.outcome(item["key"], label, outcomes.SOURCE_MISSING, err.reason))
            continue

        if not objects:
            decided.append(outcomes.outcome(item["key"], label, outcomes.SOURCE_EMPTY, "source_empty"))
            continue

        total_objects += len(objects)
        total_bytes += item_bytes
        plan_items.append(
            {
                "itemKey": item["key"],
                "label": label,
                "kind": item["kind"],
                "targetName": resolved["targetName"],
                "objects": objects,
                "objectCount": len(objects),
                "totalBytes": item_bytes,
            }
        )
        decided.append(outcomes.outcome(item["key"], label, outcomes.CLEARED))
    return plan_items, decided


@observability.traced("inspect-source")
@notify.notifies_on_failure("inspect")
def handler(event, context) -> dict:
    """Step Functions entry point: expands the selection and writes the copy plan.

    A thin shim; the orchestration lives below so it is testable without a Lambda context.
    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out, so
    if it were outermost the span would close as successful on an invocation that actually failed
    and notified.

    Args:
      event: The validated request, carrying the authorized source, its normalised items and the
        outcome list validate-authorize created.
      context: The Lambda context, unused.

    Returns:
      The request merged with the plan key, the three counts and the COMPLETE outcome list.

    Raises:
      TerminalError: ``overlapping_items``, a cap reason, ``request_id_reused`` or a containment
        reason — each a whole-request failure, notified before the Catch records it.
      TransientError: On a retryable S3 fault.
    """
    return _inspect_source(event)


def _inspect_source(event) -> dict:
    """Expands the selection, enforces the caps and writes the plan.

    Args:
      event: The validated request.

    Returns:
      The request merged with the plan key, the counts and the carried-forward outcomes.

    Raises:
      TerminalError: Any whole-request refusal.
      TransientError: On a retryable S3 fault.
    """
    source = event["source"]
    actor = (event.get("actor") or {}).get("username")
    execution_arn = (event.get("execution") or {}).get("arn")

    already = outcomes.decided_keys(event.get("outcomes"))
    items = _collapse([item for item in source["items"] if item["key"] not in already])
    _assert_no_overlap(items)

    plan_items, decided = _expand(event, items)
    plan.assert_request_id_unused(event, execution_arn)
    plan_key = plan.write(
        event, source, event.get("destination"), actor, execution_arn, plan_items
    )

    object_count = sum(item["objectCount"] for item in plan_items)
    total_bytes = sum(item["totalBytes"] for item in plan_items)
    logger.info(
        "plan for %s: %d item(s), %d object(s), %d bytes from %d selected",
        actor,
        len(plan_items),
        object_count,
        total_bytes,
        len(items),
    )
    observability.info(
        "copy plan built",
        actor=actor,
        operation=event.get("operation"),
        source_bucket=source["bucket"],
        source_root=source["root"],
        items=len(plan_items),
        objects=object_count,
        bytes=total_bytes,
        skipped=len(items) - len(plan_items),
    )
    return {
        **event,
        "planKey": plan_key,
        "itemCount": len(plan_items),
        "objectCount": object_count,
        "totalBytes": total_bytes,
        "outcomes": outcomes.carry_forward(event.get("outcomes"), decided),
    }
