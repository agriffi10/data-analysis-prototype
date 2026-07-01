"""check-table-absent — the table-builder Step Function's second task (SPEC-068).

Guard against clobbering an existing table (Glue has no versioning here): ask the
Glue Data Catalog whether ``tableName`` already exists in the target database. Not
found ⇒ pass the request through unchanged; found ⇒ terminal failure ``table_exists``.
Read-only (``GetTable`` only). Together with SPEC-070's ``CREATE … IF NOT EXISTS`` this
is the duplicate-name guard.

Transient Glue errors (throttling / 5xx) are RAISED — not converted to a terminal
reason — so the SFN ``Retry`` can retry them (lambdas.md §4). Only a genuinely
existing table is terminal.
"""

import logging

from tbcommon import clients
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

    # A GetTable that returns ⇒ the table already exists; any other error (throttling,
    # 5xx) propagates uncaught for the SFN Retry.
    raise TerminalError("table_exists", f"table {table!r} already exists in database {database!r}")
