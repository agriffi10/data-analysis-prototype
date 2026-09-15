"""check-table-absent — the table-builder Step Function's second task.

Guards against clobbering an existing table by asking the Glue Data Catalog whether the
target name is already taken. Read-only; together with execute-ddl's
``CREATE … IF NOT EXISTS`` this is the duplicate-name guard, and it narrows the race rather than
closing it. The Pipe starts runs fire-and-forget and a create takes no lock, so two creates of one
name can both pass here, and the second's no-op DDL is still reported as a created table.

GetTable resolves under Lake Formation, and the target databases are LF-gated, so the shared
execution role is an LF admin — without it, GetTable on a real user's database returns
AccessDenied rather than EntityNotFound and the guard cannot tell absent from denied.

The service name is the control plane, not the function: one table-build is five invocations,
and they are only one queryable set if they share it. The per-verb identity rides as the
``verb`` field.
"""

import logging

from cpcommon import clients, errors, events, observability
from cpcommon.errors import TerminalError
from tbcommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")


@observability.traced("check-table-absent")
@notify.notifies_on_failure("check")
def handler(event: dict, context) -> dict:
    """Step Functions entry point: verifies the target table does not already exist.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    Args:
      event: The task input, carrying the space and table name.
      context: The Lambda context, unused.

    Returns:
      The event unchanged when the table is absent.

    Raises:
      TerminalError: ``table_exists`` when the name is taken; notified to the actor before
        the SFN Catch records it.
      TransientError: On a Glue throttle, passed through un-notified for the SFN Retry.
    """
    return _check_table_absent(event)


def _check_table_absent(event: dict) -> dict:
    """Reads the target table from Glue and passes the event through if it is absent.

    The verdict is recorded as an explicit boolean alongside the database and table checked.
    The pre-condition and the post-condition of a table build are the same check, so having
    it in the record is what makes "the DDL claimed success and the table is not there" a
    statable sentence rather than a suspicion — this plane's defining incident, where LF admin
    status silently did not grant CREATE_TABLE.

    A Glue throttle is not an EntityNotFoundException, so it would otherwise propagate as a
    bare ClientError this verb's Retry list does not name, permanently failing the build.

    Args:
      event: The task input, carrying the space and table name.

    Returns:
      The event unchanged.

    Raises:
      TerminalError: ``table_exists`` when GetTable returns, or ``malformed_event`` when a
        required field is missing.
      TransientError: On a retryable Glue fault.
      ClientError: Any deterministic Glue fault propagates unchanged.
    """
    database = events.require(event, "space", "database")
    table = events.require(event, "tableName")

    glue = clients.glue()
    try:
        glue.get_table(DatabaseName=database, Name=table)
    except glue.exceptions.EntityNotFoundException:
        logger.info("table %s absent in %s — proceeding", table, database)
        observability.info(
            "target table absent", database=database, table=table, exists=False
        )
        return event
    except Exception as err:
        errors.raise_if_transient(err, f"glue get_table {database}.{table}")
        raise

    raise TerminalError("table_exists", f"table {table!r} already exists in database {database!r}")
