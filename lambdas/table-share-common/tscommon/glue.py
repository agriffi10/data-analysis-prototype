"""Glue catalog reads for the table-share source.

The shape validation and definition capture live in ``cpcommon.glue`` — the table-builder
refresh path asks the catalog the same question — and are re-exported here unchanged so every
caller and test keeps working against this module. The two verbs below stay, because their
reason codes are table-share's own request vocabulary rather than shape checks.
"""

from typing import cast

from cpcommon import clients, errors
from cpcommon.errors import TerminalError
from cpcommon.glue import clone_definition

__all__ = ["clone_definition", "get_table", "table_exists"]


def get_table(database: str, table: str) -> dict:
    """Reads the share source from the Glue catalog.

    Every remaining fault is classified rather than assumed transient. An earlier version made
    them all transient — the opposite bias to the rest of the fleet — so a deterministic error
    burned the whole Retry budget before failing, turning an instant refusal into a slow one
    and telling the user nothing sooner.

    Args:
      database: The source database.
      table: The source table name.

    Returns:
      The raw Glue table dict.

    Raises:
      TerminalError: ``source_not_found`` when it does not exist, or ``source_not_readable``
        when Lake Formation denies the read or the fault is deterministic.
      TransientError: On a retryable Glue fault.
    """
    client = clients.glue()
    try:
        return cast("dict", client.get_table(DatabaseName=database, Name=table)["Table"])
    except Exception as exc:
        code = errors.error_code(exc)
        if code == "EntityNotFoundException":
            raise TerminalError("source_not_found", f"{database}.{table}") from exc
        if code == "AccessDeniedException":
            raise TerminalError("source_not_readable", f"{database}.{table}: {exc}") from exc
        errors.raise_if_transient(exc, f"GetTable {database}.{table}")
        raise TerminalError("source_not_readable", f"{database}.{table}: {exc}") from exc


def table_exists(database: str, table: str) -> bool:
    """Reports whether a recipient's target table name is already taken.

    A denied read is terminal — the recipient database should be readable once the role is a
    Lake Formation admin — and anything else is transient so the Step Function retries rather
    than mis-reporting a throttle as a conflict verdict.

    Args:
      database: The recipient's database.
      table: The target table name.

    Returns:
      True when the table already exists.

    Raises:
      TerminalError: ``target_not_readable`` on a denied read or a deterministic fault.
      TransientError: On a retryable Glue fault.
    """
    client = clients.glue()
    try:
        client.get_table(DatabaseName=database, Name=table)
        return True
    except Exception as exc:
        code = errors.error_code(exc)
        if code == "EntityNotFoundException":
            return False
        if code == "AccessDeniedException":
            raise TerminalError("target_not_readable", f"{database}.{table}: {exc}") from exc
        errors.raise_if_transient(exc, f"GetTable {database}.{table}")
        raise TerminalError("target_not_readable", f"{database}.{table}: {exc}") from exc
