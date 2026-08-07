"""User-facing notification text for table-share outcomes.

One place maps each stable terminal reason code to friendly text, so every verb and its tests
agree on the wording. Sender messages name the recipient for a per-recipient outcome, or just
the source for a whole-request failure; success-target messages address the recipient user or
the recipient space's owner. Kept ASCII — no smart quotes.

This module keeps its own bespoke ``failure_message`` wording rather than using a ``cpcommon``
resolver, and registers its reason codes with cpcommon at import so they pass
``TerminalError``'s raise-time validation.

Attributes:
  _ACCESS_DENIED: Reasons meaning "not allowed", where no table detail is surfaced because the
    request may not have got far enough to trust one.
  _BODIES: Reason code to the clause following the "Couldn't share …" prefix. The create-failure
    reasons carry no raw Athena text — that stays in logs and the SFN record for operators.
    Note the recipient cap's wording carries no marker: this module substitutes only the table
    name and has no general token mechanism, so an unsubstituted marker would ship to the
    user's inbox verbatim.
"""

from cpcommon import messages as _cpmessages

from . import config

_ACCESS_DENIED = frozenset({"unauthorized", "forbidden"})

_BODIES = {
    "invalid_table_name": "the result name isn't a valid table name.",
    "no_recipients": "no recipients were given.",
    "invalid_recipients": "the recipient list is malformed.",
    "too_many_recipients": (
        f"a share can go to at most {config.SHARE_MAX_RECIPIENTS} recipients at a time. "
        "Please share to fewer."
    ),
    "source_not_found": "the source table doesn't exist.",
    "source_not_readable": "the source table couldn't be read.",
    "source_is_view": "views can't be shared - only tables with data files.",
    "source_not_external": "only base external tables can be shared.",
    "source_catalog_partitioned": "tables with catalog-registered partitions can't be shared (yet).",
    "source_empty": "the source table has no data files.",
    "source_too_large": "the source table is too large to share.",
    "source_definition_too_large": (
        "that table has too many columns (or too much column detail) to share. "
        "Please share a narrower table."
    ),
    "source_location_unsupported": "the source table's data location isn't supported.",
    "unknown_user": "there is no user with that name.",
    "unknown_space": "there is no shared space with that name.",
    "unknown_target": "that recipient isn't a valid target.",
    "conflict": 'a table named "{tableName}" already exists there.',
    "target_not_readable": "the recipient's database couldn't be checked.",
    "copy_failed": "copying the data failed.",
    "create_failed": "creating the table failed. Please try again or contact the Administrator.",
    "create_timeout": "creating the table failed. Please try again or contact the Administrator.",
    "unexpected_error": "something went wrong. Please try again.",
}


def _recipient_phrase(kind: str, name: str) -> str:
    """Renders a recipient as a kind-qualified, quoted phrase.

    Args:
      kind: ``user`` or ``space``.
      name: The recipient's name.

    Returns:
      The phrase for interpolation into a sentence.

    Raises:
      None.
    """
    return f'{"user" if kind == "user" else "space"} "{name}"'


def failure_message(
    reason: str,
    source_table: str = "",
    *,
    kind: str = "",
    name: str = "",
    table_name: str = "",
) -> str:
    """Composes the sender-facing failure text for a terminal reason and its context.

    The table-name placeholder is substituted directly rather than through string formatting,
    so a body that ever contains a literal brace cannot raise. No raw AWS or Athena text is
    ever interpolated.

    Args:
      reason: The terminal reason code. An unknown one falls back to a generic clause rather
        than leaking the code.
      source_table: The source table's name.
      kind: The recipient kind, when this is a per-recipient outcome.
      name: The recipient's name, when this is a per-recipient outcome.
      table_name: The result table name, for the bodies that name it.

    Returns:
      The sentence, reading as a per-recipient outcome when a recipient is given and as a
      whole-request failure otherwise.

    Raises:
      None.
    """
    if reason in _ACCESS_DENIED:
        return "You don't have access to share that table."
    src = source_table or "your table"
    body = _BODIES.get(reason, "something went wrong.")
    body = body.replace("{tableName}", table_name or "")
    if kind and name:
        return f'Couldn\'t share "{src}" to {_recipient_phrase(kind, name)}: {body}'
    return f'Couldn\'t share "{src}": {body}'


def success_message(source_table: str, kind: str, name: str, table_name: str) -> str:
    """Composes the sender-facing per-recipient success text.

    Args:
      source_table: The source table's name.
      kind: The recipient kind.
      name: The recipient's name.
      table_name: The result table name.

    Returns:
      The sentence.

    Raises:
      None.
    """
    return f'Shared "{source_table}" to {_recipient_phrase(kind, name)} as "{table_name}".'


def recipient_user_message(actor: str, table_name: str, database: str) -> str:
    """Composes the text a user recipient sees in their own inbox.

    Args:
      actor: The sender's username.
      table_name: The result table name.
      database: The recipient's database.

    Returns:
      The sentence.

    Raises:
      None.
    """
    return f'{actor} shared table "{table_name}" with you in "{database}".'


def space_owner_message(actor: str, table_name: str, space: str) -> str:
    """Composes the text a recipient space's owner sees. The owner only, never the members.

    Args:
      actor: The sender's username.
      table_name: The result table name.
      space: The recipient space's name.

    Returns:
      The sentence.

    Raises:
      None.
    """
    return f'{actor} shared table "{table_name}" into your space "{space}".'


_cpmessages.register_reasons(_BODIES)
