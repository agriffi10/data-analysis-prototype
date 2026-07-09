"""User-facing notification text for table-builder outcomes.

One place maps each stable terminal reason code to friendly text addressed to the
actor, so every verb + its tests agree on the wording. Kept ASCII (no smart quotes).
"""

# Reasons that mean "not allowed" — no table name is surfaced (the request may not
# even have got far enough to trust one).
_ACCESS_DENIED = frozenset({"unauthorized", "forbidden"})

# reason -> the clause after 'Couldn't create table "{name}": '. {database} is
# filled per-call where relevant. The DDL-failure reasons carry NO raw Athena
# StateChangeReason (SPEC-106 FR-008) — that detail stays in logs + the SFN
# terminal record for operators, never in the actor's notification.
_BODIES = {
    "invalid_table_name": "the name isn't a valid table name.",
    "invalid_partition_keys": "the partition keys aren't valid (check names, types, and ranges).",
    "table_exists": 'a table with that name already exists in "{database}".',
    "no_data_files": "no supported data files were found in that folder.",
    "mixed_formats": "the folder mixes file formats - use a single format.",
    "unsupported_format": "that file format isn't supported (use Parquet, CSV, or JSON).",
    "unexpected_partitioning": "the folder is partitioned but no partition keys were provided.",
    "partition_layout_mismatch": "the partition keys don't match the folder layout (check names and order).",
    "schema_inference_failed": "the data schema couldn't be read.",
    "unmappable_type": "the data schema couldn't be read.",
    "ddl_execution_failed": "creating the table failed. Please try again or contact the Administrator.",
    "ddl_timeout": "creating the table failed. Please try again or contact the Administrator.",
    "malformed_event": "the request was malformed. Please try again.",
    # Generic catch-all for an unexpected (non-terminal) verb exception — emitted by
    # notify.notifies_on_failure so an unexpected failure still reaches the actor.
    "unexpected_error": "something went wrong. Please try again.",
}


def failure_message(reason: str, table_name: str = "", database: str = "") -> str:
    """Map a terminal reason (+ context) to the message the actor sees.

    An unknown reason falls back to a generic couldn't-create line rather than
    leaking the code. No raw AWS/Athena text is ever interpolated (SPEC-106 FR-008).
    """
    if reason in _ACCESS_DENIED:
        return "You don't have access to create a table here."
    name = table_name or "your table"
    body = _BODIES.get(reason, "something went wrong.")
    # Substitute the one known placeholder directly (never str.format) so a body that
    # ever contains a literal brace can't raise KeyError/ValueError (SPEC-083 FR-005).
    body = body.replace("{database}", database)
    return f'Couldn\'t create table "{name}": {body}'


def success_message(table_name: str, database: str) -> str:
    """Return the ready-to-query message emitted on execute-ddl success."""
    return f'Table "{table_name}" is ready to query in "{database}".'
