"""Key containment and the destination layout for the file-send control plane.

Containment is the one place on this plane where a bug is a cross-tenant read, so the rule it
enforces is written as **two independent checks** rather than one, and each has its own test.

SPEC-165 added the second half: the destination layout. ``destination_key`` is the ONE builder
for every key this plane writes, and it lives here rather than in a verb because the layout is
what a recipient sees forever — a verb that concatenated its own would be free to disagree with
it, and the disagreement would show up as files landing in the wrong inbox rather than as an
error. A test forbids any verb building one by hand.

Attributes:
  _DOT_SEGMENTS: The path segments refused outright wherever they appear in a key.
"""

from cpcommon.errors import TerminalError

from .config import SHARED_FILES_FOLDER

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
    exist. It is required because the same string becomes the ``itemName`` in this plane's
    destination-key builder, where a dot segment produces a legal-but-nonsense destination
    inside somebody's inbox — and because a rule that holds only while every downstream
    consumer stays careful is not a rule.

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


def item_name(key: str) -> str:
    """Returns the name a selected item arrives under in the recipient's inbox.

    The last path segment, with a folder's trailing slash removed first — so ``alice/reports/``
    and ``alice/reports`` both name ``reports``, and ``alice/deep/nested/q1.csv`` names
    ``q1.csv``. **This is what makes the destination independent of the sender's own folder
    depth** (FR-003): a recipient sees what was sent, not where it lived.

    Args:
      key: The selected item's key, already confirmed inside the authorized root.

    Returns:
      The item's name.

    Raises:
      TerminalError: ``forbidden`` when the key has no final segment at all — ``""`` or a key
        of nothing but slashes. Nothing should reach here with one, since validate-authorize
        refuses an empty key outright; it fails rather than relying on that, because a name
        that came back empty would collapse every destination onto the sender's inbox root and
        merge one send into another.
    """
    name = key.rstrip("/").rsplit("/", 1)[-1]
    if not name:
        raise TerminalError("forbidden", f"{key!r} has no item name")
    return name


def relative_key(item_key: str, object_key: str) -> str:
    """Returns a listed object's key relative to the item that was selected.

    The rule that makes a folder arrive with its structure intact and a file arrive as a file:
    ``alice/reports/2026/q1.csv`` under a selected ``alice/reports/`` keeps ``2026/q1.csv``,
    and a selected file keeps ``""``.

    Args:
      item_key: The selected item's key — a folder's carries its trailing slash.
      object_key: The absolute key of an object found under it.

    Returns:
      The object's key relative to the item, empty for a file item.

    Raises:
      TerminalError: ``forbidden`` when the object does not sit under the item. A listing
        cannot normally produce one, so this is the same class of check as the containment
        re-test beside it: the key arrived from S3 rather than from the request, and a
        relative key computed by slicing the wrong length would silently re-root the object.
    """
    if not object_key.startswith(item_key):
        raise TerminalError("forbidden", f"{object_key!r} is not under {item_key!r}")
    return object_key[len(item_key) :]


def inbox_prefix(target_root: str, sender: str) -> str:
    """Returns the prefix one sender's inbox occupies inside a recipient's space.

    ``{targetRoot}shared_files/{sender}/`` — everything that sender has ever sent to that
    recipient, and nothing anyone else sent. It is factored out of ``destination_key`` below
    rather than written twice because SPEC-166's conflict guard needs the prefix without a key:
    it asks what item names the inbox ALREADY holds, which is one listing at this prefix rather
    than a probe per selected item. A guard that composed the prefix itself would be the second
    builder the sweep in ``test_paths_fscommon`` exists to forbid.

    Args:
      target_root: The recipient's space root, with or without its trailing slash.
      sender: The verified sender's username.

    Returns:
      The inbox prefix, ending in a slash so a listing under it cannot match a sibling whose
      name merely starts the same way.

    Raises:
      TerminalError: ``forbidden`` when the target root is empty or the sender is missing.
        Either would widen the prefix to somebody else's data — an empty sender lists every
        sender's inbox, and the guard would then refuse a name a different sender used.
    """
    root = normalize_root(target_root)
    if not sender:
        raise TerminalError("forbidden", "an inbox prefix needs the sender")
    return f"{root}{SHARED_FILES_FOLDER}/{sender}/"


def inbox_label(sender: str) -> str:
    """Returns the inbox's location as a person would read it, relative to their space root.

    ``shared_files/{sender}/`` — the phrase a notification uses to tell a recipient where their
    files landed, which is the one thing they cannot guess. It lives HERE rather than in the
    message table for the same reason the key builder does: the layout has one home, and the
    sweep in ``test_paths_fscommon`` forbids any other module naming the folder at all — a
    sentence that drifted from the keys would send people looking in the wrong place.

    Args:
      sender: The verified sender's username, which namespaces the inbox.

    Returns:
      The root-relative inbox path.

    Raises:
      TerminalError: ``forbidden`` when the sender is missing, which would render a sentence
        pointing at the inbox root shared by every sender.
    """
    if not sender:
        raise TerminalError("forbidden", "an inbox label needs the sender")
    return f"{SHARED_FILES_FOLDER}/{sender}/"


def destination_key(target_root: str, sender: str, item: str, rel_key: str) -> str:
    """Builds the ONE destination key for a sent object.

    The layout is ``{targetRoot}shared_files/{sender}/{item}[/{relKey}]`` — an inbox namespaced
    by who sent it, mirroring ``shared_tables/{table}/``. Two senders cannot collide, and the
    provenance of a received file is visible in the file browser with no metadata lookup.

    Every downstream verb calls this rather than composing its own, and a test enforces it.
    ``shared_files`` is a constant in ``config`` for the same reason: a literal repeated across
    verbs is a layout that can drift one verb at a time.

    Args:
      target_root: The recipient's space root — the user-space or shared-space bucket prefix —
        with or without its trailing slash.
      sender: The verified sender's username, which namespaces the inbox.
      item: The selected item's name, from ``item_name``.
      rel_key: The object's key relative to that item; empty for a file item.

    Returns:
      The absolute destination key inside the recipient's bucket.

    Raises:
      TerminalError: ``forbidden`` when the target root is empty, or when the sender or item is
        missing. Each would fold the destination up a level — an empty sender would put one
        person's files where the inbox itself belongs.
    """
    if not sender or not item:
        raise TerminalError("forbidden", f"destination needs a sender and an item name, got {sender!r}/{item!r}")
    base = f"{inbox_prefix(target_root, sender)}{item}"
    return f"{base}/{rel_key}" if rel_key else base
