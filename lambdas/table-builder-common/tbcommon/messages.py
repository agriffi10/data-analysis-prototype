"""User-facing notification text for table-builder outcomes.

One place maps each stable terminal reason code to friendly text addressed to the
actor, so every verb + its tests agree on the wording. Kept ASCII (no smart quotes).

This module keeps its own bespoke ``failure_message`` wording (SPEC-107 FR-002 —
unchanged); it registers the table-builder domain reason codes with cpcommon at import
so they pass ``TerminalError``'s raise-time validation (SPEC-107 FR-005).
"""

import json
import re

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
    # Refresh-path reasons (SPEC-143/144). failure_message() picks the "create"/"refresh"
    # prefix from the request's mode, so these read correctly under either.
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
    # SPEC-144. `columns_removed` is the only body that reads a token, and it is the
    # WARNING itself: nothing has changed, and the specific names are what makes the
    # opt-in an informed one rather than a dare.
    "columns_removed": (
        "these columns are no longer in the data and would be removed: {removed}. Nothing "
        "was changed - refresh again and confirm the removal to apply it."
    ),
    "removals_flag_not_applicable": "the request was malformed. Please try again.",
    # SPEC-149. The ONE failure wording the refresh apply needs, because the apply is now a
    # single in-place glue:UpdateTable: it either replaced the definition or it did not, and
    # a failure leaves the table exactly as it was. SPEC-144's TWO rebuild reasons are GONE —
    # the second of them described a state of the world (the old table removed, the new one
    # not created) that this path cannot reach, and keeping it would be the message layer's
    # version of dead code.
    "update_failed": "the table couldn't be updated. Nothing was changed. Please try again or contact the Administrator.",
    # Generic catch-all for an unexpected (non-terminal) verb exception — emitted by
    # notify.notifies_on_failure so an unexpected failure still reaches the actor.
    "unexpected_error": "something went wrong. Please try again.",
}


#: Every `{marker}` any body declares, read off the bodies rather than listed, so a new one
#: is blanked-when-absent automatically instead of shipping literally the first time a
#: caller forgets it. The pattern matches ANY brace group, not `[a-z_]+`: the surrounding
#: code is camelCase throughout, so a `{removedCount}` would otherwise be missed by the
#: discovery and rendered raw to the user — the exact failure this exists to prevent.
_MARKERS = frozenset(re.findall(r"\{([^{}]*)\}", " ".join(_BODIES.values())))

#: Longest list of column names named in a body or carried in a link, so neither a
#: notification nor a URL is unbounded by a user's schema.
MAX_NAMED_COLUMNS = 20


def removed_tokens(names: list[str]) -> dict:
    """The tokens a ``columns_removed`` TerminalError carries.

    Both halves are built HERE so the cap and the encoding cannot drift apart: `removed` is
    the display string the body renders (capped, with an "and N more" tail), and
    `removedNames` is the machine-readable list the notification link is built from.

    Two separate values rather than one re-split string, because splitting the display
    string back apart is wrong twice over — the tail is not a column name, and **column
    names are not catalog-safe**. They come verbatim from a file header or a Glue column
    (`infer_schema` and `load_table_definition` never validate them), so one containing a
    comma, a space or an ampersand would be silently mangled. JSON is the separator-free
    encoding that makes the round trip exact.
    """
    shown = list(names)[:MAX_NAMED_COLUMNS]
    display = ", ".join(shown)
    remaining = len(names) - len(shown)
    if remaining > 0:
        display += f", and {remaining} more"
    return {"removed": display, "removedNames": json.dumps(shown)}


def failure_message(
    reason: str,
    table_name: str = "",
    database: str = "",
    mode: str = "create",
    tokens: dict | None = None,
) -> str:
    """Map a terminal reason (+ context) to the message the actor sees.

    An unknown reason falls back to a generic couldn't-{verb} line rather than leaking the
    code. No raw AWS/Athena text is ever interpolated (SPEC-106 FR-008).

    ``mode`` picks the verb. It reaches the access-denied short-circuit too, and that is
    not a detail: `forbidden` is the ORDINARY outcome of refreshing from a stale schema
    rail, so a create-only line would tell a user they can't *create* a table they were
    trying to refresh — about the most confusing thing this layer could say.
    """
    verb = "refresh" if mode == "refresh" else "create"
    if reason in _ACCESS_DENIED:
        return f"You don't have access to {verb} a table here."
    name = table_name or "your table"
    body = _BODIES.get(reason, "something went wrong.")
    # str.replace, never str.format (SPEC-083 FR-005). Every DECLARED marker is
    # substituted, not just the supplied ones — an absent token must leave a sentence
    # rather than a literal "{removed}" on the user's screen.
    # The trusted context wins over the payload: tokens come from a raise site and must
    # not be able to shadow the database this layer was told about.
    values = {**(tokens or {}), "database": database}
    for marker in _MARKERS:
        body = body.replace("{" + marker + "}", values.get(marker) or "")
    return f'Couldn\'t {verb} table "{name}": {body}'


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def success_message(
    table_name: str,
    database: str,
    status: str = "created",
    added: int = 0,
    retyped: int = 0,
    removed: int = 0,
) -> str:
    """The message emitted on a successful terminal outcome.

    ``unchanged`` reads differently from ``refreshed`` on purpose (FR-002): a refresh that
    found nothing must not look like one that changed something, or a user concludes the
    button is broken — and the counts are what make "it worked" checkable rather than
    merely reassuring.
    """
    if status == "unchanged":
        return f'Table "{table_name}" is already up to date - no schema changes were found.'
    if status == "refreshed":
        parts = []
        if added:
            parts.append(f"{_plural(added, 'column')} added")
        if retyped:
            parts.append(f"{_plural(retyped, 'column')} retyped")
        if removed:
            parts.append(f"{_plural(removed, 'column')} removed")
        changes = ", ".join(parts) if parts else "schema updated"
        return f'Table "{table_name}" was refreshed in "{database}": {changes}.'
    return f'Table "{table_name}" is ready to query in "{database}".'


# Register the domain reason codes (incl. the base codes redundantly — idempotent) so a
# TerminalError raised with any of them passes cpcommon's raise-time check (FR-005).
_cpmessages.register_reasons(_BODIES)

