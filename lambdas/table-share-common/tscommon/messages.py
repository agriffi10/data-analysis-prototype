"""User-facing notification text for table-share outcomes.

One place maps each stable terminal reason code to friendly text, so every verb and its tests
agree on the wording. Sender messages name the recipient for a per-recipient outcome, or just
the source for a whole-request failure; success-target messages address the recipient user or
the recipient space's owner. Kept ASCII — no smart quotes.

This module is the table and its wording; the resolution itself is ``cpcommon.messages``
, which also marks these codes valid so they pass ``TerminalError``'s
raise-time validation. ``unexpected_error`` is deliberately absent from the table below — it
was declared here byte-identically to ``cpcommon``'s own and resolves through the base table
now, rendering the same sentence.

Attributes:
  _BODIES: Reason code to the clause following the "Couldn't share …" prefix. The create-failure
    reasons carry no raw Athena text — that stays in logs and the SFN record for operators.
    The recipient cap's wording carries a marker rather than the constant: the cap is filled
    from ``config`` by ``failure_message`` itself, so it cannot drift from the value that
    enforces it and a raise site cannot misstate it.
  resolver: The domain-scoped resolver, carrying this plane's prefix, access-denied clause
    and shorter unknown-reason fallback.
"""

from cpcommon import messages as _cpmessages

from . import config

_BODIES = {
    "invalid_table_name": "the result name isn't a valid table name.",
    "no_recipients": "no recipients were given.",
    "invalid_recipients": "the recipient list is malformed.",
    "too_many_recipients": (
        "a share can go to at most {max} recipients at a time. Please share to fewer."
    ),
    "source_not_found": "the source table doesn't exist.",
    "source_not_readable": "the source table couldn't be read.",
    "source_is_view": "views can't be shared - only tables with data files.",
    "source_not_external": "only base external tables can be shared.",
    "source_catalog_partitioned": "tables with catalog-registered partitions can't be shared (yet).",
    "source_empty": "the source table has no data files.",
    "source_too_large": "the source table is too large to share.",
    "source_object_too_large": (
        "one of that table's data files is too large to copy. "
        "Please contact the Administrator."
    ),
    "too_many_transfer_items": (
        "that's too many files to copy to that many recipients at once. "
        "Please share to fewer recipients, or share a smaller table."
    ),
    "transfer_too_large": (
        "that's too much data to copy to that many recipients at once. "
        "Please share to fewer recipients, or share a smaller table."
    ),
    "source_definition_too_large": (
        "that table has too many columns (or too much column detail) to share. "
        "Please share a narrower table."
    ),
    "definition_unreadable": (
        "we couldn't read the table's own definition, so no table was created. "
        "Please try again or contact the Administrator."
    ),
    "source_location_unsupported": "the source table's data location isn't supported.",
    "unknown_user": "there is no user with that name.",
    "unknown_space": "there is no shared space with that name.",
    "unknown_target": "that recipient isn't a valid target.",
    "conflict": 'a table named "{tableName}" already exists there.',
    "target_not_readable": "the recipient's database couldn't be checked.",
    "copy_failed": "copying the data failed.",
    "transfer_results_unreadable": (
        "we couldn't confirm the copy finished, so the share was stopped. "
        "Please try again or contact the Administrator."
    ),
    "share_timed_out": (
        "the share ran for too long and was stopped. Some recipients may have received part "
        "of the data. Please contact the Administrator before trying again."
    ),
    "create_failed": "creating the table failed. Please try again or contact the Administrator.",
    "create_timeout": "creating the table failed. Please try again or contact the Administrator.",
}


resolver = _cpmessages.register(
    _BODIES,
    prefix='Couldn\'t share "{source}"{toRecipient}: ',
    access_denied="You don't have access to share that table.",
    fallback="something went wrong.",
)


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
    tokens: dict | None = None,
) -> str:
    """Composes the sender-facing failure text for a terminal reason and its context.

    This layer's job is the trusted context; the resolver composes the sentence. That context
    is passed last so it wins over the payload — a raise site's token must not shadow the
    recipient clause, the result table name or the recipient cap. No raw AWS or Athena text
    is ever interpolated.

    Args:
      reason: The terminal reason code. An unknown one falls back to a generic clause rather
        than leaking the code.
      source_table: The source table's name.
      kind: The recipient kind, when this is a per-recipient outcome.
      name: The recipient's name, when this is a per-recipient outcome.
      table_name: The result table name, for the bodies that name it.
      tokens: Optional marker values from the raise site, carried on the terminal error.

    Returns:
      The sentence, reading as a per-recipient outcome when a recipient is given and as a
      whole-request failure otherwise.

    Raises:
      None.
    """
    return resolver.message(
        reason,
        **{
            **(tokens or {}),
            "source": source_table or "your table",
            "toRecipient": f" to {_recipient_phrase(kind, name)}" if kind and name else "",
            "tableName": table_name or "",
            "max": str(config.SHARE_MAX_RECIPIENTS),
        },
    )


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
