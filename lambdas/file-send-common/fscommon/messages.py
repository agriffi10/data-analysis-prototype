"""User-facing notification text for file-send outcomes.

One place maps each stable terminal reason code to friendly text, so every verb and its tests
agree on the wording. Kept ASCII — no smart quotes.

This module is the table and its wording; the resolution itself is ``cpcommon.messages``
, which also marks these codes valid so they pass ``TerminalError``'s
raise-time validation. ``unexpected_error`` is deliberately absent — it resolves through the
base table and renders the same sentence everywhere.

**No raw AWS text is ever interpolated into any of these** (SPEC-106): the detail on the
exception is for the logs and the Step Functions record, and the sentence the user reads is
composed here.

Attributes:
  _BODIES: Reason code to the clause following the "Couldn't send ..." prefix. The cap bodies
    that CAN name a number carry a marker rather than the number, so the sentence is filled from
    ``config`` by ``failure_message`` and cannot drift from the constant that enforces it. The
    two product caps deliberately name none: the limit is ``objects x recipients``, and a
    sentence quoting either factor alone would read as a rule the code does not have.

    ``{itemName}`` is the one marker filled from the RAISE SITE instead — it is the sender's own
    folder name, not a number this module can know, and it is deliberately spelled ``itemName``
    rather than ``name`` because ``name`` already means the recipient's name in
    ``failure_message``.
  resolver: The domain-scoped resolver, carrying this plane's prefix, access-denied clause and
    fallback.
"""

from cpcommon import messages as _cpmessages

from . import config
from .paths import inbox_label

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
    "object_too_large": (
        "one of those files is bigger than {maxObjectSize} and can't be sent. "
        "Please send it another way."
    ),
    "too_many_transfer_items": (
        "that many files to that many people is too much to send in one go. "
        "Please send to fewer recipients, or send fewer files."
    ),
    "transfer_too_large": (
        "that much data to that many people is too much to send in one go. "
        "Please send to fewer recipients, or send fewer files."
    ),
    "conflict": (
        'they already have something called "{itemName}" from you, and nothing was '
        "overwritten. Please rename it, or ask them to move what is already there."
    ),
    "copy_failed": "some of the files could not be copied.",
    "send_timed_out": (
        "the send was still running after several hours and was stopped. Some recipients may "
        "have received part of it, so please check before sending again."
    ),
    "transfer_results_unreadable": (
        "the copy ran but its results could not be read, so we can't confirm what arrived. "
        "Please check before sending again."
    ),
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


def _things_phrase(item_names, object_count: int) -> str:
    """Renders what was sent as a phrase a person would say.

    The item names are what the sender picked and what the recipient sees in their inbox; the
    object count is what those expanded to, and the two differ by orders of magnitude for a
    folder. Both are given because either alone misleads — "1 thing" for a 3,000-file folder, or
    "3,000 files" for something the recipient will find under one name.

    Args:
      item_names: The selected item names, in selection order.
      object_count: How many objects they expanded to.

    Returns:
      The phrase, e.g. ``"reports" and "notes.txt" (301 files)``.

    Raises:
      None.
    """
    names = [f'"{name}"' for name in (item_names or []) if name]
    if not names:
        listed = "some files"
    elif len(names) == 1:
        listed = names[0]
    elif len(names) <= 3:
        listed = f"{', '.join(names[:-1])} and {names[-1]}"
    else:
        listed = f"{', '.join(names[:2])} and {len(names) - 2} more"
    files = "file" if object_count == 1 else "files"
    return f"{listed} ({object_count:,} {files})"


def success_message(kind: str, name: str, item_names, object_count: int) -> str:
    """Composes the sender-facing per-recipient SUCCESS text.

    Args:
      kind: The recipient kind.
      name: The recipient's name.
      item_names: The selected item names.
      object_count: How many objects were copied for that recipient.

    Returns:
      The sentence.

    Raises:
      None.
    """
    return f"Sent {_things_phrase(item_names, object_count)} to {_recipient_phrase(kind, name)}."


def recipient_message(sender: str, item_names, object_count: int) -> str:
    """Composes the text a ``user`` recipient sees in their own inbox.

    It names the folder the files landed in as well as the sender, because the destination is the
    one thing the recipient cannot guess: a send arrives under ``shared_files/{sender}/``, which
    is not where they were last working.

    Args:
      sender: The verified sender's username.
      item_names: The selected item names.
      object_count: How many objects arrived.

    Returns:
      The sentence.

    Raises:
      None.
    """
    return (
        f"{sender} sent you {_things_phrase(item_names, object_count)}. "
        f"You'll find them in {inbox_label(sender)}."
    )


def space_owner_message(sender: str, space: str, item_names, object_count: int) -> str:
    """Composes the text a recipient space's OWNER sees. The owner only, never the members.

    Args:
      sender: The verified sender's username.
      space: The recipient space's name.
      item_names: The selected item names.
      object_count: How many objects arrived.

    Returns:
      The sentence.

    Raises:
      None.
    """
    return (
        f'{sender} sent {_things_phrase(item_names, object_count)} to your space "{space}". '
        f"You'll find them in {inbox_label(sender)}."
    )


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
            "maxObjectSize": f"{config.SEND_MAX_OBJECT_BYTES // 1024**3} GB",
        },
    )
