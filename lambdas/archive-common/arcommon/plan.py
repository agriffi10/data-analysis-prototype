"""The copy plan: what an archive will move, expanded once and passed on by pointer.

inspect-source turns the validated selection into the exact object list that will be copied and
writes it here; the manifest builder and delete-source read it back. **Nothing it produces rides
on the state.** At ``ARCHIVE_MAX_OBJECTS`` the list is tens of megabytes against a 256 KB payload
limit, and ``States.DataLimitExceeded`` escapes every ``Catch`` — the worst failure this plane
has, because it is the one where the user is told nothing at all. So the plan goes to the admin
bucket and its KEY is threaded onward, with the count and the byte total beside it.

This module owns **every** admin-bucket key layout on this plane — the two plans, the two
transfer manifests, the poll's progress record and the three Map Run result exports — for
The reason: one module, one place a key can be wrong. Where they live is this plane's
business; a manifest's BYTES and an export's reader belong to ``cpcommon.transfer``, which is
shared with table-share and file-send.

**Two of the three keys are pure functions of the request id and one is not.** The plan and the
results prefix are execution-stable, so a ``Retry`` of inspect-source rewrites the same object
rather than leaving a second one behind. The manifest is keyed by the EXECUTION as well, because
two overlapping executions of one request must not clobber each other's dataset while a Map is
reading it. Nothing else on this plane needs that distinction, and stating it here is
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

    **It is not the only thing in this repo called ``archive/``, and it is the one that does NOT
    move** when the space's app-managed folders relocate. It is fact 3 of the word: the other two
    are ``cpcommon.app_managed.RECEIPT_FOLDER`` (the user's receipt folder in the space's own
    bucket) and ``cpcommon.app_managed.VAULT_ARCHIVE_SEGMENT`` (the key segment in the Glacier
    vault). It stays a literal HERE, in the plane that owns it, and a tripwire in this layer's
    tests pins all three equal today so the move has to look at it. ``{admin}/archive/`` is
    control-plane scratch expiring in days; ``{space}/archive/`` holds the user's receipts and is
    never expired; the archive BUCKET holds the data for seven years. Three unrelated things, in
    three buckets.
  BASENAME: The copy plan's basename — an ARCHIVE's object list.
  RESTORE_BASENAME: The restore plan's basename — a RESTORE's object list, keyed under the
    RESTORE run's own request id and not the archive's. The two ids are deliberately different
    values, so two restores of one archive write two plans and neither
    collides with the copy plan the archive itself wrote.
  MANIFEST_BASENAME: The transfer manifest's basename.
  RESTORE_MANIFEST_BASENAME: The restore transfer manifest's basename. **One manifest feeds BOTH
    of the restore's Distributed Maps** — the retrieval reads its source fields and
    the copy-back reads all of them — because they run over the same object set in the same
    order, and a second dataset would be a second thing that could disagree with the plan.
  PROGRESS_BASENAME: The poll's progress record. It lives in the admin bucket rather than on the
    state for the reason: the loop runs for hours and a per-object status list on the
    state is the 256 KB failure whose overflow escapes every ``Catch``. What rides is the small
    scalar block the ``Choice`` branches on.
  RESULTS_FOLDER: The folder under the request's prefix that the Distributed Map's
    ``ResultWriter`` exports into. Step Functions appends its own Map Run component below it.
  RETRIEVAL_RESULTS_FOLDER: The retrieval Map's export folder. Nothing reads it — that Map
    tolerates NO item failure, so a failed child fails the Map Run and the state's ``Catch``
    reports it — and it exists because a Distributed Map with no ``ResultWriter`` aggregates its
    children's output onto the state, which at 2,500 children is the same 256 KB failure.
  RESTORE_RESULTS_FOLDER: The copy-back Map's export folder, which the collector DOES read.
    Deliberately not ``RESULTS_FOLDER``: an archive and a restore of it are two different runs
    with two different request ids, so they could not collide, but naming them apart means an
    operator reading the admin bucket can tell which direction a run was going.
  _UNDELETABLE_FOLDERS: Folder names this plane may not delete AT ANY DEPTH, because the two
    bucket policies and the execution role's own Deny refuse ``s3:DeleteObject`` beneath them
    with a wildcard that matches ``/``. They are NOT the same rule as
    ``config.RESERVED_SOURCE_ROOTS``, which is anchored at the space root and answers a
    different question — see ``_assert_deletable_folder``.
"""

import json

from cpcommon import clients, errors, events, s3_listing
from cpcommon import config as cpconfig
from cpcommon.app_managed import (
    ATHENA_RESULTS_FOLDER,
    RECEIPT_FOLDER,
    app_managed_prefixes,
)
from cpcommon.errors import TerminalError
from cpcommon.paths import assert_inside_root, normalize_root

from . import manifest, messages  # noqa: F401
from .config import (
    ARCHIVE_MAX_BYTES,
    ARCHIVE_MAX_OBJECT_BYTES,
    ARCHIVE_MAX_OBJECTS,
    PROTECTED_MARKER_BASENAME,
    RESERVED_SOURCE_ROOTS,
)

PREFIX = "archive"
BASENAME = "copy-plan.json"
RESTORE_BASENAME = "restore-plan.json"
MANIFEST_BASENAME = "transfer-manifest.jsonl"
RESTORE_MANIFEST_BASENAME = "restore-manifest.jsonl"
PROGRESS_BASENAME = "restore-progress.json"
RESULTS_FOLDER = "results"
RETRIEVAL_RESULTS_FOLDER = "retrieval-results"
RESTORE_RESULTS_FOLDER = "restore-results"

_UNDELETABLE_FOLDERS = (RECEIPT_FOLDER, ATHENA_RESULTS_FOLDER, "user_settings")


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


def restore_plan_key(request: dict) -> str:
    """Derives the restore plan's S3 key from the RESTORE run's request id.

    Args:
      request: The validated restore request.

    Returns:
      The restore plan's key under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id.
    """
    return f"{_request_folder(request, 'restore plan')}{RESTORE_BASENAME}"


def write_restore_plan(request: dict, actor: str, objects: list, total_bytes: int) -> str:
    """Writes the restore plan to the admin bucket and returns its key.

    **Nothing it produces rides on the state**, for the same reason the copy plan does not: at
    ``ARCHIVE_MAX_OBJECTS`` the list is tens of megabytes against a 256 KB payload limit, and
    ``States.DataLimitExceeded`` escapes every ``Catch``. Each entry carries its size so
    the restore can tell the user how much is coming back and the retrieval can bound its wait.

    Args:
      request: The validated restore request, which determines the key and names the archive and
        the space.
      actor: The verified actor, recorded for diagnosis.
      objects: The derived objects, each with its archive key, destination key and size.
      total_bytes: How many bytes those objects hold.

    Returns:
      The key the plan was written to.

    Raises:
      TransientError: On a retryable S3 fault, so the caller's Retry re-runs the verb — safe,
        because the key is a pure function of the request id and the verb is read-only besides
        this write.
      TerminalError: ``malformed_event`` from the key derivation.
      ClientError: Any deterministic fault propagates.
    """
    key = restore_plan_key(request)
    archive = request.get("archive") or {}
    space = request.get("source") or {}
    body = json.dumps(
        {
            "requestId": request.get("requestId"),
            "actor": actor,
            "archive": {
                "bucket": archive.get("bucket"),
                "root": archive.get("root"),
                "archiveId": archive.get("archiveId"),
            },
            "space": {"bucket": space.get("bucket"), "root": space.get("root")},
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


def load_restore_plan(key: str, request: dict) -> dict:
    """Reads a restore plan back, refusing every shape that is not complete or not ours.

    The mirror of ``load`` and refused for the same reasons — a short plan here would mean a
    guard that cleared destinations the restore then did not check, and the restore copying back
    over whatever it did not know about. The request-identity check is the other half of
    ``assert_describes``' finding: the key is a pure function of the request id, so a second run
    under a reused id overwrites it.

    Args:
      key: The restore plan's key.
      request: The running restore request, which the plan must describe.

    Returns:
      The parsed plan.

    Raises:
      TransientError: On a retryable S3 fault; the caller's Retry re-runs the verb.
      TerminalError: ``plan_unreadable`` when the plan is absent, is not valid JSON, is not an
        object, carries no objects, is short of the count it records, or holds an entry with no
        destination key; ``plan_superseded`` when it describes a different request or archive.
    """
    try:
        body = clients.s3().get_object(Bucket=cpconfig.ADMIN_BUCKET, Key=key)["Body"].read()
    except Exception as err:
        errors.raise_if_transient(err, f"get {cpconfig.ADMIN_BUCKET}/{key}")
        raise TerminalError(
            "plan_unreadable", f"could not read restore plan {key}: {err}"
        ) from err

    try:
        loaded = json.loads(body)
    except ValueError as err:
        raise TerminalError(
            "plan_unreadable", f"restore plan {key} is not valid JSON: {err}"
        ) from err

    if not isinstance(loaded, dict):
        raise TerminalError("plan_unreadable", f"restore plan {key} is not an object")
    objects = loaded.get("objects")
    if not isinstance(objects, list) or not objects:
        raise TerminalError("plan_unreadable", f"restore plan {key} carries no objects")
    recorded = loaded.get("objectCount")
    if not isinstance(recorded, int) or isinstance(recorded, bool) or len(objects) != recorded:
        raise TerminalError(
            "plan_unreadable",
            f"restore plan {key} holds {len(objects)} objects but records {recorded!r}",
        )
    for entry in objects:
        if not isinstance(entry, dict) or not entry.get("destKey"):
            raise TerminalError(
                "plan_unreadable", f"restore plan {key} holds an object with no destination key"
            )

    archive = request.get("archive") or {}
    loaded_archive = loaded.get("archive") or {}
    for what, found, expected in (
        ("request id", loaded.get("requestId"), request.get("requestId")),
        ("archive root", loaded_archive.get("root"), archive.get("root")),
    ):
        if expected is not None and found != expected:
            raise TerminalError(
                "plan_superseded",
                f"restore plan {key} names a {what} of {found!r}, not {expected!r}",
            )
    return loaded


def _execution_folder(request: dict, execution_name, what: str) -> str:
    """Derives the EXECUTION-unique folder a transfer manifest sits in.

    Args:
      request: The validated request.
      execution_name: The execution's name, stamped onto the state by a ``Pass`` — never read
        from ``$$`` inside the task's own ``Parameters``, which wraps the payload and would put
        the request one level below where every notify path reads it.
      what: The artifact being keyed, for the refusal's detail.

    Returns:
      The folder under the admin bucket, ending in a slash.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id, or when the
        execution name is missing. It refuses rather than falling back to the bare request id:
        the fallback is exactly the collision the execution segment exists to prevent, and it
        would appear only under concurrency.
    """
    folder = _request_folder(request, what)
    if not isinstance(execution_name, str) or not execution_name.strip():
        raise TerminalError(events.MALFORMED, f"a {what} key needs the execution name")
    return f"{folder}{execution_name.strip()}/"


def transfer_manifest_key(request: dict, execution_name) -> str:
    """Derives the transfer manifest's key, which is EXECUTION-unique where the plan is not.

    Args:
      request: The validated archive request.
      execution_name: The execution's name.

    Returns:
      The manifest key under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id or execution name.
    """
    return f"{_execution_folder(request, execution_name, 'transfer manifest')}{MANIFEST_BASENAME}"


def restore_manifest_key(request: dict, execution_name) -> str:
    """Derives the restore transfer manifest's key, EXECUTION-unique for the same reason.

    Args:
      request: The validated restore request.
      execution_name: The execution's name.

    Returns:
      The restore manifest's key under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id or execution name.
    """
    folder = _execution_folder(request, execution_name, "restore manifest")
    return f"{folder}{RESTORE_MANIFEST_BASENAME}"


def restore_progress_key(request: dict) -> str:
    """Derives the poll's progress record key, which is REQUEST-stable and not execution-unique.

    Stable on purpose, unlike the manifest beside it. The record exists so a poll iteration does
    not re-head what an earlier one already saw complete, and a ``Retry`` of the poll verb — or a
    redriven execution — should pick that progress up rather than start again from zero. There is
    nothing for two concurrent executions to clobber here that re-heading would not repair.

    Args:
      request: The validated restore request.

    Returns:
      The progress record's key under the admin bucket.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id.
    """
    return f"{_request_folder(request, 'restore progress')}{PROGRESS_BASENAME}"


def retrieval_results_prefix(request: dict) -> str:
    """Derives the prefix the RETRIEVAL Map's ``ResultWriter`` exports under.

    Args:
      request: The validated restore request.

    Returns:
      The prefix under the admin bucket, with NO trailing slash — Step Functions appends its own
      Map Run component and manifest basename below it.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id.
    """
    return f"{_request_folder(request, 'retrieval results')}{RETRIEVAL_RESULTS_FOLDER}"


def restore_results_prefix(request: dict) -> str:
    """Derives the prefix the COPY-BACK Map's ``ResultWriter`` exports under.

    Args:
      request: The validated restore request.

    Returns:
      The prefix under the admin bucket, with NO trailing slash.

    Raises:
      TerminalError: ``malformed_event`` when the request carries no usable id.
    """
    return f"{_request_folder(request, 'restore results')}{RESTORE_RESULTS_FOLDER}"


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
    reserved = tuple(
        anchored for folder in RESERVED_SOURCE_ROOTS for anchored in app_managed_prefixes(root, folder)
    )

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


def _assert_deletable_folder(root: str, key: str) -> None:
    """Refuses an object this plane could copy but could not then delete.

    **Found in review, and the two rules it reconciles are both correct on their own.** The code's
    reserved-folder rule is anchored at the SPACE ROOT, deliberately: ``alice/reports/archive/`` is
    an ordinary folder the user made, and ``assert_not_reserved`` says so. The IAM Deny that
    protects the same names cannot be anchored anywhere — ``*`` matches ``/`` in a resource ARN, so
    ``*/archive/*`` covers every depth, and IAM has no single-segment wildcard to express the
    narrower rule with.

    So a legal-looking archive of ``alice/projects/`` containing ``alice/projects/archive/notes.txt``
    would copy every object into Glacier at the 90-day minimum, write its record, and then fail
    part way through the deletion with "contact an administrator" — the exact shape
    ``assert_not_protected_marker`` refuses a marker up front to avoid.

    It is a WHOLE-REQUEST refusal rather than an exclusion, and that direction is the rule:
    the alternative silently drops the user's own data out of an archive that reports success. The
    user can rename the folder or select around it.

    Args:
      root: The authorized, normalised space root.
      key: An absolute object key inside that root.

    Returns:
      None.

    Raises:
      TerminalError: ``undeletable_folder``, naming the folder so the message can tell the user
        which one to deal with.
    """
    for segment in key[len(root) :].split("/")[:-1]:
        if segment in _UNDELETABLE_FOLDERS:
            raise TerminalError(
                "undeletable_folder",
                f"{key!r} sits inside a folder named {segment!r}, which cannot be deleted",
                tokens={"folderName": segment},
            )


def _assert_not_the_record(relative: str) -> str:
    """Refuses the one relative key that would archive onto this plane's own integrity record.

    **Found in review, and it is the worst outcome this arc could still produce.** An object's
    archive key is ``{archivePrefix}{relKey}`` and the record's is ``{archivePrefix}_manifest.json``
    — so a user's own file at the SPACE ROOT called ``_manifest.json`` maps to exactly the record's
    key. Nothing upstream stops it: the reserved-root rule refuses selecting the space root as a
    FOLDER, but naming that file directly passes containment, the reserved rule and the marker rule.

    What it would cost is not a duplicate. The copy would land, ``write-manifest`` would OVERWRITE
    it with the integrity record, ``delete-source`` would then delete the user's original — the
    vault has versioning off — and the run would report success. The archive is then also
    permanently unrestorable: the restore excludes that key as the record, counts one object fewer
    than the record claims, and refuses ``restore_archive_incomplete`` for every object archived
    alongside it. Alone, it restores as ``archive_not_found`` against a receipt the user is holding.

    It is a WHOLE-REQUEST refusal rather than an exclusion, which is the direction: silently
    dropping the file would archive everything else and delete the one object it could not carry.

    Only the space root collides — a ``reports/_manifest.json`` three folders down has a relative
    key of ``reports/_manifest.json`` and is an ordinary file that archives and restores like any
    other.

    Args:
      relative: An object's key relative to the space root.

    Returns:
      The relative key, unchanged, so this reads as a checkpoint at the call site.

    Raises:
      TerminalError: ``reserved_object_name``, naming the basename so the message can tell the
        user which file to rename.
    """
    if relative == manifest.BASENAME:
        raise TerminalError(
            "reserved_object_name",
            f"{relative!r} at the space root would overwrite this archive's own record",
            tokens={"itemName": manifest.BASENAME},
        )
    return relative


def _expand_item(bucket: str, root: str, entry: dict):
    """Yields every object one selected item resolves to, with its key relative to the root.

    A ``file`` resolves to itself; a ``folder`` is walked through the shared paginator, never
    assuming one page is the whole folder — S3 returns at most 1,000 keys per page, and treating
    a truncated listing as complete on THIS plane means deleting objects that were never copied.

    **Every key that enters the plan is re-checked against the authorized root**,
    and the check is a separate statement rather than an argument to the yield: the ordering is
    security-relevant, and hiding it in Python's argument-evaluation order makes a reader take it
    on faith. The request's keys were checked as strings the browser supplied; these arrive from
    a ``ListObjectsV2`` response, which is the first point in the request's life where a key is
    produced by something other than the request.

    The exclusions apply to a selected FILE as well as to a listing: nothing upstream filters a
    file item, so naming ``{root}DO_NOT_DELETE.txt`` as a file would otherwise put an undeletable
    object into a plan whose last step is a delete.

    A listed key that IS the root leaves an empty relative key and is dropped. It is not reachable
    from a legal selection — the reserved-root rule refuses selecting a space root — and it is
    dropped rather than carried because an empty relative key names the archive prefix itself,
    which ``origin_key`` refuses to reconstruct, so it would fail two states later as an
    unreadable plan.

    Args:
      bucket: The source bucket.
      root: The authorized, normalised space root.
      entry: One normalised selection item.

    Yields:
      ``(rel_key, size)`` per resolved object.

    Raises:
      TerminalError: ``source_missing`` for an absent file, or ``forbidden`` for a listed key
        that fails the containment re-check. An absent file fails the WHOLE request: the user
        picked it from their own browser moments ago, so a miss means the request no longer
        describes reality and every other item in it is suspect too — and this plane DELETES
        what it copies, which makes proceeding over a stale selection the worst of the options.
      TransientError: On a retryable S3 fault.
    """
    key = entry["key"]
    exclude = _excluder(root)
    if entry["kind"] == "file":
        assert_inside_root(root, key)
        _assert_deletable_folder(root, key)
        size = s3_listing.object_size(bucket, key, missing_reason="source_missing")
        if not exclude(key, size, key):
            yield _assert_not_the_record(key[len(root):]), size
        return
    for object_key, size in s3_listing.list_data_objects(bucket, key, ignore=exclude):
        assert_inside_root(root, object_key)
        _assert_deletable_folder(root, object_key)
        relative = object_key[len(root):]
        if relative:
            yield _assert_not_the_record(relative), size


def expand(source: dict) -> tuple[list, int]:
    """Expands a validated selection into the deduplicated object list an archive will copy.

    **Overlapping selections COLLAPSE here rather than being refused**, which is the
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


def assert_archive_unused(request: dict) -> None:
    """Refuses a request whose archive prefix already holds something.

    **Found in review, and it closes the worse half of a request-id collision.** The request id is
    browser-supplied and is the whole identity of an archive: the copy plan, the archive prefix,
    ``_manifest.json`` and the receipt are all keyed on it alone (only the transfer manifest also
    carries the execution). The queue's FIFO ``MessageDeduplicationId`` is that id, but its window
    is five minutes against a three-hour ceiling — and the live checks for this arc submit
    hand-crafted messages — so a second request carrying an id that has already been used is
    reachable, and nothing downstream would notice.

    What it costs is not a duplicate: a second run under a used id mixes two archives under one
    prefix that the restore will list and restore wholesale, overwrites the first run's record and
    receipt, and — if the second run fails its commit gate — has its ROLLBACK delete the first
    archive's objects out of a bucket with versioning off. That last one is unrecoverable, and it
    is the reason this check exists rather than being left to the producer's conventions.

    **It narrows rather than closes**, exactly as table-share's conflict guard does: two concurrent
    executions can both find the prefix empty. What it removes is the ordinary case — an id reused
    minutes or days later — and it is one ``ListObjectsV2`` against a bucket this plane is the only
    reader of.

    Args:
      request: The validated request, carrying the resolved archive destination.

    Returns:
      None.

    Raises:
      TerminalError: ``request_id_reused`` when the prefix is occupied, or ``forbidden`` when the
        request carries no archive destination to check.
      TransientError: On a retryable S3 fault.
    """
    archive = request.get("archive") or {}
    bucket, root = archive.get("bucket"), archive.get("root")
    if not bucket or not root:
        raise TerminalError("forbidden", "the request carries no archive destination")
    try:
        response = clients.s3().list_objects_v2(Bucket=bucket, Prefix=root, MaxKeys=1)
    except Exception as err:
        errors.raise_if_transient(err, f"list {bucket}/{root}")
        raise
    if response.get("KeyCount") or response.get("Contents"):
        raise TerminalError(
            "request_id_reused",
            f"{bucket}/{root} already holds objects, so this request id has been used before",
        )


def assert_describes(loaded: dict, request: dict, key: str) -> dict:
    """Confirms a plan read back from S3 is the plan THIS execution wrote.

    **Found in review, and it is the other half of the request-id collision.** The plan's key is a
    pure function of the request id, which is what makes a ``Retry`` of inspect-source rewrite the
    same object rather than leave a second one behind — and which also means a second execution
    carrying the same id overwrites it. delete-source takes the bucket, the root and the KEY LIST
    from whatever it reads back, so without this check a run could pass its own commit gate on its
    own counts and then delete a different selection entirely, in either space bucket.

    Cheap and total: four fields the state already holds, compared against what the object claims.
    The count is included because it is the term the gate reasoned about, and the root because it
    is the prefix every deletion is scoped to.

    Args:
      loaded: The parsed plan.
      request: The running request.
      key: The plan's key, for the refusal's detail.

    Returns:
      The plan, unchanged, so this reads as a checkpoint at the call site.

    Raises:
      TerminalError: ``plan_superseded`` when the plan describes a different request, source or
        object count.
    """
    source = request.get("source") or {}
    loaded_source = loaded.get("source") or {}
    expected_root = source.get("root")
    expectations = (
        ("request id", loaded.get("requestId"), request.get("requestId")),
        ("source bucket", loaded_source.get("bucket"), source.get("bucket")),
        (
            "source root",
            normalize_root(loaded_source.get("root") or "?"),
            normalize_root(expected_root) if expected_root else None,
        ),
        ("object count", loaded.get("objectCount"), request.get("objectCount")),
    )
    for what, found, expected in expectations:
        if expected is not None and found != expected:
            raise TerminalError(
                "plan_superseded",
                f"copy plan {key} names a {what} of {found!r}, not {expected!r}",
            )
    return loaded


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


def load(key: str, request: dict) -> dict:
    """Reads a plan back, refusing every shape that is not demonstrably complete or not ours.

    Every unreadable shape is a WHOLE-REQUEST terminal, never a partial plan handed on. **A
    short plan is the shape this plane must never proceed over**: it would produce a manifest
    short of its lines, a copy that succeeded over it, a commit gate that agreed — because the
    gate compares the export against the plan, and both would be short by the same amount — and
    then a deletion of a source the archive does not hold. The count check is what makes that
    sentence true rather than aspirational, and it costs one comparison because the plan records
    its own ``objectCount`` at write time.

    Args:
      key: The plan key, as inspect-source threaded it onward.
      request: The running request, which the plan must describe — see ``assert_describes``.

    Returns:
      The parsed plan.

    Raises:
      TransientError: On a retryable S3 fault; the caller's Retry re-runs the verb.
      TerminalError: ``plan_unreadable`` when the plan is absent, is not valid JSON, is not an
        object, carries no objects, is short of the count it records, names no source or archive
        location, or holds an entry with no relative key; ``plan_superseded`` when it describes a
        different request. inspect-source wrote it earlier in this same execution, so a failure
        here means the object is missing, corrupt, or has been overwritten by another run — and
        no retry fixes any of the three.
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
    return assert_describes(plan, request, key)
