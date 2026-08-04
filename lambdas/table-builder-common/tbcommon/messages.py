"""User-facing notification text for table-builder outcomes.

One place maps each stable terminal reason code to friendly text addressed to the
actor, so every verb + its tests agree on the wording. Kept ASCII (no smart quotes).

This module keeps its own bespoke ``failure_message`` wording (SPEC-107 FR-002 —
unchanged); it registers the table-builder domain reason codes with cpcommon at import
so they pass ``TerminalError``'s raise-time validation (SPEC-107 FR-005).
"""

from cpcommon import messages as _cpmessages

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
    # Refresh-path reasons (SPEC-143). Deliberately create-shaped wording: failure_message()
    # below still frames every outcome as a create, and SPEC-144 FR-009 owns teaching this
    # layer to talk about refreshes. `not_implemented` gets no body — the SPEC-143 stub is
    # an ASL Pass state, so nothing raises it in Python and nothing renders it.
    "invalid_mode": "the request was malformed. Please try again.",
    "partition_keys_not_refreshable": (
        "a refresh keeps the table's existing partition keys - to change them, drop the "
        "table and build it again."
    ),
    "table_not_found": 'no table named that exists in "{database}".',
    "cannot_refresh_view": "a view has no data files to re-read.",
    "cannot_refresh_managed_table": "only tables the portal created over files in your space can be refreshed.",
    "cannot_refresh_catalog_partitioned": "tables with catalog-registered partitions can't be refreshed.",
    "cannot_refresh_location_unsupported": "that table's data location isn't one this portal can read.",
    "table_outside_space": "that table's data is outside the space you're refreshing it from.",
    "projection_not_reconstructable": (
        "that table's partition settings can't be read back - drop the table and build it "
        "again to change them."
    ),
    "definition_too_large": "that table has too many columns to refresh.",
    "format_changed": "the folder's file format no longer matches the table's - build a new table instead.",
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


# Register the domain reason codes (incl. the base codes redundantly — idempotent) so a
# TerminalError raised with any of them passes cpcommon's raise-time check (FR-005).
_cpmessages.register_reasons(_BODIES)

