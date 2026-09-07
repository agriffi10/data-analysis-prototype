"""The server-side half of the rules the browser also enforces as an affordance.

`isWriteLockedPrefix` and the marker check live in the browser so a control can be disabled with
an explanation. They live here too because a disabled button is not a permission, and a request
this API would otherwise perform reaches S3 whether or not a browser would have sent it.

**The two buckets deny different things, and this module mirrors each rather than averaging
them.** The user-space bucket's Deny is root-anchored — `{root}archive/` and below. The
shared-space bucket's wildcard segment matches `/` too, so *any* `archive` folder below the space
root is covered. Averaging them either leaves a hole on one bucket or refuses work the other
permits, and both failures are invisible until someone hits them.
``test_archive_write_lock_mirrors_iam.py`` is what keeps this paragraph honest: it builds a key
matcher out of each bucket policy and runs ``is_write_locked`` against it, so the asymmetry is
asserted rather than described.

**Key containment wraps `cpcommon.paths` rather than calling it bare.** `assert_inside_root`
raises `TerminalError`, which `errors.for_exception` does not recognise, so an unwrapped call
answers **500 InternalError** where the requirement is **403 AccessDenied**. It fails *safely*, so
a test asserting "no AWS call happened" passes over it — the assertions here are on the reason
code.
"""

from cpcommon.app_managed import RECEIPT_FOLDER, app_managed_prefixes
from cpcommon.errors import TerminalError
from cpcommon.paths import assert_inside_root, has_dot_segment, normalize_root
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
    """Returns a listing prefix, having refused one that escapes the space root.

    **A prefix is not a key, and the difference is load-bearing.**
    ``assert_inside_root(root, "")`` raises — an empty key is meaningless — but an empty prefix is
    the file browser's very first listing request. So the empty case is admitted here and the
    containment rule is otherwise identical.

    Args:
      space: The resolved space.
      prefix: The caller-supplied listing prefix, possibly empty.

    Returns:
      The absolute prefix to list, always inside the root.

    Raises:
      ApiError: ``AccessDenied`` when the prefix carries a dot segment or escapes the root.
    """
    if not prefix:
        return space.root
    if has_dot_segment(prefix):
        raise ApiError("AccessDenied", "prefix contains a path segment that is not allowed")
    absolute = prefix if prefix.startswith(space.root) else f"{normalize_root(space.root)}{prefix}"
    if not absolute.startswith(space.root):
        raise ApiError("AccessDenied", "prefix is not inside the space root")
    return absolute


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

    The comparison is against ``{root}archive/`` **with its slash**, which is what the rendered Deny
    says. Matching the slashless form too would refuse a *file* literally named ``archive`` at a
    space root, which IAM permits and the browser's predicate allows — a bare 403 for an upload
    that would have worked.

    **The shared bucket's segment scan drops the final segment of a file key for that same
    reason**, and it did not until a test read the Deny instead of describing it: the anchored arm
    above gets its slash from ``app_managed_prefixes``, but a bare ``in segments`` finds the word
    in a key's LAST segment too, so ``finance/reports/archive`` — a file *called* ``archive``, not
    a file *inside* one — matched a Deny whose Resource requires ``/archive/``.
    ``focommon.protected._is_at_or_below`` already made this distinction; this copy did not.

    Args:
      space: The resolved space.
      key: The object key or prefix being written.

    Returns:
      True if the location is write-locked.

    Raises:
      None.
    """
    if key.startswith(app_managed_prefixes(space.root, RECEIPT_FOLDER)):
        return True
    if space.kind != "shared":
        return False
    if not key.startswith(space.root):
        return False
    segments = key[len(space.root) :].split("/")
    return RECEIPT_FOLDER in (segments if key.endswith("/") else segments[:-1])


def assert_writable(space: ResolvedSpace, key: str) -> None:
    """Refuses a write into a location the bucket policy write-locks.

    **The marker rule is deliberately NOT here, and the split is the whole point.** Both bucket
    policies Deny ``s3:DeleteObject`` on ``*/DO_NOT_DELETE.txt`` and nothing else — creating one is
    permitted, and it is how a space's prefix is held open in the first place. Folding the marker
    into this check made a route stricter than the policy it claims to mirror and refused
    ``ensurePrefixMarker`` and ``ensureSavedQueriesFolder``: a brand-new user's prefix would never
    be created and a saved-queries folder would vanish once emptied, both failing as a *best-effort*
    background write that logs and carries on.

    Args:
      space: The resolved space.
      key: The object key being created.

    Returns:
      None.

    Raises:
      ApiError: ``AccessDenied`` for a write-locked location.
    """
    if is_write_locked(space, key):
        raise ApiError("AccessDenied", "archived locations are not writable")


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
      ApiError: ``AccessDenied`` for a marker key or a write-locked location.
    """
    if is_marker(key):
        raise ApiError("AccessDenied", "folder markers may not be removed or replaced")
    assert_writable(space, key)
