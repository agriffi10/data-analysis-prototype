"""Key containment and the derived destination for the file-operations control plane.

Containment is the one place on this plane where a bug is a cross-tenant read or write, so it is
**not written here**: ``cpcommon.paths`` owns it and this module re-exports the names. A second
copy of that rule is a second place the same failure can be introduced.

What is genuinely this plane's is below, and it is one function's worth of subtlety.
``destination_key`` answers "where does this OBJECT land?" and ``derived_destination_key`` answers
"where does this ITEM land?" — the second is the first with an empty relative key, deliberately,
because two functions that agree today are two functions that can stop agreeing. Every guard that
matters — the same-key no-op, the into-itself refusal, the collision between two selected items —
compares their output rather than the request's ``destination.prefix``. The prefix is the folder
items are copied *into*; it is not where any of them ends up.

**There is exactly ONE builder and a sweep enforces it**, because the destination tests can only
prove the one right: a verb that composed its own would pass every one of them while writing
somewhere else, and on a move that is the source deleted after the copy went to the wrong place.

``item_name`` is copied from ``fscommon.paths`` rather than imported, and the copy is deliberate:
``fscommon`` carries file-send's wording, so importing it would merge two planes' domain
vocabularies to save nine lines. The image puts both on ``/opt/python``, so the import would
resolve — the separation is a code decision, not a packaging one. What is **not** copied is
``fscommon.paths.destination_key``, which prepends an inbox prefix this plane has no business
writing to.
"""

from cpcommon.errors import TerminalError
from cpcommon.paths import assert_inside_root, has_dot_segment, normalize_root

from .config import FILE_OPS_SAMPLE_PATH_CHARS, MAX_TARGET_NAME

__all__ = [
    "assert_inside_root",
    "derived_destination_key",
    "destination_key",
    "has_dot_segment",
    "item_name",
    "normalize_root",
    "relative_key",
    "shorten_for_display",
    "validate_target_name",
]

_CONTROL_CHARS = frozenset(chr(code) for code in range(0x20))

_DOT_NAMES = frozenset({".", ".."})

_ITEM_KINDS = frozenset({"file", "folder"})


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
    ``/``, no control characters, not ``.`` or ``..`` — and adds the one the browser's version does
    not carry, because this plane accepts a hand-crafted envelope: a length cap. **The cap is
    applied to characters AND to encoded bytes**, because S3's own limit is 1024 BYTES for a whole
    key: 255 astral characters is 1020 bytes and would leave nothing for the prefix the name sits
    under.

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
    if len(name) > MAX_TARGET_NAME or len(name.encode("utf-8")) > MAX_TARGET_NAME:
        raise TerminalError("invalid_target_name", f"a name of {len(name)} characters is too long")
    return name


def relative_key(item_key: str, object_key: str) -> str:
    """Returns an object's key relative to the selected item it was found under.

    What keeps a folder's structure intact: ``alice/reports/2026/q1.csv`` under a selected
    ``alice/reports/`` is ``2026/q1.csv``, and it lands under whatever the item is renamed to.

    Args:
      item_key: The selected folder's key, with its trailing slash.
      object_key: An absolute key from the listing beneath it.

    Returns:
      The relative key.

    Raises:
      TerminalError: ``forbidden`` when the object is not inside the item. It cannot happen through
        the listing — the prefix asked for is the item — but the value of the check is that the
        relative key is a SUBSTRING OPERATION, and one taken against the wrong prefix silently
        yields a plausible key rather than an error.
    """
    prefix = normalize_root(item_key) if item_key.endswith("/") else item_key
    if not object_key.startswith(prefix):
        raise TerminalError("forbidden", f"{object_key!r} is not inside {prefix!r}")
    return object_key[len(prefix) :]


def destination_key(
    destination_prefix: str, target_name: str, rel_key: str, *, is_folder: bool
) -> str:
    """Returns where ONE object lands. The only function on this plane that composes a destination.

    ``{destinationPrefix}{targetName}`` for a file item, and ``{destinationPrefix}{targetName}/``
    plus the object's relative key for a folder — so the layout is unaffected by how deep the
    source sat: moving ``alice/deep/nested/q1.csv`` into ``alice/out/`` yields ``alice/out/q1.csv``,
    not a rebuilt copy of the source's own path.

    **The folder form is re-normalised to a trailing slash even when it carries no relative key**,
    and that residue is what re-opened the data-loss path during review: ``item_name`` strips the
    slash, so a naive concatenation yields ``alice/reports`` against a source of ``alice/reports/``
    — unequal, so the same-key rule never fires, and a move copies a folder onto itself and then
    deletes it.

    Args:
      destination_prefix: The authorized destination folder, absolute.
      target_name: The item's own name, or the one the request asked for.
      rel_key: The object's key relative to its selected item; empty for a file item and for the
        folder itself.
      is_folder: Whether the selected item is a folder, which is what decides the trailing slash.

    Returns:
      The absolute key this object lands at.

    Raises:
      TerminalError: ``invalid_target_name`` when the name is unusable, or ``forbidden`` when the
        destination prefix is empty.
    """
    if not isinstance(target_name, str) or not target_name:
        raise TerminalError("invalid_target_name", "an item has no destination name")
    base = f"{normalize_root(destination_prefix)}{target_name}"
    if not is_folder:
        return base
    return f"{base}/{rel_key}" if rel_key else f"{base}/"


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

    **``kind`` is validated for the same reason, and it is the less obvious half.** The trailing
    slash is applied on ``kind == "folder"``, so anything else — an absent field, ``"Folder"``, a
    caller that spelled it ``type`` — silently produces the no-slash form, which is exactly the
    key that makes a move copy a folder onto itself and then delete it. Refusing an unrecognised
    kind is what stops a typo in a future verb from becoming data loss rather than an error.

    Args:
      destination_prefix: The authorized destination folder, with its trailing slash.
      item: The selected item, carrying ``kind``, ``key`` and optionally ``targetName``.

    Returns:
      The absolute key this item lands at, ending in a slash when the item is a folder.

    Raises:
      TerminalError: ``invalid_items`` when the item has no usable key or an unrecognised kind,
        ``invalid_target_name`` when a supplied name is unusable, or ``forbidden`` when the item's
        key has no final segment.
    """
    key = item.get("key")
    kind = item.get("kind")
    if not isinstance(key, str) or not key:
        raise TerminalError("invalid_items", "an item has no key")
    if kind not in _ITEM_KINDS:
        raise TerminalError("invalid_items", f"unknown item kind {kind!r}")

    requested = item.get("targetName")
    name = validate_target_name(requested) if requested is not None else item_name(key)
    return destination_key(destination_prefix, name, "", is_folder=kind == "folder")


def shorten_for_display(text: str) -> str:
    """Shortens one path or name FROM THE MIDDLE so the part that identifies it survives.

    The caps on this plane admit keys and names no message could render whole — 1,024 bytes of
    arbitrary UTF-8 — and a refusal that fills a notification with one path tells the user less
    than one that names three. The basename is the half that identifies a file, so the middle is
    what goes.

    Lives here rather than in the verb that first needed it because the destination guard's
    sample and the notification's item lines shorten the same values for the same reason; two
    implementations would be two answers to "what does the user read".

    Args:
      text: The path or name to render, already relative to whatever root the reader sees.

    Returns:
      The text, unchanged when it is short enough, else its head and tail joined by an ellipsis.

    Raises:
      None.
    """
    if len(text) <= FILE_OPS_SAMPLE_PATH_CHARS:
        return text
    keep = (FILE_OPS_SAMPLE_PATH_CHARS - 3) // 2
    return f"{text[:keep]}...{text[-keep:]}"
