"""User-facing notification text for file-send outcomes.

One place maps each stable terminal reason code to friendly text, so every verb and its tests
agree on the wording. Kept ASCII — no smart quotes.

This module is the table and its wording; the resolution itself is ``cpcommon.messages``
(SPEC-156 FR-002), which also marks these codes valid so they pass ``TerminalError``'s
raise-time validation. ``unexpected_error`` is deliberately absent — it resolves through the
base table and renders the same sentence everywhere.

**No raw AWS text is ever interpolated into any of these** (SPEC-106): the detail on the
exception is for the logs and the Step Functions record, and the sentence the user reads is
composed here.

Attributes:
  _BODIES: Reason code to the clause following the "Couldn't send ..." prefix. The three cap
    bodies carry a marker rather than the number, so the sentence is filled from ``config`` by
    ``failure_message`` and cannot drift from the constant that enforces it. ``{itemName}`` is
    the one marker filled from the RAISE SITE instead — it is the sender's own folder name, not
    a number this module can know, and it is deliberately spelled ``itemName`` rather than
    ``name`` because ``name`` already means the recipient's name in ``failure_message``.
  resolver: The domain-scoped resolver, carrying this plane's prefix, access-denied clause and
    fallback.
"""

from cpcommon import messages as _cpmessages

from . import config

_BODIES = {
    "no_items": "nothing was selected to send.",
    "invalid_items": "the list of files to send is malformed.",
    "too_many_items": (
        "you can send at most {maxItems} files or folders at a time. Please send fewer."
    ),
    "selection_too_large": (
        "that selection is too large to send in one go. Please send fewer files or folders."
    ),
    "no_recipients": "no recipients were given.",
    "invalid_recipients": "the recipient list is malformed.",
    "too_many_recipients": (
        "a send can go to at most {maxRecipients} recipients at a time. Please send to fewer."
    ),
    "results_not_sendable": (
        "query results can't be sent. Please save what you need to a folder first, and send that."
    ),
    "unknown_user": "there is no user with that name.",
    "unknown_space": "there is no shared space with that name.",
    "source_missing": "one of the files you selected is no longer there.",
    "nothing_to_send": "there was nothing to send in what you selected.",
    "overlapping_items": (
        "one of the folders you selected already contains another thing you selected. "
        "Please send one or the other."
    ),
    "colliding_item_names": (
        'two of the things you selected are both called "{itemName}". '
        "Please send them separately."
    ),
    "too_many_objects": (
        "that selection holds more than {maxObjects} files. Please send fewer folders."
    ),
    "source_too_large": "that selection is too large to send. Please send fewer files or folders.",
}


resolver = _cpmessages.register(
    _BODIES,
    prefix="Couldn't send{toRecipient}: ",
    access_denied="You don't have access to send those files.",
    fallback="something went wrong.",
    blank_unfilled=True,
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
    *,
    kind: str = "",
    name: str = "",
    tokens: dict | None = None,
) -> str:
    """Composes the sender-facing failure text for a terminal reason and its context.

    This layer's job is the trusted context; the resolver composes the sentence. That context
    is passed LAST so it wins over the payload — a raise site's token must not shadow the
    recipient clause or misstate a cap.

    Args:
      reason: The terminal reason code. An unknown one falls back to a generic clause rather
        than leaking the code.
      kind: The recipient kind, when this is a per-recipient outcome.
      name: The recipient's name, when this is a per-recipient outcome.
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
            "toRecipient": f" to {_recipient_phrase(kind, name)}" if kind and name else "",
            "maxItems": str(config.SEND_MAX_ITEMS),
            "maxRecipients": str(config.SEND_MAX_RECIPIENTS),
            "maxObjects": f"{config.SEND_MAX_OBJECTS:,}",
        },
    )
