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

from tbcommon import clients, notify
from tbcommon.errors import TerminalError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


@notify.notifies_on_failure("check")
def handler(event, context):
    database = event["space"]["database"]
    table = event["tableName"]

    glue = clients.glue()
    try:
        glue.get_table(DatabaseName=database, Name=table)
    except glue.exceptions.EntityNotFoundException:
        # The table (or its database) doesn't exist yet — the create can proceed.
        logger.info("table %s absent in %s — proceeding", table, database)
        return event

    # A GetTable that returns ⇒ the table already exists. Notify the actor (best-effort)
    # before raising the terminal failure; any other error escapes to the wrapper.
    err = TerminalError("table_exists", f"table {table!r} already exists in database {database!r}")
    notify.emit_failure(event, err, "check")
    raise err
