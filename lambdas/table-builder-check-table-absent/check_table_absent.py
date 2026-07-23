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

from cpcommon import clients, errors, events, observability
from tbcommon import notify
from cpcommon.errors import TerminalError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one table-build is five invocations, and
# they are only one queryable set if they share a service name (SPEC-127 FR-003). The per-verb
# identity rides as the `verb` field.
observability.init(service="table-builder")


# @traced is OUTERMOST, above @notifies_on_failure: the latter catches on its way out,
# so if it were outermost the span would close status="ok" on an invocation that
# actually failed and notified.
@observability.traced("check-table-absent")
@notify.notifies_on_failure("check")
def handler(event: dict, context) -> dict:
    """SFN entry point: verify the target table doesn't already exist.

    Delegates to ``_check_table_absent`` and notifies the actor on a terminal failure
    (best-effort) before the SFN ``Catch`` records it. A transient Glue throttle maps to
    ``TransientError`` and passes through un-notified for the SFN ``Retry``;
    ``@notifies_on_failure`` surfaces genuinely unexpected errors.
    """
    return _check_table_absent(event)


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
        # THE VERDICT AS AN EXPLICIT BOOLEAN, with the database and table it checked. The
        # pre-condition and the post-condition of a table build are the SAME check, so having
        # this in the record is what makes "the DDL claimed success and the table is not there"
        # a statable sentence rather than a suspicion (SPEC-135 FR-003 — the plane's defining
        # incident, where LF admin status silently did not grant CREATE_TABLE).
        observability.info(
            "target table absent", database=database, table=table, exists=False
        )
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
