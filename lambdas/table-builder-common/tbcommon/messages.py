"""User-facing notification text for table-builder outcomes.

One place maps each stable terminal reason code to friendly text addressed to the actor, so
every verb and its tests agree on the wording. Kept ASCII — no smart quotes. This module
keeps its own bespoke ``failure_message`` wording rather than using a ``cpcommon`` resolver,
and registers its reason codes with cpcommon at import so they pass ``TerminalError``'s
raise-time validation.

Attributes:
  _ACCESS_DENIED: Reasons meaning "not allowed", where no table name is surfaced because the
    request may not have got far enough to trust one.
  _BODIES: Reason code to the clause following ``Couldn't create table "{name}": ``. The
    DDL-failure reasons carry no raw Athena text — that stays in logs and the SFN record for
    operators, never in the actor's notification. The refresh reasons read correctly under
    either verb because ``failure_message`` picks the prefix from the request's mode.
  _MARKERS: Every marker any body declares, read off the bodies rather than listed, so a new
    one is blanked-when-absent automatically instead of shipping literally the first time a
    caller forgets it. The pattern matches any brace group rather than lowercase words,
    because the surrounding code is camelCase and a camelCase marker would otherwise be
    missed by the discovery and rendered raw — the exact failure this exists to prevent.
  MAX_NAMED_COLUMNS: Longest list of column names named in a body or carried in a link, so
    neither a notification nor a URL is unbounded by a user's schema.
"""

import json
import re

from cpcommon import messages as _cpmessages

_ACCESS_DENIED = frozenset({"unauthorized", "forbidden"})

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
    "columns_removed": (
        "these columns are no longer in the data and would be removed: {removed}. Nothing "
        "was changed - refresh again and confirm the removal to apply it."
    ),
    "removals_flag_not_applicable": "the request was malformed. Please try again.",
    "update_failed": "the table couldn't be updated. Nothing was changed. Please try again or contact the Administrator.",
    "unexpected_error": "something went wrong. Please try again.",
}


_MARKERS = frozenset(re.findall(r"\{([^{}]*)\}", " ".join(_BODIES.values())))

MAX_NAMED_COLUMNS = 20


def removed_tokens(names: list[str]) -> dict:
    """Builds both halves of the tokens a columns-removed refusal carries.

    Built together so the cap and the encoding cannot drift apart. Two separate values rather
    than one re-split string, because splitting the display string back apart is wrong twice
    over: the "and N more" tail is not a column name, and column names are not catalog-safe.
    They come verbatim from a file header or a Glue column and are never validated, so one
    containing a comma, a space or an ampersand would be silently mangled. JSON is the
    separator-free encoding that makes the round trip exact.

    Args:
      names: Every column name that would be removed.

    Returns:
      ``{"removed": …, "removedNames": …}`` — the capped display string the message body
      renders, and the JSON list the notification link is built from.

    Raises:
      None.
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
    """Maps a terminal reason and its context to the message the actor sees.

    Substitution is ``str.replace``, never ``str.format``, and every declared marker is
    substituted rather than only the supplied ones — an absent token must leave a sentence
    rather than a literal brace group on the user's screen. The trusted context wins over the
    payload: tokens come from a raise site and must not shadow the database this layer was
    told about. No raw AWS or Athena text is ever interpolated.

    Args:
      reason: The terminal reason code. An unknown one falls back to a generic line rather
        than leaking the code.
      table_name: The table the request names, if one is trusted yet.
      database: The database the request names.
      mode: ``create`` or ``refresh``, picking the verb. It reaches the access-denied
        short-circuit too, and that is not a detail — ``forbidden`` is the ordinary outcome of
        refreshing from a stale schema rail, so a create-only line would tell a user they
        cannot create a table they were trying to refresh.
      tokens: Optional marker values from the raise site.

    Returns:
      The full actor-facing sentence.

    Raises:
      None.
    """
    verb = "refresh" if mode == "refresh" else "create"
    if reason in _ACCESS_DENIED:
        return f"You don't have access to {verb} a table here."
    name = table_name or "your table"
    body = _BODIES.get(reason, "something went wrong.")
    values = {**(tokens or {}), "database": database}
    for marker in _MARKERS:
        body = body.replace("{" + marker + "}", values.get(marker) or "")
    return f'Couldn\'t {verb} table "{name}": {body}'


def _plural(count: int, noun: str) -> str:
    """Renders a count with its noun, pluralised by a trailing s.

    Args:
      count: The number to render.
      noun: The singular noun.

    Returns:
      The count and noun as one string.

    Raises:
      None.
    """
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def success_message(
    table_name: str,
    database: str,
    status: str = "created",
    added: int = 0,
    retyped: int = 0,
    removed: int = 0,
) -> str:
    """Composes the message emitted on a successful terminal outcome.

    An unchanged refresh reads differently from one that changed something on purpose: a
    refresh that found nothing must not look like one that did, or a user concludes the button
    is broken — and the counts are what make "it worked" checkable rather than merely
    reassuring.

    Args:
      table_name: The table the request named.
      database: The database it lives in.
      status: ``created``, ``refreshed`` or ``unchanged``.
      added: Columns added by a refresh.
      retyped: Columns retyped by a refresh.
      removed: Columns removed by a refresh.

    Returns:
      The full actor-facing sentence.

    Raises:
      None.
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


_cpmessages.register_reasons(_BODIES)
