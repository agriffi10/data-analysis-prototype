"""check-table-absent — the table-builder Step Function's second task.

Guards against clobbering an existing table: asks the Glue Data Catalog whether
tableName already exists in the target database. Not found ⇒ pass the request
through unchanged; found ⇒ terminal failure table_exists. Read-only (GetTable only);
together with execute-ddl's CREATE ... IF NOT EXISTS this is the duplicate-name
guard.

GetTable resolves under Lake Formation (target DBs are LF-gated), so the shared
execution role is an LF admin (SPEC-070) — without it, GetTable on a real user's DB
returns AccessDenied, not EntityNotFound, and the guard can't tell absent from
denied. Any error that still escapes (a bug, an AccessDenied, a throttle boto's own
retries couldn't clear) is notified to the actor by @notifies_on_failure rather than
failing silently, and re-raised for the SFN Catch.
"""

import logging

from cpcommon import clients, errors, events
from tbcommon import notify
from cpcommon.errors import TerminalError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


@notify.notifies_on_failure("check")
def handler(event: dict, context) -> dict:
    """SFN entry point: verify the target table doesn't already exist.

    Delegates to ``_check_table_absent`` and notifies the actor on a terminal failure
    (best-effort) before the SFN ``Catch`` records it. A transient Glue throttle maps to
    ``TransientError`` and passes through un-notified for the SFN ``Retry``;
    ``@notifies_on_failure`` surfaces genuinely unexpected errors.
    """
    try:
        return _check_table_absent(event)
    except TerminalError as err:
        notify.emit_failure(event, err, "check")
        raise


def _check_table_absent(event: dict) -> dict:
    """GetTable the target; pass the event through if absent, else terminal table_exists."""
    database = events.require(event, "space", "database")
    table = events.require(event, "tableName")

    glue = clients.glue()
    try:
        glue.get_table(DatabaseName=database, Name=table)
    except glue.exceptions.EntityNotFoundException:
        # The table (or its database) doesn't exist yet — the create can proceed.
        logger.info("table %s absent in %s — proceeding", table, database)
        return event
    except Exception as err:  # noqa: BLE001 - a throttle is retryable; the rest propagate
        # A Glue ThrottlingException is NOT EntityNotFoundException, so it would otherwise
        # propagate as a bare ClientError the CheckTableAbsent Retry list does not name —
        # permanently failing the build. Map it to TransientError (paired with adding it
        # to that Retry list) so the SFN retries; a deterministic fault re-raises unchanged.
        errors.raise_if_transient(err, f"glue get_table {database}.{table}")
        raise

    # A GetTable that returns ⇒ the table already exists.
    raise TerminalError("table_exists", f"table {table!r} already exists in database {database!r}")
