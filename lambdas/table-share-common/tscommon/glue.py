"""Glue catalog reads for the table-share source (SPEC-090).

get_table fetches the source table; clone_definition validates it is a shareable
shape (base EXTERNAL_TABLE, flat or partition-projection) and captures its
definition verbatim — columns, partition keys, SerDe/formats, carried
TBLPROPERTIES — with LOCATION and catalog identity stripped (the recipient step
sets its own, docs/architecture.md Control Planes -> Table Share).

clone_definition MOVED to cpcommon.glue in SPEC-143 (the table-builder refresh path
asks the catalog the same shape question) and is re-exported here unchanged, so every
tscommon caller and test keeps working against ``glue_mod.clone_definition``. The two
verbs below stay: their reason codes (source_not_found / target_not_readable) are
table-share's own request vocabulary, not shape checks.
"""

from cpcommon import clients, errors
from cpcommon.errors import TerminalError, TransientError
from cpcommon.glue import clone_definition  # re-export, SPEC-143 FR-004

__all__ = ["clone_definition", "get_table", "table_exists"]


def get_table(database: str, table: str) -> dict:
    """Return the raw Glue Table for ``database.table``; terminal when unreadable."""
    client = clients.glue()
    try:
        return client.get_table(DatabaseName=database, Name=table)["Table"]
    except Exception as exc:  # mapped by error code below
        code = errors.error_code(exc)
        if code == "EntityNotFoundException":
            raise TerminalError("source_not_found", f"{database}.{table}") from exc
        if code == "AccessDeniedException":
            # LF gates the catalog; the execution role's LF-admin wiring is SPEC-092.
            raise TerminalError("source_not_readable", f"{database}.{table}: {exc}") from exc
        raise TransientError(f"GetTable failed for {database}.{table}: {exc}") from exc


def table_exists(database: str, table: str) -> bool:
    """True iff ``database.table`` exists — the recipient conflict check (SPEC-091).

    A denied read is terminal (the recipient DB should be readable once the role is
    an LF admin, SPEC-092); anything else transient so the SFN retries rather than
    mis-reporting a throttle as a conflict verdict.
    """
    client = clients.glue()
    try:
        client.get_table(DatabaseName=database, Name=table)
        return True
    except Exception as exc:  # mapped by error code below
        code = errors.error_code(exc)
        if code == "EntityNotFoundException":
            return False
        if code == "AccessDeniedException":
            raise TerminalError("target_not_readable", f"{database}.{table}: {exc}") from exc
        raise TransientError(f"GetTable failed for {database}.{table}: {exc}") from exc
