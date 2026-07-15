"""Task-input shape validation for control-plane verb handlers (SPEC-107).

Moved from tbcommon (it was already generic and exists only there). The Step Function
hands each verb a JSON task input; a malformed or replayed input (a missing/renamed/
wrong-typed key) would otherwise raise a bare ``KeyError``/``TypeError`` that the SFN
Catch records as an opaque failure with NO actor notification. ``require`` turns that
into a typed ``TerminalError`` with a specific reason, so the failure is recorded
meaningfully AND surfaced to the actor via the handler's ``emit_failure`` path
(SPEC-083 FR-002).

Table-share verbs do NOT adopt this in SPEC-107 (they validate inline today; switching
them would be a behaviour change) — it is available for the data-quality / file-converter
arcs.
"""

from typing import Any

from .errors import TerminalError

# Stable reason code for a bad task input (a cpcommon.messages base code).
MALFORMED = "malformed_event"


def require(event: Any, *path: str, reason: str = MALFORMED) -> Any:
    """Return ``event[path...]`` or raise ``TerminalError(reason)``.

    Every segment must be a present key on a dict; the resolved value must be non-empty
    when it's a string (buckets/prefixes/names/formats are all non-empty strings). The
    dotted path is included in the detail for the log/SFN record.

    ``reason`` lets a domain surface its OWN terminal code for a bad task input while
    still using this one shape-check (the data-quality arc raises ``invalid_request``,
    SPEC-109 FR-001/FR-004). It defaults to the shared ``malformed_event`` base code, so
    every existing caller is unaffected. Whatever is passed must be a registered reason —
    ``TerminalError`` validates it at the raise site (SPEC-107 FR-005).
    """
    node = event
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise TerminalError(reason, f"missing required field {'.'.join(path)!r}")
        node = node[key]
    if node is None or (isinstance(node, str) and not node.strip()):
        raise TerminalError(reason, f"empty required field {'.'.join(path)!r}")
    return node
