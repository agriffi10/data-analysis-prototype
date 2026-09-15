"""The portal's own folders and markers, as the file-operations plane refuses them.

These rules are enforcement, and the browser's side is only the affordance: the plane accepts a
hand-crafted envelope, and nothing the browser hides, filters or disables is a permission. They are
not the plane's only check on a selected item — the inspect-source verb and ``focommon.delete``
apply rules of their own further on. The browser's rules also differ from these, so what it
refuses is no measure of what this module needs. ``undeletableSelectionRefusal`` in
``protectedFolders.ts`` disables Delete and Move only when EVERY selected item is refused, so a
mixed selection arrives here with its protected items in it. ``user_settings/`` is hidden in the
browser and never refused as a copy, move or delete source. A lone file goes from the browser to
the API's object routes rather than coming here, and ``apicommon.protected`` holds their rules: a
separate set, written for those routes, that guards nothing sent to this plane. ``config`` names
the tests that hold its two folder lists and the archive rule, and what each is held against.

**THE THREE BROWSER LISTS DIFFER ON PURPOSE AND MUST NOT BE UNIONED.** ``protectedFolders.ts``
carries the note and this docstring repeats the warning, because unioning them looks like the tidy
repair and would silently remove working capability. They answer different questions: may the user
SEE it, may the user PASTE into it, may the user DESTROY it. ``athenaresults/`` is the clearest
case — visible, never a paste target, never deletable, and copying *out* of it is permitted today.

So the rule is stated per (side x operation), enumerated against the real constants:

  - as a DESTINATION, the picker-locked folders, plus ``archive/`` under its own depth rule;
  - as a DELETE or MOVE SOURCE, the undeletable root folders, plus anything beneath
    ``athenaresults/`` or ``archive/``;
  - for EVERY operation, ``user_settings/`` as a source, by this plane's own rule;
  - for EVERY operation INCLUDING COPY, the marker file by basename — see below;
  - as a COPY SOURCE, no FOLDER rule at all. There is deliberately none, and a test says so.

**The bucket asymmetry is mirrored, never averaged.** In the personal bucket the prefix IS the
principal tag, so the Deny names the caller's own root and ``alice/backups/archive/x`` is an
ordinary file. In the shared bucket the Deny puts a wildcard where the space name goes, and an S3
resource wildcard matches ``/`` too, so it reaches an ``archive`` folder at ANY depth below the
space root. Anchoring both at the root would accept a destination IAM refuses; applying the
any-depth rule to both would refuse a personal file IAM permits deleting.
``test_archive_write_lock_mirrors_iam.py`` builds a key matcher out of each bucket policy and runs
``_is_at_or_below`` against it, so this paragraph is asserted rather than described.

Every refusal names the folder in operator text and carries its own reason code, so the notifier
can word it without re-deriving which rule fired.
"""

from cpcommon.app_managed import app_managed_prefixes, segments_hold_app_managed

from .config import (
    ARCHIVE_FOLDER,
    ATHENA_RESULTS_FOLDER,
    MARKER_BASENAME,
    PICKER_LOCKED_FOLDERS,
    UNDELETABLE_ROOT_FOLDERS,
    USER_SETTINGS_FOLDER,
)
from .outcomes import Refusal
from .paths import normalize_root

__all__ = [
    "destination_refusal",
    "marker_refusal",
    "settings_source_refusal",
    "source_refusal",
]


def _is_root_folder(key: str, root: str, name: str) -> bool:
    """Reports whether a key names one folder at the space root, and not below it.

    **A file whose name happens to match is NOT that folder.** ``alice/archive`` — an
    extension-less file — is matched by no bucket Deny and the browser's own rule only ever asks
    this of a folder, so treating it as one would refuse a delete both the browser and IAM permit.
    A folder's key carries its trailing slash by the time it reaches here; validate-authorize
    normalises it.

    Args:
      key: The key under test.
      root: The authorized space root, normalised.
      name: The folder's name.

    Returns:
      True when the key is exactly that root-level folder.

    Raises:
      None.
    """
    return key.endswith("/") and key in app_managed_prefixes(normalize_root(root), name)


def _is_under_root_folder(key: str, root: str, name: str) -> bool:
    """Reports whether a key is one root-level folder or anything inside it.

    Root-anchored in both buckets, unlike the write-lock rule below: this mirrors the browser's
    PICKER, which filters the folder out of the navigable list and so makes everything under it
    unreachable, rather than mirroring an IAM Deny. Compared on the RAW key, so a file merely named
    like a locked folder is not mistaken for one.

    Args:
      key: The key under test.
      root: The authorized space root, normalised.
      name: The folder's name.

    Returns:
      True when the key is that folder or sits beneath it.

    Raises:
      None.
    """
    return key.startswith(app_managed_prefixes(normalize_root(root), name))


def _is_at_or_below(key: str, root: str, name: str, *, space_kind: str) -> bool:
    """Reports whether a key is the named folder or anything inside it, under the bucket's own rule.

    Root-anchored in a personal space and any-depth in a shared one, mirroring each bucket's Deny
    rather than averaging the two.

    **The any-depth arm scans for the folder's SEGMENTS, not its name.** Since the move, the
    shared Deny reads ``*/system_settings/archive/*``, so a folder a user calls ``archive`` inside
    a shared space is ordinary and refusing it would be a refusal IAM does not make.
    ``segments_hold_app_managed`` is what supplies the pair, for the same reason
    ``app_managed_prefixes`` supplies the anchored form: a literal here went stale at the move.

    **Compared on the RAW key, never a slash-appended form.** ``alice/archive`` is an
    extension-less FILE, matched by no Deny and offered for deletion by the browser; appending a
    slash to compare would make it indistinguishable from the folder. For the same reason the
    shared-bucket segment scan drops the final segment of a file key: a file *called* ``archive``
    is not a file *inside* one.

    Args:
      key: The key under test.
      root: The authorized space root, normalised.
      name: The folder's name.
      space_kind: ``personal`` or ``shared``, which is what selects the rule.

    Returns:
      True when writes or deletes at this key are denied by the bucket's policy.

    Raises:
      None.
    """
    root = normalize_root(root)
    if key.startswith(app_managed_prefixes(root, name)):
        return True
    if space_kind != "shared" or not key.startswith(root):
        return False
    segments = key[len(root) :].split("/")
    return segments_hold_app_managed(
        segments if key.endswith("/") else segments[:-1], name
    )


def destination_refusal(root: str, prefix: str, space_kind: str) -> Refusal | None:
    """Refuses a destination the browser's own picker would never offer.

    Every picker-locked folder is refused at the space root, INCLUDING the two a folder-name list
    tends to omit — ``_data-quality-reports/`` and ``shared_tables/`` — whose absence would let this
    plane accept a destination the browser refuses. ``archive/`` is refused again under the depth
    rule, because the picker rule alone is root-anchored and the shared bucket denies it deeper.

    **Anything BENEATH a locked folder is refused too, not just the folder itself.** The browser's
    picker filters locked folders out of the navigable list, so a user cannot enter one and cannot
    target a descendant — a root-only rule here would accept a destination the picker makes
    unreachable, which is the gap this rule exists to close. The harm is concrete for
    ``shared_tables/``: a table's files acquiring neighbours is how a later projection read starts
    returning rows nobody wrote.

    No separate rule is written for the bucket-root ``_config`` and ``_directory`` documents. They
    live outside every user prefix and containment already makes them unreachable. That is not an
    exemption: a shared space may legitimately contain ``marketing/_config/``, the picker rule is
    anchored at the SPACE root in whichever bucket, and the by-name form correctly refuses it.

    Args:
      root: The authorized destination space root.
      prefix: The destination folder key, absolute.
      space_kind: ``personal`` or ``shared``.

    Returns:
      The refusal, or None when the destination is ordinary.

    Raises:
      None.
    """
    for name in PICKER_LOCKED_FOLDERS:
        if _is_under_root_folder(prefix, root, name):
            return Refusal("destination_folder_locked", f"{name}/ is not a place files can be put")
    if _is_at_or_below(prefix, root, ARCHIVE_FOLDER, space_kind=space_kind):
        return Refusal("destination_archive_read_only", f"{ARCHIVE_FOLDER}/ is read-only")
    return None


def source_refusal(root: str, key: str, operation: str, space_kind: str) -> Refusal | None:
    """Refuses a source a delete or a move would destroy, and refuses nothing for a copy.

    **A copy is deliberately unrestricted here, and that is a capability rather than an oversight.**
    ``athenaresults/`` is picker-locked and undeletable and copying out of it works in the browser
    today; refusing it here would silently remove that, and doing it by folder name would be exactly
    the union the browser's own note forbids.

    The undeletable rule matches the folder ITSELF at the space root. Its contents are ordinary for
    ``saved_queries/`` — visible, deletable, a valid destination — but NOT for the other two: the
    role policy denies ``s3:DeleteObject`` beneath ``athenaresults/``, and IAM denies writes and
    deletes beneath ``archive/``. Without those two depth rules this plane would accept requests its
    own IAM refuses mid-operation, which is the mismatch the deletability assertion exists to
    prevent.

    Args:
      root: The authorized source space root.
      key: The selected item's key, absolute.
      operation: ``copy``, ``move`` or ``delete``.
      space_kind: ``personal`` or ``shared``.

    Returns:
      The refusal, or None when the source may be destroyed.

    Raises:
      None.
    """
    if operation == "copy":
        return None

    for name in UNDELETABLE_ROOT_FOLDERS:
        if _is_root_folder(key, root, name):
            return Refusal("source_folder_undeletable", f"{name}/ cannot be moved or deleted")

    if _is_at_or_below(key, root, ATHENA_RESULTS_FOLDER, space_kind=space_kind):
        return Refusal("results_folder_not_deletable", f"{ATHENA_RESULTS_FOLDER}/ is managed for you")

    if _is_at_or_below(key, root, ARCHIVE_FOLDER, space_kind=space_kind):
        return Refusal("archive_read_only", f"{ARCHIVE_FOLDER}/ is read-only")

    return None


def settings_source_refusal(root: str, key: str) -> Refusal | None:
    """Refuses the space's settings folder as a source, for every operation.

    Written as this plane's own rule rather than by list membership, because ``user_settings`` is
    hidden and picker-locked but deliberately NOT undeletable, so no existing list reaches it.
    Hiding is not enforcement and this plane accepts a hand-crafted envelope; without this rule the
    execution role's own Deny would refuse mid-operation what the code-side rule permitted.

    Args:
      root: The authorized source space root.
      key: The selected item's key, absolute.

    Returns:
      The refusal, or None.

    Raises:
      None.
    """
    if _is_at_or_below(key, root, USER_SETTINGS_FOLDER, space_kind="personal"):
        return Refusal("settings_folder_not_a_source", f"{USER_SETTINGS_FOLDER}/ is managed for you")
    return None


def marker_refusal(key: str) -> Refusal | None:
    """Refuses an explicitly selected undeletable marker, by basename at any depth.

    Both bucket policies deny ``DeleteObject`` on ``*/DO_NOT_DELETE.txt`` and an S3 wildcard matches
    ``/``, so a marker anywhere is already undeletable and selecting one can only fail.

    **Copy is refused too, and this is the one place copy is not free.** Everywhere else on this
    plane a copy is unrestricted, because copying takes nothing away. A marker is the exception:
    both bucket policies deny ``DeleteObject`` on the basename at any depth, so copying one MINTS
    A NEW PERMANENTLY UNDELETABLE OBJECT wherever it lands — litter no user and no plane can ever
    remove. The refusal's wording says so rather than talking about deletion, which would be false
    under the copy prefix.

    **This is about a SELECTED item only.** A marker discovered inside a folder being expanded is
    excluded from the plan rather than refused — ``saved_queries/`` ships its own marker, and
    failing a whole folder delete on a nested one would refuse everything in the folder for the
    sake of the one file nobody can remove.

    Args:
      key: The selected item's key, absolute.

    Returns:
      The refusal, or None.

    Raises:
      None.
    """
    if key.rstrip("/").rsplit("/", 1)[-1] == MARKER_BASENAME:
        return Refusal("marker_not_deletable", f"{MARKER_BASENAME} cannot be copied, moved or deleted")
    return None
