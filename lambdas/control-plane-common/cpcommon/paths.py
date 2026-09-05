"""Key containment, shared by every control plane that reads a user's space.

**This is an ALGORITHM, so it lives here**: the rule that decides whether a key the
browser supplied sits inside the root the caller was authorized for is the same rule on every
plane, and a second copy of it is a second place a cross-tenant read can be introduced. It
arrived on ``fscommon.paths`` and moved here on the third
plane to need it; ``fscommon.paths`` now re-exports these names, so the file-send call sites and
their tests are unchanged.

The domain layers keep what is theirs: fscommon's inbox layout, arcommon's archived-key layout
and its inverse. Only the containment question is here; the app-managed folder NAMES and the
depth-one prefix builders they anchor are ``cpcommon.app_managed``, beside the vault root the
archive plane and the API both spell.

Attributes:
  _DOT_SEGMENTS: The path segments refused outright wherever they appear in a key.
"""

from .errors import TerminalError

_DOT_SEGMENTS = frozenset({".", ".."})


def normalize_root(root: str) -> str:
    """Returns a space root prefix with exactly one trailing slash.

    Args:
      root: The authorized space root, with or without its trailing slash.

    Returns:
      The root ending in a single ``/``.

    Raises:
      TerminalError: ``forbidden`` when the root is empty, which would make every key
        "inside" it.
    """
    if not isinstance(root, str) or not root.strip("/"):
        raise TerminalError("forbidden", "empty source root")
    return root.rstrip("/") + "/"


def has_dot_segment(key: str) -> bool:
    """Reports whether any path segment of a key is ``.`` or ``..``.

    Args:
      key: The S3 key to inspect.

    Returns:
      True when a dot segment is present.

    Raises:
      None.
    """
    return any(segment in _DOT_SEGMENTS for segment in key.split("/"))


def assert_inside_root(root: str, key: str) -> str:
    """Confirms a selected key sits inside the authorized source root, or fails terminally.

    **TWO RULES, BECAUSE EITHER ALONE LEAVES A HOLE.**

    (a) The root comparison is on a **trailing-slash-normalised** prefix. This is what refuses
    ``alice2/reports/q1.csv`` against root ``alice/`` — a raw ``key.startswith(root)`` on the
    unnormalised root accepts it, and the two usernames need not be related for one to be a
    prefix of the other.

    (b) Any key containing a ``.`` or ``..`` **path segment** is refused outright.
    Normalisation does nothing about dot segments, and
    ``"alice/../bob/secrets.csv".startswith("alice/")`` is ``True``.

    Rule (b) is **not an exploitable read today**, and it is worth being precise about why it
    is required anyway. S3 keys are opaque bytes: neither ``ListObjectsV2`` nor ``GetObject``
    resolves ``..``, so such a key simply names an object that almost certainly does not
    exist. It is required because the same string is concatenated into a destination key
    downstream — an inbox key on file-send, an archive key on the archive plane — where a dot
    segment produces a legal-but-nonsense destination, and because a rule that holds only while
    every downstream consumer stays careful is not a rule.

    Args:
      root: The authorized space root prefix.
      key: The selected item's key, exactly as the request supplied it.

    Returns:
      The key, unchanged, so this reads as a checkpoint at the call site.

    Raises:
      TerminalError: ``forbidden`` when the key is not a non-empty string, carries a dot
        segment, or does not sit inside the normalised root.
    """
    prefix = normalize_root(root)
    if not isinstance(key, str) or not key:
        raise TerminalError("forbidden", "item key missing")
    if has_dot_segment(key):
        raise TerminalError("forbidden", f"{key!r} contains a path segment that is not allowed")
    if not key.startswith(prefix):
        raise TerminalError("forbidden", f"{key!r} is not inside {prefix!r}")
    return key
