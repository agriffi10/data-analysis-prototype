"""The in-app path a conversion's notification deep-links to: the folder the file landed in.

Two rules, each learned somewhere else and each with a failure that is silent, and one convention:

**The prefix is the FULL key, including the space root.** The file browser keeps a ``?prefix=``
only when it starts with the resolved space's root prefix, so a root-relative one is discarded
and the user lands at their space root with no idea why.

**``space`` comes first in the query string**, as every plane's link puts it. It is a convention
rather than a guard: the notification row's feature gate parses the link, so the order does not
decide whether a shared-space link is gated.

**Every component is percent-encoded.** The prefix is arbitrary user-controlled text, and an
unencoded ``?``, ``#`` or ``&`` truncates the link into one that resolves somewhere else. The
space NAME is encoded here too, which is a deliberate divergence from file-ops' notifier — that
one interpolates the name raw and shape-checks it instead. The shape check is kept as well,
because a name that is not one the browser could resolve should produce no link rather than a
broken one, and encoding alone would happily encode nonsense.

The link is a PATH and never a URL: ``isSafeInAppPath`` in the browser rejects anything that
could resolve off this origin, and this producer is the first of those two gates.

Attributes:
  _FILES_ROUTE: The file browser's route.
  _SEGMENT: What a space name may contain to be interpolated at all. Usernames and space names
    are already constrained to this by the catalog rule, so it refuses nothing this pipeline
    legitimately produces.
"""

import logging
import re
from urllib.parse import quote

logger = logging.getLogger()

__all__ = ["destination_link"]

_FILES_ROUTE = "/files"

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def destination_link(space_kind: str, space_name: str, key: str) -> str | None:
    """Builds the in-app path that lands the actor in the folder their file was written to.

    Args:
      space_kind: ``personal`` or ``shared``.
      space_name: The space's name, which is also its root segment.
      key: The destination key the file was written to, absolute within its bucket.

    Returns:
      The in-app path, or None when no working link can be minted — which is the honest answer:
      the notification still says what happened, it just carries no link.

    Raises:
      None.
    """
    if not isinstance(space_name, str) or not _SEGMENT.fullmatch(space_name):
        logger.warning("refusing to build a link from an unexpected space name")
        return None
    root = f"{space_name}/"
    folder = key[: key.rfind("/") + 1] if "/" in key else ""
    if not folder.startswith(root):
        folder = root
    encoded = quote(folder, safe="/")
    if space_kind == "shared":
        return f"{_FILES_ROUTE}?space={quote(space_name, safe='')}&prefix={encoded}"
    return f"{_FILES_ROUTE}?prefix={encoded}"
