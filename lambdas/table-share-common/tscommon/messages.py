"""User-facing notification text for table-share outcomes (SPEC-094).

One place maps each stable terminal reason code to friendly text, so every verb +
its tests agree on the wording. Sender messages name the recipient (per-recipient
outcomes) or just the source (whole-request failures); success-target messages
address the recipient user or the recipient space's owner. Kept ASCII (no smart
quotes), mirroring tbcommon.messages.

This module keeps its own bespoke ``failure_message`` wording (SPEC-107 FR-002 —
unchanged); it registers the table-share domain reason codes with cpcommon at import so
they pass ``TerminalError``'s raise-time validation (SPEC-107 FR-005).
"""

from cpcommon import messages as _cpmessages

from . import config

# Reasons that mean "not allowed" — no table detail is surfaced (the request may
# not even have got far enough to trust one).
_ACCESS_DENIED = frozenset({"unauthorized", "forbidden"})

# reason -> the clause after "Couldn't share "{source}" [to {recipient}]: ".
# {tableName} is substituted per-call where relevant. The create-failure reasons
# carry NO raw Athena StateChangeReason (SPEC-106 FR-008) — that detail stays in
# logs + the SFN terminal record for operators, never in a notification.
_BODIES = {
    # Whole-request failures (validate-authorize / inspect-source).
    "invalid_table_name": "the result name isn't a valid table name.",
    "no_recipients": "no recipients were given.",
    "invalid_recipients": "the recipient list is malformed.",
    "too_many_recipients": (
        f"a share can go to at most {config.SHARE_MAX_RECIPIENTS} recipients "
        "({count} were given). Please share to fewer at a time."
    ),
    "source_not_found": "the source table doesn't exist.",
    "source_not_readable": "the source table couldn't be read.",
    "source_is_view": "views can't be shared - only tables with data files.",
    "source_not_external": "only base external tables can be shared.",
    "source_catalog_partitioned": "tables with catalog-registered partitions can't be shared (yet).",
    "source_empty": "the source table has no data files.",
    "source_too_large": "the source table is too large to share.",
    "source_location_unsupported": "the source table's data location isn't supported.",
    # Per-recipient failures (the Map verbs).
    "unknown_user": "there is no user with that name.",
    "unknown_space": "there is no shared space with that name.",
    "unknown_target": "that recipient isn't a valid target.",
    "conflict": 'a table named "{tableName}" already exists there.',
    "target_not_readable": "the recipient's database couldn't be checked.",
    "copy_failed": "copying the data failed.",
    "create_failed": "creating the table failed. Please try again or contact the Administrator.",
    "create_timeout": "creating the table failed. Please try again or contact the Administrator.",
    # Generic catch-all for an unexpected (non-terminal) verb exception — emitted by
    # notify.notifies_on_failure so an unexpected failure still reaches the sender.
    "unexpected_error": "something went wrong. Please try again.",
}


def _recipient_phrase(kind: str, name: str) -> str:
    return f'{"user" if kind == "user" else "space"} "{name}"'


def failure_message(
    reason: str,
    source_table: str = "",
    *,
    kind: str = "",
    name: str = "",
    table_name: str = "",
) -> str:
    """The sender-facing failure text for a terminal reason (+ context).

    With ``kind``/``name`` it reads as a per-recipient outcome; without them it is
    a whole-request failure. An unknown reason falls back to a generic clause
    rather than leaking the code. No raw AWS/Athena text is ever interpolated
    (SPEC-106 FR-008).
    """
    if reason in _ACCESS_DENIED:
        return "You don't have access to share that table."
    src = source_table or "your table"
    body = _BODIES.get(reason, "something went wrong.")
    # Substitute the known placeholder directly (never str.format) so a body that
    # ever contains a literal brace can't raise (the SPEC-083 FR-005 rule).
    body = body.replace("{tableName}", table_name or "")
    if kind and name:
        return f'Couldn\'t share "{src}" to {_recipient_phrase(kind, name)}: {body}'
    return f'Couldn\'t share "{src}": {body}'


def success_message(source_table: str, kind: str, name: str, table_name: str) -> str:
    """The sender-facing per-recipient success text."""
    return f'Shared "{source_table}" to {_recipient_phrase(kind, name)} as "{table_name}".'


def recipient_user_message(actor: str, table_name: str, database: str) -> str:
    """The text a USER recipient sees in their own inbox."""
    return f'{actor} shared table "{table_name}" with you in "{database}".'


def space_owner_message(actor: str, table_name: str, space: str) -> str:
    """The text a recipient SPACE's owner sees (owner only — never the members)."""
    return f'{actor} shared table "{table_name}" into your space "{space}".'


# Register the domain reason codes (incl. the base codes redundantly — idempotent) so a
# TerminalError raised with any of them passes cpcommon's raise-time check (FR-005).
_cpmessages.register_reasons(_BODIES)
