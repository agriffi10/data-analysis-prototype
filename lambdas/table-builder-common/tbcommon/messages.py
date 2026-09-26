"""User-facing notification text for table-builder outcomes.

One place maps each stable terminal reason code to friendly text addressed to the actor, so
every verb and its tests agree on the wording. Kept ASCII — no smart quotes. This module is
the table and its wording; the resolution itself is ``cpcommon.messages``,
which also marks these codes valid so they pass ``TerminalError``'s raise-time validation.

The shared base codes are deliberately absent from the table below. ``malformed_event`` and
``unexpected_error`` were declared here byte-identically to ``cpcommon``'s own, which is the
overlap the resolver refuses — they resolve through the base table now and render the same
sentence.

Attributes:
  _BODIES: Reason code to the clause following ``Couldn't create table "{name}": ``. The
    DDL-failure reasons carry no raw Athena text — that stays in logs and the SFN record for
    operators, never in the actor's notification. The refresh reasons read correctly under
    either verb because the prefix template takes the verb from the request's mode.
  resolver: The domain-scoped resolver, carrying this plane's prefix, access-denied clause
    and shorter unknown-reason fallback.
  _MARKERS: Every marker any body declares, discovered by the resolver rather than listed,
    so a new one is blanked-when-absent automatically instead of shipping literally the
    first time a caller forgets it.
  MAX_NAMED_COLUMNS: Longest list of column names named in a body or carried in a link, so
    neither a notification nor a URL is unbounded by a user's schema.
  _REMOVAL_EFFECT: The sentence a removal refusal adds where the SerDe matches by position and
    a removed column therefore shifts every file that still has it. Carried as a token rather
    than a second template, so the two formats' wording cannot drift apart around the one
    clause that differs. It opens with a space, because the marker sits against the column
    list's full stop and the empty case has to leave today's spacing untouched.
"""

import json

from cpcommon import ddl
from cpcommon import messages as _cpmessages

_BODIES = {
    "invalid_table_name": "the name isn't a valid table name.",
    "location_is_space_root": (
        "a table reads every file in the folder it's built from, so it can't be built from the "
        "top of a space - open the folder holding your data and build it there."
    ),
    "invalid_partition_keys": "the partition keys aren't valid (check names, types, and ranges).",
    "table_exists": 'a table with that name already exists in "{database}".',
    "no_data_files": "no supported data files were found in that folder.",
    "mixed_formats": "the folder mixes file formats - use a single format.",
    "unsupported_format": (
        "that folder holds a file that isn't Parquet, CSV, or JSON, and a table reads every file "
        "in its folder - move it out, or build from a folder holding only data files."
    ),
    "unexpected_partitioning": "the folder is partitioned but no partition keys were provided.",
    "partition_layout_mismatch": "the partition keys don't match the folder layout (check names and order).",
    "invalid_column_names": (
        "these column names won't work in Athena: {columns}. Athena column names can only use "
        "letters, digits and underscores, and two names that differ only by case become one "
        "column - rename them in your files and try again."
    ),
    "schema_inference_failed": "the data schema couldn't be read.",
    "unmappable_type": "the data schema couldn't be read.",
    "ddl_execution_failed": "creating the table failed. Please try again or contact the Administrator.",
    "ddl_timeout": "creating the table failed. Please try again or contact the Administrator.",
    "invalid_mode": "the request was malformed. Please try again.",
    "partition_keys_not_refreshable": (
        "a refresh keeps the table's existing partition keys - to change them, drop the "
        "table and build it again."
    ),
    "table_not_found": 'no table named that exists in "{database}".',
    "cannot_refresh_view": "a view has no data files to re-read.",
    "cannot_refresh_managed_table": "only tables Data Quarry created over files in your space can be refreshed.",
    "cannot_refresh_catalog_partitioned": "tables with catalog-registered partitions can't be refreshed.",
    "cannot_refresh_location_unsupported": "that table's data location isn't one Data Quarry can read.",
    "table_outside_space": "that table's data is outside the space you're refreshing it from.",
    "projection_not_reconstructable": (
        "that table's partition settings can't be read back - drop the table and build it "
        "again to change them."
    ),
    "definition_too_large": "that table has too many columns to refresh.",
    "format_changed": "the folder's file format no longer matches the table's - build a new table instead.",
    "columns_removed": (
        "these columns aren't in the first file in the table's folder and would be removed: "
        "{removed}.{removalEffect} Nothing was changed - refresh again and confirm the removal "
        "to apply it."
    ),
    "removals_flag_not_applicable": "the request was malformed. Please try again.",
    "table_changed_during_refresh": (
        "the table was changed by something else while this refresh was running. Nothing was "
        "changed - refresh again to pick up both sets of changes."
    ),
    "refresh_already_running": (
        "a refresh of that table is already running. Nothing was changed - wait for it to "
        "finish, then check whether you still need to refresh again."
    ),
    "update_failed": "the table couldn't be updated. Nothing was changed. Please try again or contact the Administrator.",
    "build_timed_out": (
        "it ran for too long and was stopped part-way, so the table may or may not have been "
        "built - check it before trying again. Give it a few minutes first: that table stays "
        "locked for a short while afterwards."
    ),
}


resolver = _cpmessages.register(
    _BODIES,
    prefix='Couldn\'t {verb} table "{name}": ',
    access_denied="You don't have access to {verb} a table here.",
    fallback="something went wrong.",
    blank_unfilled=True,
)

_MARKERS = resolver.markers

MAX_NAMED_COLUMNS = 20

_REMOVAL_EFFECT = (
    " Because this is a CSV table, any file that still has them would have the values after "
    "them read into the wrong columns."
)


def removed_tokens(names: list[str], fmt: str) -> dict:
    """Builds every token a columns-removed refusal carries, the format's own sentence included.

    Built together so the cap and the encoding cannot drift apart. Two separate values rather
    than one re-split string, because splitting the display string back apart is wrong twice
    over: the "and N more" tail is not a column name, and column names are not catalog-safe.
    They come verbatim from a file header or a Glue column and are never validated, so one
    containing a comma, a space or an ampersand would be silently mangled. JSON is the
    separator-free encoding that makes the round trip exact.

    The removal warning is the refusal, so where a removal costs more than the column it names,
    the refusal says so. In a positional format it does: the table's remaining columns close up,
    and every file that still carries the removed one reads the values after it one column
    across. A refresh keeping the table's order does not help here — the column is gone from the
    table either way — so the opt-in stays the whole gate and this sentence is what the user
    weighs. It is unconditional for the format rather than judged on which columns were removed:
    removing only the last column is harmless, and a refusal that said so would have to know
    which columns are last, which the dialog carrying the same sentence cannot.

    ``ddl.POSITIONAL_FORMATS`` is the predicate rather than a literal, so the sentence and the
    write that makes it true branch on one fact. It names CSV in words because CSV is that set's
    only member; the tests pin the membership, so a format joining it reddens there rather than
    shipping a sentence calling Parquet a CSV.

    The sentence is ordered BEFORE the names in the returned mapping, and that is not cosmetic:
    the resolver substitutes markers by ``str.replace`` in mapping order, so a column literally
    named ``{removalEffect}`` would otherwise have this sentence spliced into the middle of the
    column list. Filled first, its marker is gone before any user value is placed, so such a name
    blanks exactly as a column named ``{removed}`` already did rather than injecting a sentence.
    Blanking is the resolver's ``blank_unfilled`` and is not fixed here; the markers the message
    layer adds AFTER the tokens are still substituted into user values — a column named ``{name}``
    renders as the table's name — which is the resolver's to close, not this function's.

    Args:
      names: Every column name that would be removed.
      fmt: The source format, which decides whether the removal costs more than the columns.

    Returns:
      ``{"removalEffect": …, "removed": …, "removedNames": …}``, in that order — the format's
      sentence, empty where the SerDe matches by name; the capped display string the message body
      renders; and the JSON list the notification link is built from. The order is load-bearing,
      for the reason above.

    Raises:
      None.
    """
    shown = list(names)[:MAX_NAMED_COLUMNS]
    display = ", ".join(shown)
    remaining = len(names) - len(shown)
    if remaining > 0:
        display += f", and {remaining} more"
    return {
        "removalEffect": _REMOVAL_EFFECT if fmt in ddl.POSITIONAL_FORMATS else "",
        "removed": display,
        "removedNames": json.dumps(shown),
    }


def failure_message(
    reason: str,
    table_name: str = "",
    database: str = "",
    mode: str = "create",
    tokens: dict | None = None,
) -> str:
    """Maps a terminal reason and its context to the message the actor sees.

    This layer's job is the trusted context; the resolver composes the sentence. That context
    is passed last so it wins over the payload: tokens come from a raise site and must not
    shadow the database, the verb or the table name this layer was told about. No raw AWS or
    Athena text is ever interpolated.

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
    return resolver.message(
        reason,
        **{
            **(tokens or {}),
            "database": database,
            "verb": "refresh" if mode == "refresh" else "create",
            "name": table_name or "your table",
        },
    )


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


def renamed_sentence(renamed: list[tuple[str, str]]) -> str:
    """Says which of a create's columns the table holds under a new name, and why.

    A CSV column named after a partition key is kept under another name, because a CSV is read
    by position. The table's rail shows only the new name, so without this sentence the user
    meets an unfamiliar column and a familiar one apparently missing.

    Neither name is clipped, because the new name is the one the user has to find and a clip can
    cut exactly its suffix. They are short anyway: a column is renamed only when it folds to a
    declared partition key, which the dialog holds to ``PARTITION_KEY_NAME_RE``'s 63 characters.

    Args:
      renamed: ``(name in the files, name in the table)`` pairs, in declaration order.

    Returns:
      The sentence, with a leading space, or "" when nothing was renamed. At most
      ``MAX_NAMED_COLUMNS`` pairs are spelled out, then a count of the rest.

    Raises:
      None.
    """
    if not renamed:
        return ""
    shown = ", ".join(
        f'"{source}" is "{declared}"' for source, declared in renamed[:MAX_NAMED_COLUMNS]
    )
    remaining = len(renamed) - MAX_NAMED_COLUMNS
    if remaining > 0:
        shown += f", and {remaining} more"
    if len(renamed) == 1:
        return f" A column named after a partition key keeps its values under a new name: {shown}."
    return f" Columns named after a partition key keep their values under new names: {shown}."


def success_message(
    table_name: str,
    database: str,
    status: str = "created",
    added: int = 0,
    retyped: int = 0,
    removed: int = 0,
    renamed: list[tuple[str, str]] | None = None,
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
      renamed: A create's ``(name in the files, name in the table)`` pairs, which
        ``renamed_sentence`` appends. A refresh passes none: a renamed column a refresh adds
        belongs to a table built before columns were renamed, or to a header that gained its own
        column under the new name, and either way its count already says a column was added.

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
    return f'Table "{table_name}" is ready to query in "{database}".' + renamed_sentence(renamed or [])
