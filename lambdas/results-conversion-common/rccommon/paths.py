"""Where a converted file may be written: the name, the folder, the key and the refusals.

The destination key is ``{space root}{prefix}{filename}``, with the prefix relative to the space
root. Containment is proved by ``cpcommon.paths.assert_inside_root``, which refuses a dot
segment and a key escaping the root; its ``forbidden`` is translated to ``invalid_request``
here because a malformed destination is a statement about the request, not about the space.

**The protected-folder rule is any-depth in BOTH buckets, and that is stricter than the
browser's picker in a personal space on purpose.** The execution role's Deny on these folders is
written with an IAM wildcard where the space name goes, and a wildcard matches ``/`` — so IAM
refuses the folder at any depth in either bucket, and a validator that accepted a deeper one
would turn a named refusal into an ``AccessDenied`` at the write. The validator mirrors the
Deny, not the picker.

Attributes:
  _CONTROL: The code points a file name may not carry — the C0 controls and DEL.
"""

from cpcommon.app_managed import app_managed_prefix
from cpcommon.errors import TerminalError
from cpcommon.paths import assert_inside_root, normalize_root

from . import reasons
from .config import MAX_FILENAME_BYTES, MAX_PREFIX_BYTES, PROTECTED_DESTINATIONS

__all__ = ["check_filename", "check_prefix", "destination_key", "protected_refusal"]

_CONTROL = frozenset(range(32)) | {127}


def check_prefix(prefix: object) -> str:
    """Confirms the destination folder is empty or slash-terminated, and not too long.

    Args:
      prefix: The request's destination folder, relative to the space root.

    Returns:
      The prefix, unchanged.

    Control characters are refused here for the same reason ``check_filename`` refuses them, and
    the two used to disagree: a newline in a folder name reaches an operator's plain-text log
    through the key it becomes, where it forges a second line.

    Args-note: the two checks are deliberately the same shape rather than shared, because a
    file name additionally refuses a slash and the dot segments, which a prefix is made of.

    Raises:
      TerminalError: ``invalid_request`` when it is not a string, is non-empty without a
        trailing slash, exceeds ``MAX_PREFIX_BYTES`` in UTF-8, or carries a control character.
    """
    if not isinstance(prefix, str):
        raise TerminalError(reasons.INVALID_REQUEST, "destination prefix is not a string")
    if prefix and not prefix.endswith("/"):
        raise TerminalError(reasons.INVALID_REQUEST, "destination prefix does not end in a slash")
    if len(prefix.encode("utf-8")) > MAX_PREFIX_BYTES:
        raise TerminalError(
            reasons.INVALID_REQUEST, f"destination prefix is over {MAX_PREFIX_BYTES} bytes"
        )
    if any(ord(ch) in _CONTROL for ch in prefix):
        raise TerminalError(reasons.INVALID_REQUEST, "destination prefix has a control character")
    return prefix


def check_filename(filename: object) -> str:
    """Confirms the file name is one S3 and a file browser can both hold.

    Args:
      filename: The request's file name.

    Returns:
      The file name, unchanged.

    Raises:
      TerminalError: ``invalid_request`` when it is not a string, is empty or over
        ``MAX_FILENAME_BYTES`` in UTF-8, contains a slash or a control character, or is ``.`` or
        ``..``.
    """
    if not isinstance(filename, str):
        raise TerminalError(reasons.INVALID_REQUEST, "file name is not a string")
    size = len(filename.encode("utf-8"))
    if size < 1 or size > MAX_FILENAME_BYTES:
        raise TerminalError(
            reasons.INVALID_REQUEST, f"file name must be 1 to {MAX_FILENAME_BYTES} bytes"
        )
    if "/" in filename:
        raise TerminalError(reasons.INVALID_REQUEST, "file name contains a slash")
    if any(ord(ch) in _CONTROL for ch in filename):
        raise TerminalError(reasons.INVALID_REQUEST, "file name contains a control character")
    if filename in (".", ".."):
        raise TerminalError(reasons.INVALID_REQUEST, "file name is a dot segment")
    return filename


def destination_key(root: str, prefix: str, filename: str) -> str:
    """Builds the destination key and proves it sits inside the space root.

    Args:
      root: The authorized space root.
      prefix: The checked destination folder, relative to the root.
      filename: The checked file name.

    Returns:
      The absolute key.

    Raises:
      TerminalError: ``invalid_request`` when the key carries a dot segment or escapes the root.
    """
    key = f"{normalize_root(root)}{prefix}{filename}"
    try:
        assert_inside_root(root, key)
    except TerminalError as err:
        raise TerminalError(reasons.INVALID_REQUEST, err.detail) from err
    return key


def protected_refusal(root: str, key: str) -> str | None:
    """Names the app-managed folder a destination key sits in, or None when it sits in none.

    Compared on the key's FOLDER segments only: a file merely named like a protected folder is
    a file, matched by no Deny.

    Args:
      root: The authorized space root.
      key: The contained destination key.

    Returns:
      The folder's name, or None.

    Raises:
      None.
    """
    normalized = normalize_root(root)
    folders = key[len(normalized) :].split("/")[:-1]
    for name in PROTECTED_DESTINATIONS:
        if key.startswith(app_managed_prefix(normalized, name)) or name in folders:
            return name
    return None
