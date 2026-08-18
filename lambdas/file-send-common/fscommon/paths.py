"""Key containment and the destination layout for the file-send control plane.

Containment is the one place on this plane where a bug is a cross-tenant read, so the rule it
enforces is written as **two independent checks** rather than one, and each has its own test.

**Those two checks moved to ``cpcommon.paths``** and are re-exported here, so
every call site and every test on this plane is unchanged. The move is the rule applied
to the third plane that needed the rule: containment is an ALGORITHM, and the archive plane
asking the identical question would otherwise have been a second copy of it — in the one place
where a copy that drifts is a cross-tenant read. What stays here is what is genuinely
file-send's: the inbox layout below.

The expansion added that second half. ``destination_key`` is the ONE builder for every key this plane
writes, and it lives here rather than in a verb because the layout is what a recipient sees
forever — a verb that concatenated its own would be free to disagree with it, and the
disagreement would show up as files landing in the wrong inbox rather than as an error. A test
forbids any verb building one by hand.
"""

from cpcommon.errors import TerminalError
from cpcommon.paths import assert_inside_root, has_dot_segment, normalize_root

from .config import SHARED_FILES_FOLDER

__all__ = [
    "assert_inside_root",
    "destination_key",
    "has_dot_segment",
    "inbox_label",
    "inbox_prefix",
    "item_name",
    "normalize_root",
    "relative_key",
]


def item_name(key: str) -> str:
    """Returns the name a selected item arrives under in the recipient's inbox.

    The last path segment, with a folder's trailing slash removed first — so ``alice/reports/``
    and ``alice/reports`` both name ``reports``, and ``alice/deep/nested/q1.csv`` names
    ``q1.csv``. **This is what makes the destination independent of the sender's own folder
    depth** a recipient sees what was sent, not where it lived.

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
    rather than written twice because the conflict guard needs the prefix without a key:
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
