"""User-facing notification text for archive and restore outcomes.

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
  _BODIES: Reason code to the clause following the "Couldn't archive ..." prefix. The cap body
    that CAN name a number carries a marker rather than the number, so the sentence is filled
    from ``config`` by ``failure_message`` and cannot drift from the constant that enforces it.
    ``{itemName}`` is filled from the RAISE SITE instead — it is the user's own folder name, not
    a number this module can know.

    **One prefix serves both modes**, and the wording is chosen so it can: "Couldn't archive
    that" reads correctly for a failed archive, and a restore failure is worded inside its own
    body. Two resolvers would mean two prefixes to keep in step for one queue of messages.
  resolver: The domain-scoped resolver, carrying this plane's prefix, access-denied clause and
    fallback.
"""

from cpcommon import messages as _cpmessages

from . import config

_BODIES = {
    "invalid_request": "that request was malformed and could not be run.",
    "no_items": "nothing was selected.",
    "invalid_items": "the list of files was malformed.",
    "too_many_items": (
        "you can archive at most {maxItems} files or folders at a time. Please select fewer."
    ),
    "selection_too_large": (
        "that selection is too large to archive in one go. Please select fewer files or folders."
    ),
    "reserved_folder": (
        "that folder is managed by the portal and can't be archived. "
        "Please select your own files or folders instead."
    ),
    "protected_marker": (
        "one of the things you selected can't be removed from your space, so nothing was "
        "archived. Please select something else."
    ),
    "unknown_space": "there is no shared space with that name.",
}


resolver = _cpmessages.register(
    _BODIES,
    prefix="Couldn't archive that: ",
    access_denied="You don't have access to archive those files.",
    fallback="something went wrong.",
    blank_unfilled=True,
)


def failure_message(reason: str, *, tokens: dict | None = None) -> str:
    """Composes the actor-facing failure text for a terminal reason and its context.

    This layer's job is the trusted context; the resolver composes the sentence. That context is
    passed LAST so it wins over the payload — a raise site's token must not misstate a cap.

    Args:
      reason: The terminal reason code. An unknown one falls back to a generic clause rather
        than leaking the code.
      tokens: Optional marker values from the raise site, carried on the terminal error.

    Returns:
      The sentence.

    Raises:
      None.
    """
    return resolver.message(
        reason,
        **{
            **(tokens or {}),
            "maxItems": str(config.ARCHIVE_MAX_ITEMS),
        },
    )
