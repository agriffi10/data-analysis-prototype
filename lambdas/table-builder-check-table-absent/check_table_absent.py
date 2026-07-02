"""check-table-absent — the table-builder Step Function's second task.

Guards against clobbering an existing table: asks the Glue Data Catalog whether
tableName already exists in the target database. Not found ⇒ pass the request
through unchanged; found ⇒ terminal failure table_exists. Read-only (GetTable only);
together with execute-ddl's CREATE ... IF NOT EXISTS this is the duplicate-name
guard. Transient Glue errors (throttling / 5xx) are raised — not terminal — so the
SFN Retry can retry them.
"""

import logging

from tbcommon import clients, notify
from tbcommon.errors import TerminalError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


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

    # A GetTable that returns ⇒ the table already exists; any other error propagates
    # uncaught for the SFN Retry. Notify the actor (best-effort) before raising.
    err = TerminalError("table_exists", f"table {table!r} already exists in database {database!r}")
    notify.emit_failure(event, err, "check")
    raise err
