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

  - as a DESTINATION, the picker-locked folders at the root, plus the execution role's
    ``ANY_DEPTH_DENIED_FOLDERS`` wherever they sit — judged on the destination prefix, on every
    item's derived key, and by the manifest builder on every planned object's key;
  - as a DELETE or MOVE SOURCE, the undeletable root folders, plus anything beneath
    ``athenaresults/`` or ``archive/``, plus ``_data-quality-reports/`` and anything in it, plus
    the execution role's ``ANY_DEPTH_DENIED_FOLDERS`` wherever they sit;
  - for EVERY operation, ``user_settings/`` as a source, by this plane's own rule;
  - for EVERY operation INCLUDING COPY, the marker file by basename — see below;
  - as a COPY SOURCE, no FOLDER rule at all. There is deliberately none, and a test says so.

**Two policies are mirrored here, and they differ.** The source rules mirror the PORTAL ROLE's
policy for each bucket — identity policies on the role every signed-in user's requests run under,
not bucket policies — whose asymmetry is kept rather than averaged: in the personal bucket the
prefix IS the principal tag, so the Deny names the caller's own root and
``alice/backups/system_settings/archive/x`` is outside it, while the shared bucket's Deny puts a
wildcard where the space name goes, and an S3 resource wildcard matches ``/`` too, so it reaches
the folder at ANY depth below the space root. ``test_archive_write_lock_mirrors_iam.py`` builds a
key matcher out of each of those policies and runs ``_is_at_or_below`` against it, so that half is
asserted rather than described.

But the plane WRITES and DELETES under its own execution role, which carries no principal tag, so
that role's Denies reach ``ANY_DEPTH_DENIED_FOLDERS`` at any depth in BOTH buckets. A rule anchored
at the root, in either bucket, accepts a key the role then refuses part way through a run.
``role_denied_folder`` is the one reading of those Denies, and every any-depth rule here goes
through it; ``test_file_ops_rules_mirror_execution_role.py`` holds it
against the role's own template.

Every refusal names the folder in operator text and carries its own reason code, so the notifier
can word it without re-deriving which rule fired.
"""

from cpcommon.app_managed import app_managed_prefixes, segments_hold_app_managed

from .config import (
    ANY_DEPTH_DENIED_FOLDERS,
    ARCHIVE_FOLDER,
    ATHENA_RESULTS_FOLDER,
    MARKER_BASENAME,
    PICKER_LOCKED_FOLDERS,
    REPORTS_FOLDER,
    UNDELETABLE_ROOT_FOLDERS,
    USER_SETTINGS_FOLDER,
)
from .outcomes import Refusal
from .paths import normalize_root

__all__ = [
    "derived_destination_refusal",
    "destination_refusal",
    "marker_refusal",
    "planned_write_refusal",
    "role_denied_folder",
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

    Root-anchored in a personal space and any-depth in a shared one, mirroring the portal role's
    Deny in each bucket rather than averaging the two.

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


def role_denied_folder(key: str) -> str | None:
    """Names the folder whose execution-role Deny covers writing or deleting at a key, or None.

    The role's Resources read ``{bucket}/*/user_settings/*`` and ``{bucket}/*/system_settings/
    {athenaresults,archive}/*``, and each means exactly "the key contains ``/name/``": a ``*``
    matches ``/``, so the folder may sit at any depth, but the Resource still needs a ``/`` BEFORE
    the name and one AFTER it. So the scan runs over every segment but the FIRST and the LAST, and
    that slice is the whole rule rather than an approximation of it.

    **Not the first**, and not "below the space root": no root is needed, and none is taken. A user
    literally named ``user_settings`` owns ``user_settings/foo/a.csv``, which no Resource matches,
    and a scan including the first segment refused every delete that user asked for. **Not the
    last**: a file key's last segment is its NAME, and a file *called* ``user_settings`` is not a
    file *inside* one; a folder key's last segment is the empty string after its slash, so the
    folder itself is still inside its parent's scan.

    Args:
      key: The absolute object key, file or folder.

    Returns:
      The folder's name, or None when no role Deny reaches the key.

    Raises:
      None.
    """
    folders = key.split("/")[1:-1]
    for name in ANY_DEPTH_DENIED_FOLDERS:
        if segments_hold_app_managed(folders, name):
            return name
    return None


def planned_write_refusal(keys: list) -> Refusal | None:
    """Refuses a planned item one of whose destination keys its role may not write.

    The manifest builder's check, run over the keys the expansion derived, and the only one of the
    destination rules that can see an object BENEATH a folder item: copying ``alice/stage/``, which
    holds ``stage/user_settings/a.csv``, puts nothing in a denied folder by its prefix or by its own
    name, and still writes one object the role refuses. The whole item is refused rather than the
    objects the role would allow, because a partial copy reported as a failure is the outcome this
    replaces, and it is how a move of the same folder is already refused on its source side.

    Args:
      keys: The item's planned destination keys, absolute.

    Returns:
      The refusal, naming the first key and its folder, or None when every key may be written.

    Raises:
      None.
    """
    for key in keys:
        name = role_denied_folder(key)
        if name is not None:
            return Refusal("write_refused", f"{key!r} sits under {name}/, which this plane may not write")
    return None


def destination_refusal(root: str, prefix: str) -> Refusal | None:
    """Refuses a destination the browser's own picker would never offer, or the role would refuse.

    Every picker-locked folder is refused at the space root, INCLUDING the two a folder-name list
    tends to omit — ``_data-quality-reports/`` and ``shared_tables/`` — whose absence would let this
    plane accept a destination the browser refuses.

    **Then the execution role's folders, at any depth and in either bucket**, which the picker has
    no opinion about: a folder the user made at ``alice/foo/user_settings/`` is an ordinary place to
    the browser, and every write beneath it is denied to this plane. Refusing it here is what turns
    that into a named refusal before anything runs. At the root the picker rule has already
    answered, so this arm speaks only for a nested folder — which is why its reason is its own
    rather than the locked folder's, whose wording says the app manages it. The space's kind
    selects nothing here: the role reads the same in both buckets.

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

    Returns:
      The refusal, or None when the destination is ordinary.

    Raises:
      None.
    """
    for name in PICKER_LOCKED_FOLDERS:
        if _is_under_root_folder(prefix, root, name):
            return Refusal("destination_folder_locked", f"{name}/ is not a place files can be put")
    denied = role_denied_folder(prefix)
    if denied is not None:
        return Refusal("destination_folder_reserved", f"{denied}/ is not a place this plane may write")
    return None


def derived_destination_refusal(root: str, key: str) -> Refusal | None:
    """Refuses an item whose own derived key lands where ``destination_refusal`` refuses a prefix.

    **The prefix is where items are put, not where any of them lands**, so judging it alone let a
    request name an ordinary folder and still write into a locked one: moving
    ``sales/stage/_data-quality-reports/`` into ``sales/`` derives ``sales/_data-quality-reports/``,
    and so does renaming a folder to that name at the root. In a shared space that is one member
    replacing or adding to another member's reports, which the data-quality plane reads back
    between its verbs.

    The same two rules run, over the key ``paths.derived_destination_key`` builds, so the answer
    cannot drift from the prefix's. Once the prefix has passed, a refused derived key is always the
    item's NAME landing on the folder itself, which is what both reason codes say — and they are
    two, because what can truthfully be said differs. A picker-locked name is the app's own folder
    at that root, where another destination is a step worth offering. One of the role's names is
    refused wherever it lands, usually for a folder the user made — which cannot even be renamed
    through this plane, since the source arm refuses it — so its sentence offers no step. Nothing
    beneath a folder item reaches a root-anchored folder its own key does not, and only because
    the two-segment homes share a first segment, ``system_settings/``, that is locked in its own
    right — a folder called that, holding ``athenaresults/``, is refused by its own key. A FILE item
    named like a locked folder is not that folder, since both rules compare the raw key. The
    any-depth arm is different: an object beneath a folder item can reach one of the role's folders
    that the item's own key does not, and ``planned_write_refusal`` is what sees it, once the
    expansion has derived every key.

    Args:
      root: The authorized destination space root.
      key: The item's derived destination key, absolute.

    Returns:
      The refusal, naming the folder, or None when the item may land there.

    Raises:
      None.
    """
    refusal = destination_refusal(root, key)
    if refusal is None:
        return None
    if refusal.reason == "destination_folder_reserved":
        return Refusal("destination_name_kept_for_app", refusal.detail)
    return Refusal("destination_name_reserved", refusal.detail)


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

    **Those two follow the portal role's policies; the last arm follows the execution role**, which
    denies deleting beneath ``ANY_DEPTH_DENIED_FOLDERS`` at any depth in both buckets. The manifest
    builder refuses such an item anyway, before anything is copied, so this arm takes away nothing
    that could have moved or removed a file. What it moves is the SEAT: judged here, the item is
    refused before the rule on its derived key runs, and a move of ``alice/f/user_settings/`` into
    ``alice/g/`` is told it cannot be removed rather than told to choose a different name, which no
    name would fix.

    ``_data-quality-reports/`` is refused with everything in it for a different reason: no Deny
    covers it, and what goes wrong is data rather than a denied call. The data-quality plane writes
    its manifest, report and runs index there under its own role, and in a shared space every
    member's reports share the one folder, so a delete or move here removes someone else's reports.
    Root-anchored in both buckets, because that is the only place the plane writes; a folder a user
    made with that name deeper down is theirs. Copying out stays free, like everywhere else.

    **No execution-role Deny backs it, and that is a choice, not a constraint.** The role carries
    no principal tag, so a Resource cannot anchor at a space root: ``*/_data-quality-reports/*``
    reaches a user's own nested folder of that name too, and this rule, ``focommon.delete`` and the
    destination rules would all have to refuse it at any depth, or the Deny fails a run part way
    through. The results-conversion role takes that trade, where it costs one save location; here
    it would refuse copying, moving and deleting a folder the browser shows as the user's own.

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

    if _is_under_root_folder(key, root, REPORTS_FOLDER):
        return Refusal("reports_folder_not_deletable", f"{REPORTS_FOLDER}/ is managed for you")

    if _is_at_or_below(key, root, ATHENA_RESULTS_FOLDER, space_kind=space_kind):
        return Refusal("results_folder_not_deletable", f"{ATHENA_RESULTS_FOLDER}/ is managed for you")

    if _is_at_or_below(key, root, ARCHIVE_FOLDER, space_kind=space_kind):
        return Refusal("archive_read_only", f"{ARCHIVE_FOLDER}/ is read-only")

    denied = role_denied_folder(key)
    if denied is not None:
        return Refusal("delete_refused", f"{denied}/ is not a place this plane may delete from")

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

    Two identity policies deny ``s3:DeleteObject`` on ``*/DO_NOT_DELETE.txt`` in both buckets: the
    portal role's, which every signed-in user's requests run under, and this plane's own execution
    role's, which every delete and move here runs under. No bucket policy carries it — the
    user-space bucket's policy is a principal allowlist and nothing more, and the shared-space
    bucket has none. An S3 resource wildcard matches ``/``, so a marker anywhere is undeletable by
    the user and by this plane, and selecting one can only fail.

    **Copy is refused too, and this is the one place copy is not free.** Everywhere else on this
    plane a copy is unrestricted, because copying takes nothing away. A marker is the exception:
    those Denies match the basename at any depth, so copying one MINTS A NEW UNDELETABLE OBJECT
    wherever it lands — litter no user can remove, nor this plane, nor the archive plane, whose
    role denies the same basename. Only an operator's own credentials, or the teardown that deletes
    a whole shared space, can clear one. The refusal's wording says so rather than talking about
    deletion, which would be false under the copy prefix.

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
