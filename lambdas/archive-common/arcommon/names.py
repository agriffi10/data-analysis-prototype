"""The archive name: what a user may call an archive, stated once for the plane.

A name is optional and purely a label. Nothing builds a key from it, nothing authorizes by it, and
a restore never reads it — the archive's identity is still its id. What it reaches is the receipt,
the per-space index and, in a shared space, the restore list every member sees, which is why the
rule refuses the characters that would break the first or mislead in the last.

**The browser states the same rule in ``archiveName.ts``, and the two are held together by one
corpus of raw inputs and their outcomes** (``archive_name_corpus.json`` beside this package),
which both test suites run. The constants alone cannot keep two implementations of a
normalisation in step — a ``.trim()`` that also strips U+00A0 agrees with every constant and
disagrees with this module.

**Only U+0020 counts as a space.** Python's ``str.split()`` and JavaScript's ``\\s`` disagree about
what whitespace is, so normalising "whitespace" would be two rules wearing one name. Tabs and line
breaks never reach normalisation: they are refused on the raw value first.

Attributes:
  None.
"""

from cpcommon.errors import TerminalError

from . import messages  # noqa: F401
from .config import ARCHIVE_NAME_MAX_CHARS, ARCHIVE_NAME_REFUSED_RANGES


def refused_character(raw: str) -> str | None:
    """Finds the first character a name may not contain.

    Args:
      raw: The name exactly as the user typed or pasted it.

    Returns:
      The first refused character, or None when there is none.

    Raises:
      None.
    """
    for character in raw:
        point = ord(character)
        if any(low <= point <= high for low, high in ARCHIVE_NAME_REFUSED_RANGES):
            return character
    return None


def normalize(raw: str) -> str:
    """Collapses every run of spaces to one and trims spaces from both ends.

    Args:
      raw: The name, already known to hold no refused character.

    Returns:
      The normalised name; an empty string means the user gave no name.

    Raises:
      None.
    """
    return " ".join(part for part in raw.split(" ") if part)


def refusal(raw: str) -> str | None:
    """Says why a raw name cannot be used, in the order the browser checks it.

    Args:
      raw: The name exactly as the user typed or pasted it.

    Returns:
      ``"character"`` when it holds a refused character, ``"length"`` when its normalised form
      is longer than the cap, or None when it can be used.

    Raises:
      None.
    """
    if refused_character(raw) is not None:
        return "character"
    if len(normalize(raw)) > ARCHIVE_NAME_MAX_CHARS:
        return "length"
    return None


def validated_name(value) -> str:
    """Returns a request's archive name, or fails the whole request when it is not one.

    The browser normalises before it sends, so this does not normalise: a name that arrives
    un-normalised was not sent by the browser's rule, and is refused rather than quietly changed
    into a label the user never saw.

    Args:
      value: The request's ``archiveName`` field, present on the request. An absent field never
        reaches this function — the caller records no name instead.

    Returns:
      The name, unchanged.

    Raises:
      TerminalError: ``invalid_name`` when the value is not a string, is empty, is not in its
        normalised form, holds a refused character or is longer than the cap.
    """
    if not isinstance(value, str):
        raise TerminalError("invalid_name", "the archive name is not a string")
    reason = refusal(value)
    if reason is not None:
        raise TerminalError("invalid_name", f"the archive name was refused ({reason})")
    if not value or normalize(value) != value:
        raise TerminalError("invalid_name", "the archive name is empty or not normalised")
    return value
