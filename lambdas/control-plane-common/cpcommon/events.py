"""Task-input shape validation for control-plane verb handlers.

The Step Function hands each verb a JSON task input. A malformed or replayed input would
otherwise raise a bare ``KeyError``/``TypeError`` that the SFN ``Catch`` records as an
opaque failure with no actor notification. These helpers turn that into a typed
``TerminalError`` with a specific reason, so the failure is both recorded meaningfully and
surfaced to the actor.

Attributes:
  MALFORMED: Stable reason code for a bad task input, registered in ``cpcommon.messages``.
"""

import json
from typing import Any

from .errors import TerminalError

MALFORMED = "malformed_event"


def parse_sqs_request(event: Any, *, reason: str) -> dict:
    """Extracts and JSON-parses the single SQS record body an EventBridge Pipe forwards.

    The Pipe forwards the raw SQS batch as a JSON array; this takes the single record and
    returns its parsed body. A malformed or replayed queue message is a deterministic
    failure the SFN ``Catch`` records and never retries. The caller supplies its own
    registered reason so each domain keeps its wording while sharing the shape check.

    Args:
      event: The Pipe payload — a single-element list of SQS records, or one record dict.
      reason: The caller's registered terminal reason code to raise under.

    Returns:
      The parsed request body as a dict.

    Raises:
      TerminalError: On an empty batch, an unrecognised event shape, a missing body, or a
        body that is not valid JSON.
    """
    if isinstance(event, list):
        if not event:
            raise TerminalError(reason, "empty event")
        record = event[0]
    elif isinstance(event, dict):
        record = event
    else:
        raise TerminalError(reason, "unrecognised event shape")
    body = record.get("body") if isinstance(record, dict) else None
    if not body:
        raise TerminalError(reason, "missing message body")
    try:
        return json.loads(body)
    except (TypeError, ValueError) as exc:
        raise TerminalError(reason, f"body is not valid JSON: {exc}") from exc


def require(event: Any, *path: str, reason: str = MALFORMED) -> Any:
    """Reads a required value out of a task input by dotted path, or fails terminally.

    Every segment must be a present key on a dict, and the resolved value must be non-empty
    when it is a string — buckets, prefixes, names and formats are all non-empty strings.
    The dotted path is included in the detail for the log and the SFN record. A domain may
    pass its own terminal code; whatever is passed must be a registered reason, which
    ``TerminalError`` validates at the raise site.

    Args:
      event: The task input to read from.
      *path: Successive dict keys to descend, e.g. ``require(event, "space", "database")``.
      reason: Registered terminal reason code to raise under. Defaults to ``MALFORMED``.

    Returns:
      The value at that path.

    Raises:
      TerminalError: If any segment is missing, or the resolved value is None or a
        blank string.
    """
    node = event
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise TerminalError(reason, f"missing required field {'.'.join(path)!r}")
        node = node[key]
    if node is None or (isinstance(node, str) and not node.strip()):
        raise TerminalError(reason, f"empty required field {'.'.join(path)!r}")
    return node
