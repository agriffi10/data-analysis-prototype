"""Turning a validated selection into the concrete, bounded object list a send will copy.

This is the whole of the first requirement. A selection is a mix of files and folders;
a folder expands recursively and can hold thousands of objects, so the expansion happens here —
once, in one verb — and everything downstream reads the copy plan rather than listing again.

**The exclusion rule is this plane's own, and reusing the analytics one would have been a
silent defect.** ``cpcommon.s3_listing.is_ignored`` anchors ``athenaresults/``,
``user_settings/`` and its hidden-segment test at the LISTING PREFIX. That is right for the
three planes that list a table's or a check's own folder, and wrong here: the listing prefix is
whichever item the user picked, so sending ``alice/reports/`` would drop a user-made
``alice/reports/athenaresults/`` — an ordinary sendable folder — and
any ``_drafts/``, without a refusal or a message. A silent drop is worse than copying it and
worse than refusing it. The hidden-segment rule also exists because *Athena* ignores those
files, which says nothing about a byte-for-byte copy. So the predicate below is anchored at the
SPACE ROOT and carries exactly the three exclusions the spec names.

Attributes:
  _FOLDER_MARKER_SUFFIX: A folder placeholder is a zero-byte object whose key ends in a slash —
    what ``createFolder`` writes (``fileBrowser.service.ts``). Excluded by that shape rather
    than by ``size == 0``, which would also drop a user's genuine empty file. The visible
    consequence is deliberate and is the spec's: an EMPTY subfolder does not survive a send,
    because nothing is left to carry it.
  _PORTAL_MANAGED_FOLDERS: The folders the portal owns at a space root, never sendable. Both are
    ANCHORED AT THE ROOT, which is the whole difference from the analytics rule — a user's own
    ``reports/athenaresults/`` is an ordinary folder they may send.

    ``athenaresults/`` is the spec's. ``user_settings/`` is not, and it is here
    because dropping it would have been a change nobody argued for: it is a portal-managed
    folder holding the sender's notification inbox and shared-space connections cache, hidden
    everywhere in the browser (``protectedFolders.ts``), and unlike the two analytics rules this
    plane deliberately does NOT reuse, anchoring it at the space root preserves the exclusion
    with **zero** false positives. Narrowing an exclusion set is a decision; this one had not
    been made.
"""

from cpcommon import s3_listing
from cpcommon.errors import TerminalError

from .authz import assert_not_results_folder
from .config import (
    ATHENA_RESULTS_FOLDER,
    SEND_MAX_OBJECT_BYTES,
    SEND_MAX_OBJECTS,
    SEND_MAX_TOTAL_BYTES,
    USER_SETTINGS_FOLDER,
)
from .paths import assert_inside_root, item_name, normalize_root, relative_key

_FOLDER_MARKER_SUFFIX = "/"

_PORTAL_MANAGED_FOLDERS = (ATHENA_RESULTS_FOLDER, USER_SETTINGS_FOLDER)


def _excluder(root: str):
    """Builds the ignore predicate for one space root.

    A closure rather than a module function because the rule is anchored at the ROOT while
    ``list_data_objects`` hands its predicate the listing PREFIX — see the module docstring for
    why the difference is the whole point.

    Args:
      root: The normalised authorized space root.

    Returns:
      A predicate matching ``list_data_objects``' ``ignore`` contract.

    Raises:
      None.
    """
    portal_managed = tuple(f"{root}{folder}/" for folder in _PORTAL_MANAGED_FOLDERS)

    def ignore(key: str, size: int, prefix: str) -> bool:
        """Reports whether an object is something other than sendable data.

        Args:
          key: The absolute object key.
          size: The object's byte size, unused — a genuine empty file is still a file.
          prefix: The listing prefix, unused: every rule here is anchored at the space root.

        Returns:
          True for a folder placeholder, the prefix marker, or a portal-managed folder.

        Raises:
          None.
        """
        del size, prefix
        if key.endswith(_FOLDER_MARKER_SUFFIX):
            return True
        if key.rsplit("/", 1)[-1] == s3_listing.MARKER_BASENAME:
            return True
        return key.startswith(portal_managed)

    return ignore


def _collapse(items: list) -> list:
    """Drops repeats of the same item, preserving the order the sender gave.

    A repeat is a duplicate, not an overlap: the rule says the same item listed twice collapses
    rather than being refused, because there is exactly one right answer and no ambiguity about
    what the user meant.

    **The identity is (kind, key), and the key alone is not enough.** validate-authorize
    normalises a ``folder`` key to a trailing slash and leaves a ``file`` key exactly as it
    arrived, so ``{"file", "alice/reports/"}`` and ``{"folder", "alice/reports"}`` reach here as
    two entries with the SAME key and different kinds. Collapsing on the key kept whichever came
    first and dropped the other — so a request naming both silently sent one zero-byte
    placeholder and none of the folder's contents, reporting success, with the outcome depending
    on the order of the list. Keyed on the pair, both survive to the overlap rule, which refuses
    them; a silent drop is the thing the rule exists to prevent.

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
    """Refuses a selection where one item contains another.

    **Both of the alternatives are worse than a refusal**, which is why this is a whole-request
    terminal rather than a repair. Copying the object twice writes it once at
    ``reports/2026/q1.csv`` and once at ``q1.csv``, which no user asked for; silently dropping
    one means the send quietly did less than it said. The user can express either intention
    exactly by selecting differently, so the refusal costs them one round trip and nothing else.

    Compared as PREFIXES, so a folder ``alice/a/`` contains ``alice/a/b.csv`` while the file
    ``alice/ab.csv`` is untouched by it — the same distinction between "starts with" and "is
    under" that the containment rule turns on.

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
                "overlapping_items",
                f"{inner['key']!r} is already inside {outer['key']!r}",
            )


def _assert_no_name_collision(items: list) -> None:
    """Refuses two items that would arrive in the recipient's inbox under one name.

    The destination is keyed by the item's NAME, not by where it lived, so ``a/reports/`` and
    ``b/reports/`` both land at ``shared_files/{sender}/reports/`` and interleave into one
    folder — two senders' worth of confusion inside a single send. It is refused for the same
    reason the overlap is: the merge is silent and the alternative repair (renaming one) would
    invent a name the sender never chose.

    Args:
      items: The collapsed selection.

    Returns:
      None.

    Raises:
      TerminalError: ``colliding_item_names`` naming the shared name.
    """
    seen: dict[str, str] = {}
    for entry in items:
        name = item_name(entry["key"])
        if name in seen:
            raise TerminalError(
                "colliding_item_names",
                f"{entry['key']!r} and {seen[name]!r} would both arrive as {name!r}",
                tokens={"itemName": name},
            )
        seen[name] = entry["key"]


def _checked(root: str, key: str) -> str:
    """Re-runs every containment rule against a key that arrived from S3.

    **The check is not trusted from validate-authorize alone** (FR-001), and the reason is that
    the two keys have different provenance. The request's keys were checked as strings the
    sender supplied; these arrive from a ``ListObjectsV2`` response, which is the first point in
    the request's life where a key is produced by something other than the request. Nothing
    known makes S3 return a key outside the prefix it was asked for — the value of the check is
    that the rule holds for what is actually copied, not for what was asked for.

    Args:
      root: The authorized space root.
      key: An absolute key from the listing.

    Returns:
      The key, unchanged.

    Raises:
      TerminalError: ``forbidden`` for an out-of-root or dot-segment key,
        ``results_not_sendable`` for the space's own query results.
    """
    assert_inside_root(root, key)
    return assert_not_results_folder(root, key)


def _expand_item(bucket: str, root: str, entry: dict):
    """Yields every object one selected item resolves to, with its relative key.

    A ``file`` resolves to exactly itself and carries an empty relative key; a ``folder`` is
    walked recursively through the shared paginator, never assuming one page is the whole
    folder — S3 returns at most 1,000 keys per page, and a folder over that boundary is the
    realistic case this verb exists for.

    **Every key that enters the plan is re-checked, and only those.** For a file the item key IS
    the object, so it is checked here; for a folder the item key is not an object and the objects
    beneath it are, so each of those is checked instead. The check is a separate statement rather
    than an argument to the yield: the ordering is security-relevant — containment before the
    ``HeadObject`` — and hiding it in Python's argument-evaluation order makes a reader take it on
    faith.

    **The exclusions apply to a selected FILE too, and an earlier version applied them only to a
    listing.** A ``file`` item is not filtered by anything upstream — validate-authorize
    normalises a *folder* key to a trailing slash and leaves a file key untouched — so naming
    ``{root}/DO_NOT_DELETE.txt`` as a file copied the prefix marker into someone's inbox, and
    naming a folder AS a file copied its zero-byte placeholder as a file. the rule says these
    are excluded from the copy set; it does not say "when they turn up in a listing". A selection
    of nothing but excluded objects then lands on the zero-object refusal, which is the right
    outcome and the same one an empty folder gets.

    Args:
      bucket: The source bucket.
      root: The authorized space root.
      entry: One normalised selection item.

    Yields:
      ``(name, rel_key, src_key, size)`` per resolved object.

    Raises:
      TerminalError: ``source_missing`` for an absent file, or a containment reason for a
        listed key that fails the re-check. An absent file fails the WHOLE request rather than
        being one bad row in it: the sender picked it from their own browser moments ago, so a
        miss means the request no longer describes reality and every other item is suspect too.
      TransientError: On a retryable S3 fault.
    """
    key = entry["key"]
    name = item_name(key)
    exclude = _excluder(root)
    if entry["kind"] == "file":
        src_key = _checked(root, key)
        size = s3_listing.object_size(bucket, src_key, missing_reason="source_missing")
        if not exclude(src_key, size, key):
            yield name, "", src_key, size
        return
    for object_key, size in s3_listing.list_data_objects(bucket, key, ignore=exclude):
        src_key = _checked(root, object_key)
        yield name, relative_key(key, src_key), src_key, size


def expand(source: dict) -> tuple[list, int]:
    """Expands a validated selection into the object list a send will copy.

    The caps are enforced INSIDE the walk rather than after it. A cap checked afterwards is a
    cap the verb has already paid for: the object list it bounds is being accumulated in memory
    as it grows, so a folder of ten million objects would exhaust the Lambda before the check
    that exists to refuse it ever ran. The cost is that a refusal cannot name the true total —
    nothing counted the rest — so it names what it had reached and says it was still counting,
    rather than reporting a bare cap an operator learns nothing from.

    Args:
      source: The authorized source, carrying the bucket, root and normalised items.

    Returns:
      ``(objects, total_bytes)``, each object carrying its owning item name, its relative key,
      its absolute source key and its size — everything the manifest builder needs
      without a second listing.

    Raises:
      TerminalError: ``overlapping_items`` or ``colliding_item_names`` for a selection that
        cannot be laid out, ``source_missing`` for an absent file, ``too_many_objects``,
        ``source_too_large`` or ``object_too_large`` at the caps, ``nothing_to_send`` when the
        selection resolves to no objects at all, or a containment reason from the re-check.
      TransientError: On a retryable S3 fault.
    """
    bucket, root = source["bucket"], normalize_root(source["root"])
    items = _collapse(source["items"])
    _assert_no_overlap(items)
    _assert_no_name_collision(items)

    objects, total_bytes = [], 0
    for entry in items:
        for name, rel_key, src_key, size in _expand_item(bucket, root, entry):
            if size > SEND_MAX_OBJECT_BYTES:
                raise TerminalError(
                    "object_too_large",
                    f"an object of {size} bytes is over the per-object cap of "
                    f"{SEND_MAX_OBJECT_BYTES}",
                )
            objects.append({"item": name, "relKey": rel_key, "srcKey": src_key, "size": size})
            total_bytes += size
            if len(objects) > SEND_MAX_OBJECTS:
                raise TerminalError(
                    "too_many_objects",
                    f"selection reached {len(objects)} objects and was still counting, "
                    f"over the cap of {SEND_MAX_OBJECTS}",
                )
            if total_bytes > SEND_MAX_TOTAL_BYTES:
                raise TerminalError(
                    "source_too_large",
                    f"selection reached {total_bytes} bytes and was still counting, "
                    f"over the cap of {SEND_MAX_TOTAL_BYTES}",
                )

    if not objects:
        raise TerminalError(
            "nothing_to_send",
            f"{len(items)} item(s) under {root} resolved to no objects",
        )
    return objects, total_bytes
