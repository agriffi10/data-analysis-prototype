"""Best-effort outcome notifications for the table-builder pipeline.

The shared primitives live in ``cpcommon.notify``; this module keeps the table-builder
specifics — the actor is always the recipient with no fan-out, the FIFO dedup id is
``{requestId}:{step}``, and the wording comes from ``tbcommon.messages``.

Each verb emits one notification at its terminal branch: a failure message when it raises,
a success message when the table is created or refreshed. A missed notification must never
change or fail the pipeline outcome, so every emit goes through
``cpcommon.notify.emit_notification``, which catches, logs and never raises.
"""

import json
from urllib.parse import quote

from cpcommon import ddl, observability
from cpcommon.errors import TerminalError
from cpcommon.notify import dedup_id, emit_notification
from cpcommon.notify import notifies_on_failure as _notifies_on_failure

from .messages import (
    MAX_NAMED_COLUMNS,
    failure_message,
    removed_tokens,
    success_message,
)

__all__ = [
    "emit_created",
    "emit_failure",
    "emit_notification",
    "emit_refresh_outcome",
    "emit_unexpected",
    "notifies_on_failure",
    "removed_tokens",
]


def _columns_removed_link(database: str, table: str, tokens: dict) -> str | None:
    """Builds the in-app link that lets the refresh dialog name the removed columns.

    Built here rather than carried on the exception: ``emit_notification`` already takes a
    link, and the exception would have grown a transport field for exactly one caller.

    The column names are percent-encoded, and that is not belt-and-braces. The database and
    table are catalog-safe identifiers; the column names are not — they come verbatim from a
    file header or a Glue column and are never validated anywhere in this plane. A header of
    ``Order ID`` puts a raw space in the URL, one containing an ampersand invents a query
    parameter, and one containing a hash truncates the rest into a fragment. Encoding each
    name individually keeps the comma as the separator and the value as itself. The path is
    a safe in-app path by construction, decided by its literal prefix, so the assertion worth
    making is about the parameters.

    Args:
      database: The catalog-safe database name.
      table: The catalog-safe table name.
      tokens: The refusal's tokens, carrying ``removedNames`` as a JSON list.

    Returns:
      The in-app path, or None when there is no database, table or decodable name list.

    Raises:
      None.
    """
    if not database or not table:
        return None
    try:
        names = [str(n) for n in json.loads(tokens.get("removedNames") or "[]")]
    except ValueError:
        return None
    if not names:
        return None
    encoded = ",".join(quote(name, safe="") for name in names[:MAX_NAMED_COLUMNS])
    return f"/query?refreshTable={database}.{table}&removed={encoded}"


def emit_failure(event: dict, err: TerminalError, step: str) -> None:
    """Emits the actor-addressed failure notification for a verb's terminal error.

    The error's detail — raw Athena text — is deliberately not forwarded to the user message;
    it stays on the exception for logs and the SFN record. Its tokens are the opposite channel
    and are forwarded, because they exist to fill the markers in a body.

    Args:
      event: The validated task input, read for actor, table, database, request id and mode.
      err: The terminal error being reported.
      step: The verb name, used in the dedup id.

    Returns:
      None. An unauthorized failure raised before the actor is bound has no recipient, so the
      emit is a no-op rather than a lost message.

    Raises:
      None.
    """
    space = event.get("space") or {}
    database = space.get("database", "")
    table = event.get("tableName", "")
    link = (
        _columns_removed_link(database, table, err.tokens)
        if err.reason == "columns_removed"
        else None
    )
    emit_notification(
        event.get("actor", ""),
        failure_message(err.reason, table, database, event.get("mode", "create"), err.tokens),
        dedup_id=dedup_id(event.get("requestId"), step),
        link=link,
    )


def emit_unexpected(event, step: str) -> None:
    """Emits the actor-addressed failure notification for an unexpected verb exception.

    Uses the generic unexpected-error reason so no internals leak.

    Args:
      event: The running request. A non-dict event is tolerated — validate-authorize's raw
        SQS array fails before the actor is bound — and yields no recipient.
      step: The verb name, used in the dedup id.

    Returns:
      None.

    Raises:
      None.
    """
    data = event if isinstance(event, dict) else {}
    space = data.get("space") or {}
    emit_notification(
        data.get("actor", ""),
        failure_message(
            "unexpected_error",
            data.get("tableName", ""),
            space.get("database", ""),
            data.get("mode", "create"),
        ),
        dedup_id=dedup_id(data.get("requestId"), step),
    )


def notifies_on_failure(step: str, *, notify_terminal: bool = True):
    """Binds table-builder's emitters into the shared failure-notification skeleton.

    Args:
      step: The verb name carried into the notification.
      notify_terminal: Whether a terminal error also notifies at the decorator, so worker
        verbs need no ``try/except`` of their own. False for validate-authorize, which
        notifies inside its own actor-aware orchestration because the actor is not bound
        until the identity block is read.

    Returns:
      A decorator for the verb handler.

    Raises:
      None.
    """
    return _notifies_on_failure(step, emit_unexpected, emit_failure if notify_terminal else None)


def _renamed_columns(event: dict) -> list[tuple[str, str]]:
    """Recovers which columns a create declared under a new name, from the state it ran on.

    Derived from the same columns, partition keys and format the DDL was built from, through
    the same ``ddl.declare_columns``, rather than carried on the state beside the statement. It
    runs after the table exists, so a state it cannot read costs the sentence and never the
    notification: a create that succeeded must still say so.

    Args:
      event: The task input, read for columns, partition keys and format.

    Returns:
      ``(name in the files, name in the table)`` pairs, empty when nothing was renamed or the
      state does not carry what the derivation needs.

    Raises:
      None.
    """
    columns = event.get("columns")
    fmt = event.get("format")
    if not columns or not fmt:
        return []
    try:
        pairs = ddl.declare_columns(columns, event.get("partitionKeys") or [], fmt)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        observability.warning("renamed columns not derived", error=type(exc).__name__)
        return []
    return [
        (pair.source["name"], pair.declared["name"])
        for pair in pairs
        if pair.collides and pair.declared is not None
    ]


def emit_created(event: dict) -> None:
    """Emits the actor-addressed success notification for a newly created table.

    Args:
      event: The task input, read for actor, table, database and request id, and for the
        columns a CSV create renamed.

    Returns:
      None.

    Raises:
      None.
    """
    space = event.get("space") or {}
    emit_notification(
        event.get("actor", ""),
        success_message(
            event.get("tableName", ""),
            space.get("database", ""),
            renamed=_renamed_columns(event),
        ),
        dedup_id=dedup_id(event.get("requestId"), "created"),
    )


def emit_refresh_outcome(event: dict, status: str, diff: dict | None = None) -> None:
    """Emits the actor-addressed success notification for a refresh.

    One dedup token covers both outcomes, because the token is per outcome rather than per
    verb: a run produces either a refreshed or an unchanged result, never both, and the two
    are emitted by different verbs on different branches.

    Args:
      event: The task input, read for actor, table, database and request id.
      status: ``refreshed`` or ``unchanged``.
      diff: The classifier's result, read for the added, retyped and removed counts.

    Returns:
      None.

    Raises:
      None.
    """
    space = event.get("space") or {}
    counts = diff or {}
    emit_notification(
        event.get("actor", ""),
        success_message(
            event.get("tableName", ""),
            space.get("database", ""),
            status,
            added=len(counts.get("added") or []),
            retyped=len(counts.get("retyped") or []),
            removed=len(counts.get("removed") or []),
        ),
        dedup_id=dedup_id(event.get("requestId"), "refresh"),
    )
