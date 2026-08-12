"""The copy plan: what an archive will move, expanded once and passed on by pointer.

inspect-source turns the validated selection into the exact object list that will be copied and
writes it here; the manifest builder and delete-source read it back. **Nothing it produces rides
on the state.** At ``ARCHIVE_MAX_OBJECTS`` the list is tens of megabytes against a 256 KB payload
limit, and ``States.DataLimitExceeded`` escapes every ``Catch`` — the worst failure this plane
has, because it is the one where the user is told nothing at all. So the plan goes to the admin
bucket and its KEY is threaded onward, with the count and the byte total beside it.

This module owns **all three** admin-bucket key layouts — the plan, the transfer manifest and the
Map Run's results export — for SPEC-161's reason: one module, one place a key can be wrong.
Where they live is this plane's business; the manifest's BYTES and the export's reader belong to
``cpcommon.transfer``, which is shared with table-share and file-send.

**Two of the three keys are pure functions of the request id and one is not.** The plan and the
results prefix are execution-stable, so a ``Retry`` of inspect-source rewrites the same object
rather than leaving a second one behind. The manifest is keyed by the EXECUTION as well, because
two overlapping executions of one request must not clobber each other's dataset while a Map is
reading it (SPEC-160). Nothing else on this plane needs that distinction, and stating it here is
cheaper than re-deriving it at three call sites.

``messages`` is imported for its side effect as well as tidiness: it registers this domain's
reason codes, and a terminal error validates its reason at construction. Without the import, a
process importing only this module raises a validation error where it meant to write a refusal.

Attributes:
  PREFIX: The prefix inside the ADMIN bucket that every artifact of an archive run shares. It is
    pinned by ``test_the_admin_prefix_matches_the_iam_grant_and_the_lifecycle_rule`` against the
    execution role's grant and the bucket's lifecycle rule, because those three are one decision
    written in three files: a plan written outside the grant fails at runtime, and one written
    outside the rule is never expired.

    **It is not the only thing in this repo called ``archive/``.** ``{admin}/archive/`` is
    control-plane scratch expiring in days; ``{space}/archive/`` holds the user's receipts and is
    never expired; the archive BUCKET holds the data for seven years. Three unrelated things, in
    three buckets.
  BASENAME: The plan object's basename.
  MANIFEST_BASENAME: The transfer manifest's basename.
  RESULTS_FOLDER: The folder under the request's prefix that the Distributed Map's
    ``ResultWriter`` exports into. Step Functions appends its own Map Run component below it.
  _FOLDER_MARKER_SUFFIX: A folder placeholder is a zero-byte object whose key ends in a slash.
    Unlike every other plane's listing, this one KEEPS them: an archived empty folder has to be
    restorable, and nothing else in the plan records that the folder existed.
"""

import json

from cpcommon import clients, errors, events, s3_listing
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError
from cpcommon.paths import assert_inside_root, normalize_root

from . import messages  # noqa: F401
from .config import (
    ARCHIVE_MAX_BYTES,
    ARCHIVE_MAX_OBJECT_BYTES,
    ARCHIVE_MAX_OBJECTS,
    PROTECTED_MARKER_BASENAME,
    RESERVED_SOURCE_ROOTS,
)

PREFIX = "archive"
BASENAME = "copy-plan.json"
MANIFEST_BASENAME = "transfer-manifest.jsonl"
RESULTS_FOLDER = "results"

_FOLDER_MARKER_SUFFIX = "/"


def _request_folder(request: dict, what: str) -> str:
    """Derives the folder every artifact of one request shares, from the request id.

    Args:
      request: The validated archive request.
      what: The artifact being keyed, for the refusal's detail.

    Returns:
      The folder under the admin bucket, ending in a slash.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id. Falling back to
        a shared or random key would give up the property the id buys — a Retry writing the same
        object rather than a second one — so it refuses instead. validate-authorize type-checks
        the id before this can be reached; the guard is here because the value becomes a KEY, and
        a key built from ``None`` is a real object in a real bucket.
    """
    request_id = request.get("requestId")
    if not isinstance(request_id, str) or not request_id.strip():
        raise TerminalError(events.MALFORMED, f"an archive {what} key needs the request id")
    return f"{PREFIX}/{request_id.strip()}/"


def plan_key(request: dict) -> str:
    """Derives the copy plan's S3 key from the request id.

    Args:
      request: The validated archive request.

    Returns:
      The plan key under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id.
    """
    return f"{_request_folder(request, 'copy plan')}{BASENAME}"


def transfer_manifest_key(request: dict, execution_name) -> str:
    """Derives the transfer manifest's key, which is EXECUTION-unique where the plan is not.

    Args:
      request: The validated archive request.
      execution_name: The execution's name, stamped onto the state by a ``Pass`` — never read
        from ``$$`` inside the task's own ``Parameters``, which wraps the payload and would put
        the request one level below where every notify path reads it (SPEC-157).

    Returns:
      The manifest key under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id, or when the
        execution name is missing. It refuses rather than falling back to the bare request id:
        the fallback is exactly the collision the execution segment exists to prevent, and it
        would appear only under concurrency.
    """
    folder = _request_folder(request, "transfer manifest")
    if not isinstance(execution_name, str) or not execution_name.strip():
        raise TerminalError(
            events.MALFORMED, "a transfer manifest key needs the execution name"
        )
    return f"{folder}{execution_name.strip()}/{MANIFEST_BASENAME}"


def transfer_results_prefix(request: dict) -> str:
    """Derives the prefix the Map Run's ``ResultWriter`` exports under.

    Args:
      request: The validated archive request.

    Returns:
      The results prefix under the admin bucket, with NO trailing slash — Step Functions appends
      its own Map Run component and manifest basename below it.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id.
    """
    return f"{_request_folder(request, 'transfer results')}{RESULTS_FOLDER}"


def _excluder(root: str):
    """Builds the ignore predicate for one space root.

    A closure rather than a module function because every rule is anchored at the space ROOT
    while ``list_data_objects`` hands its predicate the listing PREFIX — which here is whichever
    folder the user picked, so a rule anchored there would drop a user's own ``reports/archive/``.

    **THIS PLANE'S PREDICATE KEEPS WHAT EVERY OTHER PLANE'S DROPS.** ``s3_listing.is_ignored``
    excludes zero-byte objects, hidden segments and folder keys, which is right for a plane
    building a table over the data and wrong for one taking a byte-for-byte copy: an archived
    empty folder must come back, and an underscore-prefixed folder is the user's own.

    Args:
      root: The normalised authorized space root.

    Returns:
      A predicate matching ``list_data_objects``' ``ignore`` contract.

    Raises:
      None.
    """
    reserved = tuple(f"{root}{folder}/" for folder in RESERVED_SOURCE_ROOTS)

    def ignore(key: str, size: int, prefix: str) -> bool:
        """Reports whether an object is something an archive must not carry.

        Args:
          key: The absolute object key.
          size: The object's byte size, unused — a placeholder is recognised by its key.
          prefix: The listing prefix, unused: every rule here is anchored at the space root.

        Returns:
          True for a prefix marker or anything inside a portal-managed root folder.

        Raises:
          None.
        """
        del size, prefix
        if key.rsplit("/", 1)[-1] == PROTECTED_MARKER_BASENAME:
            return True
        return key.startswith(reserved)

    return ignore


def _object_size(bucket: str, key: str) -> int:
    """Reads one selected file's size, or fails the request naming it.

    Args:
      bucket: The source bucket.
      key: The selected file's key.

    Returns:
      The object's size in bytes.

    Raises:
      TerminalError: ``source_missing`` when the object is absent or unreadable. The user picked
        it from their own browser moments ago, so a miss means the request no longer describes
        reality and every other item in it is suspect too — and this plane DELETES what it
        copies, which makes proceeding over a stale selection the worst of the options.
      TransientError: On a retryable S3 fault, so the state's Retry re-runs the verb.
    """
    try:
        return int(clients.s3().head_object(Bucket=bucket, Key=key)["ContentLength"])
    except Exception as err:
        errors.raise_if_transient(err, f"head {bucket}/{key}")
        raise TerminalError("source_missing", f"{key!r}: {err}") from err


def _expand_item(bucket: str, root: str, entry: dict):
    """Yields every object one selected item resolves to, with its key relative to the root.

    A ``file`` resolves to itself; a ``folder`` is walked through the shared paginator, never
    assuming one page is the whole folder — S3 returns at most 1,000 keys per page, and treating
    a truncated listing as complete on THIS plane means deleting objects that were never copied.

    **Every key that enters the plan is re-checked against the authorized root** (FR-001 AC2),
    and the check is a separate statement rather than an argument to the yield: the ordering is
    security-relevant, and hiding it in Python's argument-evaluation order makes a reader take it
    on faith. The request's keys were checked as strings the browser supplied; these arrive from
    a ``ListObjectsV2`` response, which is the first point in the request's life where a key is
    produced by something other than the request.

    The exclusions apply to a selected FILE as well as to a listing: nothing upstream filters a
    file item, so naming ``{root}DO_NOT_DELETE.txt`` as a file would otherwise put an undeletable
    object into a plan whose last step is a delete.

    Args:
      bucket: The source bucket.
      root: The authorized, normalised space root.
      entry: One normalised selection item.

    Yields:
      ``(rel_key, size)`` per resolved object.

    Raises:
      TerminalError: ``source_missing`` for an absent file, or ``forbidden`` for a listed key
        that fails the containment re-check.
      TransientError: On a retryable S3 fault.
    """
    key = entry["key"]
    exclude = _excluder(root)
    if entry["kind"] == "file":
        assert_inside_root(root, key)
        size = _object_size(bucket, key)
        if not exclude(key, size, key):
            yield key[len(root):], size
        return
    for object_key, size in s3_listing.list_data_objects(bucket, key, ignore=exclude):
        assert_inside_root(root, object_key)
        yield object_key[len(root):], size


def expand(source: dict) -> tuple[list, int]:
    """Expands a validated selection into the deduplicated object list an archive will copy.

    **Overlapping selections COLLAPSE here rather than being refused** (FR-001 AC4), which is the
    one place this plane deliberately parts company with file-send. There, two items landing
    under one name is genuinely ambiguous, because the destination is keyed by the item's NAME.
    Here every object keeps its path relative to the space root, so ``reports/`` and
    ``reports/q1.csv`` name the same destination for the same bytes and there is exactly one
    right answer. A duplicated destination key would be a defect — the object would be copied
    twice and counted twice, and the commit gate compares counts.

    The caps are enforced INSIDE the walk rather than after it. A cap checked afterwards is a cap
    the verb has already paid for: the list it bounds is accumulating in memory as it grows, so a
    folder of ten million objects would exhaust the Lambda before the check that exists to refuse
    it ever ran. The cost is that a refusal cannot name the true total — nothing counted the rest
    — so it names what it had reached and says it was still counting.

    Args:
      source: The authorized source, carrying the bucket, root and normalised items.

    Returns:
      ``(objects, total_bytes)``, each object carrying its key relative to the space root and its
      size. Folder placeholders are CARRIED (so an archived empty folder is restorable) and
      counted, and contribute zero bytes because that is what they hold.

    Raises:
      TerminalError: ``source_missing`` for an absent file, ``object_too_large``,
        ``too_many_objects`` or ``source_too_large`` at the caps, ``nothing_to_archive`` when the
        selection resolves to no objects at all, or ``forbidden`` from the containment re-check.
      TransientError: On a retryable S3 fault.
    """
    bucket, root = source["bucket"], normalize_root(source["root"])

    seen: set = set()
    objects: list = []
    total_bytes = 0
    for entry in source["items"]:
        for rel_key, size in _expand_item(bucket, root, entry):
            if rel_key in seen:
                continue
            if size > ARCHIVE_MAX_OBJECT_BYTES:
                raise TerminalError(
                    "object_too_large",
                    f"an object of {size} bytes is over the per-object cap of "
                    f"{ARCHIVE_MAX_OBJECT_BYTES}",
                )
            seen.add(rel_key)
            objects.append({"relKey": rel_key, "bytes": size})
            total_bytes += size
            if len(objects) > ARCHIVE_MAX_OBJECTS:
                raise TerminalError(
                    "too_many_objects",
                    f"selection reached {len(objects)} objects and was still counting, over the "
                    f"cap of {ARCHIVE_MAX_OBJECTS}",
                )
            if total_bytes > ARCHIVE_MAX_BYTES:
                raise TerminalError(
                    "source_too_large",
                    f"selection reached {total_bytes} bytes and was still counting, over the cap "
                    f"of {ARCHIVE_MAX_BYTES}",
                )

    if not objects:
        raise TerminalError(
            "nothing_to_archive",
            f"{len(source['items'])} item(s) under {root} resolved to no objects",
        )
    return objects, total_bytes


def write(request: dict, source: dict, actor: str, objects: list, total_bytes: int) -> str:
    """Writes the copy plan to the admin bucket and returns its key.

    The plan records the source and archive locations it was expanded for alongside the objects,
    so a reader — the manifest builder, delete-source, or an operator looking at a failed run —
    does not have to join it back against the execution to know what it describes.

    Args:
      request: The validated request, which determines the key and carries the archive
        destination.
      source: The authorized source, carrying the bucket and root.
      actor: The verified actor, recorded for diagnosis.
      objects: The expanded objects, each carrying its relative key and size.
      total_bytes: How many bytes those objects hold.

    Returns:
      The key the plan was written to.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs inspect-source —
        safe, because the key is a pure function of the request id and the verb is read-only
        besides this write.
      TerminalError: ``malformed_event`` from the key derivation.
      ClientError: Any deterministic fault propagates.
    """
    key = plan_key(request)
    archive = request.get("archive") or {}
    body = json.dumps(
        {
            "requestId": request.get("requestId"),
            "actor": actor,
            "source": {"bucket": source["bucket"], "root": normalize_root(source["root"])},
            "archive": {"bucket": archive.get("bucket"), "root": archive.get("root")},
            "objectCount": len(objects),
            "totalBytes": total_bytes,
            "objects": objects,
        },
        separators=(",", ":"),
    ).encode()
    try:
        clients.s3().put_object(
            Bucket=cpconfig.ADMIN_BUCKET, Key=key, Body=body, ContentType="application/json"
        )
    except Exception as err:
        errors.raise_if_transient(err, f"put {cpconfig.ADMIN_BUCKET}/{key}")
        raise
    return key


def load(key: str) -> dict:
    """Reads a plan back, refusing every shape that is not demonstrably complete.

    Every unreadable shape is a WHOLE-REQUEST terminal, never a partial plan handed on. **A
    short plan is the shape this plane must never proceed over**: it would produce a manifest
    short of its lines, a copy that succeeded over it, a commit gate that agreed — because the
    gate compares the export against the plan, and both would be short by the same amount — and
    then a deletion of a source the archive does not hold. The count check is what makes that
    sentence true rather than aspirational, and it costs one comparison because the plan records
    its own ``objectCount`` at write time.

    Args:
      key: The plan key, as inspect-source threaded it onward.

    Returns:
      The parsed plan.

    Raises:
      TransientError: On a retryable S3 fault; the caller's Retry re-runs the verb.
      TerminalError: ``plan_unreadable`` when the plan is absent, is not valid JSON, is not an
        object, carries no objects, is short of the count it records, names no source or archive
        location, or holds an entry with no relative key. inspect-source wrote it earlier in this
        same execution, so a failure here means the object is missing or corrupt, which no retry
        fixes.
    """
    try:
        body = clients.s3().get_object(Bucket=cpconfig.ADMIN_BUCKET, Key=key)["Body"].read()
    except Exception as err:
        errors.raise_if_transient(err, f"get {cpconfig.ADMIN_BUCKET}/{key}")
        raise TerminalError("plan_unreadable", f"could not read copy plan {key}: {err}") from err

    try:
        plan = json.loads(body)
    except ValueError as err:
        raise TerminalError("plan_unreadable", f"copy plan {key} is not valid JSON: {err}") from err

    if not isinstance(plan, dict):
        raise TerminalError("plan_unreadable", f"copy plan {key} is not an object")
    objects = plan.get("objects")
    if not isinstance(objects, list) or not objects:
        raise TerminalError("plan_unreadable", f"copy plan {key} carries no objects")
    recorded = plan.get("objectCount")
    if not isinstance(recorded, int) or isinstance(recorded, bool) or len(objects) != recorded:
        raise TerminalError(
            "plan_unreadable",
            f"copy plan {key} holds {len(objects)} objects but records {recorded!r}",
        )
    for location in ("source", "archive"):
        block = plan.get(location)
        if not isinstance(block, dict) or not block.get("bucket") or not block.get("root"):
            raise TerminalError("plan_unreadable", f"copy plan {key} names no {location} location")
    for entry in objects:
        if not isinstance(entry, dict) or not entry.get("relKey"):
            raise TerminalError(
                "plan_unreadable", f"copy plan {key} holds an object with no relative key"
            )
    return plan
