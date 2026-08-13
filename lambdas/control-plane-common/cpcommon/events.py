"""Task-input shape validation for control-plane verb handlers.

The Step Function hands each verb a JSON task input. A malformed or replayed input would
otherwise raise a bare ``KeyError``/``TypeError`` that the SFN ``Catch`` records as an
opaque failure with no actor notification. These helpers turn that into a typed
``TerminalError`` with a specific reason, so the failure is both recorded meaningfully and
surfaced to the actor.

``timed_out_execution_input`` reads the other event shape a plane can receive: the EventBridge
status-change event that reaches a notify-failure verb through its second door.

Attributes:
  MALFORMED: Stable reason code for a bad task input, registered in ``cpcommon.messages``.
"""

import json
import logging
from typing import Any

from . import clients
from .errors import TerminalError

logger = logging.getLogger()

MALFORMED = "malformed_event"


def parse_sqs_request(event: Any, *, reason: str, exc: Any = None) -> Any:
    """Extracts and JSON-parses the single SQS record body an EventBridge Pipe forwards.

    The Pipe forwards the raw SQS batch as a JSON array; this takes the single record and
    returns its parsed body. A malformed or replayed queue message is a deterministic
    failure the SFN ``Catch`` records and never retries. The caller supplies its own
    registered reason so each domain keeps its wording while sharing the shape check.

    Args:
      event: The Pipe payload — a single-element list of SQS records, or one record dict.
      reason: The caller's registered terminal reason code to raise under. Unused when ``exc``
        is supplied.
      exc: A one-argument exception factory called with the detail string, for a plane whose
        Catch behaviour is expressed in its own exception type rather than ``TerminalError``.
        Defaults to ``TerminalError`` bound to ``reason``. shared-space passes its
        ``AuthorizationError``, which is what its own copy of this function existed for.

    Returns:
      The parsed request body — a dict from every producer, but declared ``Any`` because the
      parse is unguarded: a body that is valid JSON of another type — a list, a number — is
      returned as-is and the caller's first field read raises. Every caller either reads
      through ``require``, which type-checks, or guards the shape itself. Declaring ``dict``
      would state to a type checker exactly the thing this paragraph says is not true.

    Raises:
      TerminalError: On an empty batch, an unrecognised event shape, a missing body, or a
        body that is not valid JSON — or whatever ``exc`` builds, in the same four cases with
        the same four detail strings.
    """
    fail = exc if exc is not None else (lambda detail: TerminalError(reason, detail))
    if isinstance(event, list):
        if not event:
            raise fail("empty event")
        record = event[0]
    elif isinstance(event, dict):
        record = event
    else:
        raise fail("unrecognised event shape")
    body = record.get("body") if isinstance(record, dict) else None
    if not body:
        raise fail("missing message body")
    try:
        return json.loads(body)
    except (TypeError, ValueError) as err:
        raise fail(f"body is not valid JSON: {err}") from err


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


def timed_out_execution_input(detail: Any) -> str:
    """Returns a timed-out execution's input, fetching it back when the event omitted it.

    **The fallback is the ordinary case on any plane whose item cap approaches 200 KB**, not belt
    and braces. EventBridge caps an event at 256 KB, and Step Functions drops the input and sets
    ``inputDetails.included: false`` rather than exceed it. Where a plane's execution input is the
    Pipe's record — file-send and archive both allow one to approach 200 KB — the biggest requests
    are the ones that run long enough to time out, so they are exactly the ones the event alone
    cannot attribute. ``DescribeExecution`` returns the input whole, and is the one extra grant
    such a door needs. A plane whose inputs are small (table-share's are a table name and a
    recipient list) needs no fallback, which is why this is a shared helper rather than a shared
    assumption.

    Args:
      detail: The EventBridge event's ``detail`` block.

    Returns:
      The execution input as a JSON string, or an empty string when it cannot be obtained.

    Raises:
      None. A failed lookup degrades to no input, which the caller turns into no addressee and
      logs as a no-op — a raise would be an async Lambda failure, and EventBridge retries those,
      turning one unattributable event into three.
    """
    if not isinstance(detail, dict):
        return ""
    raw = detail.get("input")
    if (detail.get("inputDetails") or {}).get("included") is not False and isinstance(raw, str) and raw:
        return raw

    arn = detail.get("executionArn")
    if not isinstance(arn, str) or not arn:
        return ""
    try:
        described = clients.sfn().describe_execution(executionArn=arn)
    except Exception as exc:  # noqa: BLE001
        logger.info("could not read the timed-out execution's input back: %s", exc)
        return ""
    fetched = described.get("input")
    return fetched if isinstance(fetched, str) else ""
