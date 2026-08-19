"""Key containment and the derived destination for the file-operations control plane.

Containment is the one place on this plane where a bug is a cross-tenant read or write, so it is
**not written here**: ``cpcommon.paths`` owns it and this module re-exports the names. A second
copy of that rule is a second place the same failure can be introduced.

What is genuinely this plane's is below, and it is one function's worth of subtlety.
``derived_destination_key`` answers "where does this item actually land?", and every guard that
matters — the same-key no-op, the into-itself refusal, the collision between two selected items —
compares its output rather than the request's ``destination.prefix``. The prefix is the folder
items are copied *into*; it is not where any of them ends up.

``item_name`` is copied from ``fscommon.paths`` rather than imported, and the copy is deliberate:
the two layers are packaged and attached separately, and ``fscommon`` carries file-send's wording,
so importing it would merge two domain layers to save nine lines. What is **not** copied is
``fscommon.paths.destination_key``, which prepends an inbox prefix this plane has no business
writing to.
"""

from cpcommon.errors import TerminalError
from cpcommon.paths import assert_inside_root, has_dot_segment, normalize_root

from .config import MAX_TARGET_NAME

__all__ = [
    "assert_inside_root",
    "derived_destination_key",
    "has_dot_segment",
    "item_name",
    "normalize_root",
    "validate_target_name",
]

_CONTROL_CHARS = frozenset(chr(code) for code in range(0x20))

_DOT_NAMES = frozenset({".", ".."})


def item_name(key: str) -> str:
    """Returns a selected item's own leaf name.

    The last path segment, with a folder's trailing slash removed first — so ``alice/reports/`` and
    ``alice/reports`` both name ``reports``.

    Args:
      key: The selected item's key, already confirmed inside the authorized root.

    Returns:
      The item's name.

    Raises:
      TerminalError: ``forbidden`` when the key has no final segment at all. Nothing should reach
        here with one, since validate-authorize refuses an empty key outright; it fails rather than
        relying on that, because a name that came back empty would collapse the derived destination
        onto the destination prefix itself.
    """
    name = key.rstrip("/").rsplit("/", 1)[-1]
    if not name:
        raise TerminalError("forbidden", f"{key!r} has no item name")
    return name


def validate_target_name(name: object) -> str:
    """Confirms a per-item destination name is one path segment a user could have typed.

    Mirrors the browser's own leaf rule — non-empty after trimming, no surrounding whitespace, no
    ``/``, no control characters — and adds the two the browser's version does not carry, because
    the browser only ever names a folder the user is looking at while this plane accepts a
    hand-crafted envelope: dot segments, and a length cap.

    **The empty string is the case that makes this load-bearing.** An unvalidated ``""`` derives to
    the destination prefix itself, which merges a folder's *contents* into the destination and then,
    for a move, deletes the source. It also defeats the same-key rule, because the derived key is
    then the destination folder rather than a child of it.

    A name containing ``/`` or a dot segment is not covered by the containment rules, which govern
    keys rather than names — and S3 does not normalise, so the result would be a real object no
    listing renders and the browser can never reach or delete.

    Args:
      name: The requested destination name, exactly as the request supplied it.

    Returns:
      The name, unchanged.

    Raises:
      TerminalError: ``invalid_target_name`` for a non-string, an empty or whitespace-padded name,
        one containing ``/`` or a control character, a ``.`` or ``..`` segment, or one over the
        length cap.
    """
    if not isinstance(name, str) or not name:
        raise TerminalError("invalid_target_name", f"{name!r} is not a usable name")
    if name != name.strip():
        raise TerminalError("invalid_target_name", f"{name!r} has leading or trailing spaces")
    if "/" in name:
        raise TerminalError("invalid_target_name", f"{name!r} contains a slash")
    if any(char in _CONTROL_CHARS for char in name):
        raise TerminalError("invalid_target_name", f"{name!r} contains a control character")
    if name in _DOT_NAMES:
        raise TerminalError("invalid_target_name", f"{name!r} is a path segment, not a name")
    if len(name) > MAX_TARGET_NAME:
        raise TerminalError("invalid_target_name", f"a name of {len(name)} characters is too long")
    return name


def derived_destination_key(destination_prefix: str, item: dict) -> str:
    """Returns where one selected item actually lands, which is never the destination prefix.

    ``{destinationPrefix}{name}`` — re-normalised to a trailing slash when the item is a folder,
    and that re-normalisation is the whole point rather than tidiness. A folder source key carries
    its trailing slash, ``item_name`` strips one, and so a naive concatenation yields
    ``alice/reports`` against a source of ``alice/reports/``: unequal, the same-key rule never
    fires, and a move deletes the source after copying every object onto itself.

    **The name is the item's own only when it did not ask for another.** ``targetName`` is what
    makes a RENAME and a same-folder auto-numbered copy expressible at all: both send the
    containing folder as the prefix and a different name. Deriving from the key alone breaks rename
    in both directions — send the parent and the derived key equals the source, so the operation
    reports success having renamed nothing; send the new prefix and the item nests inside itself.

    The fallback is on ABSENCE, not falsiness. An empty ``targetName`` is a request that named
    something unusable, and it is refused by ``validate_target_name``; silently substituting the
    item's own name there would turn the sharpest hole on this plane into a successful operation
    nobody asked for.

    Args:
      destination_prefix: The authorized destination folder, with its trailing slash.
      item: The selected item, carrying ``kind``, ``key`` and optionally ``targetName``.

    Returns:
      The absolute key this item lands at, ending in a slash when the item is a folder.

    Raises:
      TerminalError: ``invalid_target_name`` when a supplied name is unusable, or ``forbidden``
        when the item's key has no final segment.
    """
    requested = item.get("targetName")
    name = validate_target_name(requested) if requested is not None else item_name(item["key"])
    derived = f"{normalize_root(destination_prefix)}{name}"
    return f"{derived}/" if item.get("kind") == "folder" else derived
