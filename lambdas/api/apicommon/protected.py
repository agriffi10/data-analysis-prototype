"""The server-side half of the rules the browser also enforces as an affordance.

`isWriteLockedPrefix` and the marker check live in the browser so a control can be disabled with
an explanation. They live here too because a disabled button is not a permission, and a request
this API would otherwise perform reaches S3 whether or not a browser would have sent it.

**The two buckets deny different things, and this module mirrors each rather than averaging
them.** The user-space bucket's Deny is root-anchored — `{root}system_settings/archive/` and
below. The shared-space bucket's wildcard segment matches `/` too, so a `system_settings/archive`
pair at *any* depth below the space root is covered. Averaging them either leaves a hole on one
bucket or refuses work the other permits, and both failures are invisible until someone hits them.
``test_archive_write_lock_mirrors_iam.py`` is what keeps this paragraph honest: it builds a key
matcher out of each bucket policy and runs ``is_write_locked`` against it, so the asymmetry is
asserted rather than described.

**The query results folder is refused too, though IAM permits the write.** Both buckets Deny
``s3:DeleteObject`` beneath it and nothing else, so an upload or a folder made there can never be
removed — the marker's reason, applied to a whole folder. Its Deny has the receipt folder's shape,
so the same test holds this rule against it.

**Key containment wraps `cpcommon.paths` rather than calling it bare.** `assert_inside_root`
raises `TerminalError`, which `errors.for_exception` does not recognise, so an unwrapped call
answers **500 InternalError** where the requirement is **403 AccessDenied**. It fails *safely*, so
a test asserting "no AWS call happened" passes over it — the assertions here are on the reason
code.
"""

from cpcommon.app_managed import (
    ATHENA_RESULTS_FOLDER,
    RECEIPT_FOLDER,
    app_managed_prefixes,
    segments_hold_app_managed,
)
from cpcommon.errors import TerminalError
from cpcommon.paths import assert_inside_root, has_dot_segment
from cpcommon.s3_listing import MARKER_BASENAME

from .envelope import ApiError
from .spaces import ResolvedSpace


def contained_key(space: ResolvedSpace, key: str) -> str:
    """Returns the key, having refused one that escapes the space root.

    The space comes from verified claims; the KEY is still the caller's, and nothing upstream
    checks it. A key carrying ``..`` resolves outside the prefix the claims authorize.

    Args:
      space: The resolved space.
      key: The caller-supplied object key.

    Returns:
      The key, unchanged, when it is inside the root.

    Raises:
      ApiError: ``AccessDenied`` when the key is empty, carries a dot segment, or resolves
        outside the root. Never ``TerminalError`` — see the module docstring.
    """
    try:
        return assert_inside_root(space.root, key)
    except TerminalError as exc:
        raise ApiError("AccessDenied", "key is not inside the space root") from exc


def contained_prefix(space: ResolvedSpace, prefix: str) -> str:
    """Returns a listing prefix, having refused one that is not inside the space root.

    **A prefix is not a key, and the difference is load-bearing.**
    ``assert_inside_root(root, "")`` raises — an empty key is meaningless — but an empty prefix is
    the file browser's very first listing request. So the empty case is admitted here and the
    containment rule is otherwise identical.

    **A prefix is absolute, like every key the API takes, and it has no second reading.** Accepting
    a prefix relative to the root as well means guessing the form from the value, and the guess is
    ambiguous whenever a folder shares its space's name: ``alice/`` is both the root of ``alice``'s
    space and, relatively, the folder ``alice/alice/``. So a prefix outside the root is refused
    rather than re-rooted, and ``alice/alice/`` is the one way to name that folder. The listing's
    rows carry absolute keys, so a caller that feeds a row back as the next prefix already sends
    this form.

    Args:
      space: The resolved space.
      prefix: The caller-supplied listing prefix, absolute or empty.

    Returns:
      The prefix to list, always inside the root.

    Raises:
      ApiError: ``AccessDenied`` when the prefix carries a dot segment or does not start with the
        root, a relative prefix included.
    """
    if not prefix:
        return space.root
    if has_dot_segment(prefix):
        raise ApiError("AccessDenied", "prefix contains a path segment that is not allowed")
    if not prefix.startswith(space.root):
        raise ApiError("AccessDenied", "prefix is not inside the space root")
    return prefix


def is_marker(key: str) -> bool:
    """Whether a key is a folder marker, by BASENAME.

    Takes ``cpcommon``'s constant rather than its ``is_ignored`` predicate: that one also folds in
    ``athenaresults/`` and ``user_settings/``, which are listing conveniences the API must not
    inherit as write rules.

    Args:
      key: The object key.

    Returns:
      True if the key's basename is the marker.

    Raises:
      None.
    """
    return key.rsplit("/", 1)[-1] == MARKER_BASENAME


def is_write_locked(space: ResolvedSpace, key: str) -> bool:
    """Whether writing at this key is denied by the bucket's own archive rule.

    Mirrors ``isWriteLockedPrefix`` in the browser, including its asymmetry — see the module
    docstring for why the two buckets differ.

    The comparison is against every home the receipt folder occupies — since the move, the one
    home ``{root}system_settings/archive/`` — **with its slash**, which is what the rendered Deny
    says. The builder is what supplies it rather than a literal here, which is why this arm followed
    the folder without being edited. Matching the slashless form would refuse a
    *file* literally named ``archive`` at a space root, which IAM permits and the browser's
    predicate allows — a bare 403 for an upload that would have worked.

    **The shared bucket's segment scan drops the final segment of a file key for that same
    reason**, and it did not until a test read the Deny instead of describing it: the anchored arm
    above gets its slash from ``app_managed_prefixes``, but a bare ``in segments`` finds the word
    in a key's LAST segment too, so ``finance/reports/archive`` — a file *called* ``archive``, not
    a file *inside* one — matched a Deny whose Resource requires ``/archive/``.
    ``focommon.protected._is_at_or_below`` already made this distinction; this copy did not.

    Both copies then made the same second mistake, and it took the move to expose it: each looked
    for the bare folder NAME, which was right only while the Deny was anchored one segment deep.
    The scan now goes through ``segments_hold_app_managed``, so the pair the Deny actually names
    is what either copy looks for.

    Args:
      space: The resolved space.
      key: The object key or prefix being written.

    Returns:
      True if the location is write-locked.

    Raises:
      None.
    """
    return _is_at_or_below(space, key, RECEIPT_FOLDER)


def is_in_results_folder(space: ResolvedSpace, key: str) -> bool:
    """Whether a key is in the query results folder, where nothing written can be removed.

    Not part of ``is_write_locked``, which mirrors a ``PutObject`` Deny: here IAM permits the write
    and denies only the delete. The Deny's reach is the receipt folder's — root-anchored in a
    personal space, the ``system_settings/athenaresults`` pair at any depth in a shared one — so
    the same scan answers it.

    Args:
      space: The resolved space.
      key: The object key or prefix being written.

    Returns:
      True if the key is the results folder or inside it.

    Raises:
      None.
    """
    return _is_at_or_below(space, key, ATHENA_RESULTS_FOLDER)


def _is_at_or_below(space: ResolvedSpace, key: str, folder: str) -> bool:
    """Whether a key is an app-managed folder or inside it, as that bucket's Deny reaches it.

    Root-anchored for either kind, and a segment scan for the folder's pair in a shared space only.
    The scan drops a file key's last segment, because a file NAMED like the folder is not a file
    inside it.

    Args:
      space: The resolved space.
      key: The object key or prefix.
      folder: The app-managed folder's name.

    Returns:
      True if the key is at or below the folder.

    Raises:
      None.
    """
    if key.startswith(app_managed_prefixes(space.root, folder)):
        return True
    if space.kind != "shared":
        return False
    if not key.startswith(space.root):
        return False
    segments = key[len(space.root) :].split("/")
    return segments_hold_app_managed(segments if key.endswith("/") else segments[:-1], folder)


def assert_writable(space: ResolvedSpace, key: str) -> None:
    """Refuses a write into a location the bucket policy write-locks, or one it would never let go.

    **The marker rule is deliberately NOT here, and the split is the whole point.** Both bucket
    policies Deny ``s3:DeleteObject`` on ``*/DO_NOT_DELETE.txt`` and nothing else — creating one is
    permitted, and it is how a space's prefix is held open in the first place. Folding the marker
    into this check made a route stricter than the policy it claims to mirror and refused
    ``ensurePrefixMarker`` and ``ensureSavedQueriesFolder``: a brand-new user's prefix would never
    be created and a saved-queries folder would vanish once emptied, both failing as a *best-effort*
    background write that logs and carries on.

    **The results folder IS here, though IAM permits its writes too, and the marker is why that
    needs saying.** A rule stricter than the policy is wrong exactly when something legitimate
    writes through it. Nothing does here: Athena delivers its results itself, and the browser only
    copies them out. What a caller writes here instead is an object nobody can delete.

    Args:
      space: The resolved space.
      key: The object key being created.

    Returns:
      None.

    Raises:
      ApiError: ``AccessDenied`` for a write-locked location or the results folder, each with its
        own detail.
    """
    if is_write_locked(space, key):
        raise ApiError("AccessDenied", "archived locations are not writable")
    if is_in_results_folder(space, key):
        raise ApiError("AccessDenied", "the query results folder is not writable")


def assert_replaceable(space: ResolvedSpace, key: str) -> None:
    """Refuses removing or replacing what is already at a key.

    Everything ``assert_writable`` refuses, plus the marker — because the marker's protection is
    about **removal**, not about existence. This is the rule for a delete, for a move's SOURCE
    (a move deletes it), for a copy or move DESTINATION, and for a write that has asked to
    overwrite. Replacing a marker's bytes with another object is permitted by IAM and refused
    everywhere in this app: the prefix would stay open while the file sat at a key the listing
    hides by basename and the bucket policy will not let anyone delete.

    Args:
      space: The resolved space.
      key: The object key whose existing content would go.

    Returns:
      None.

    Raises:
      ApiError: ``AccessDenied`` for a marker key, a write-locked location or the query results
        folder.
    """
    if is_marker(key):
        raise ApiError("AccessDenied", "folder markers may not be removed or replaced")
    assert_writable(space, key)
