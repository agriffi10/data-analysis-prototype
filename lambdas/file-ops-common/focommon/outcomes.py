"""The per-item outcome vocabulary every file-ops verb reads and extends.

An operation on a selection is not one result. Three of the selected items copy, one collides, one
names a folder the portal manages — and that has to survive from the first verb to the notification
or the partial execution the browser reports today is lost between specs. So each selected item
carries a record, created here and CARRIED FORWARD by every later verb rather than re-created.

**The record shape is fixed by the expansion spec and adopted here rather than invented**, because
this is the first producer and a different shape now would force every later verb and test to be
rewritten. ``itemKey`` is identity and ``label`` is display; they are never swapped.

**Three members ship with this verb and four arrive with the expansion.** ``noop`` and ``protected``
are produced here, and so is ``refused`` — which the expansion's own enumeration does not yet name.
It exists because ``protected`` means *a protected location*, and folding an into-itself refusal
into it would destroy the distinct-reason signal the whole per-refusal reason-code rule exists to
preserve.

Attributes:
  NOOP: The derived destination is the source. Reported as a success that did nothing, matching
    the browser, which treats a same-key move as a no-op rather than an error.
  PROTECTED: The item names one of the portal's own folders. Carries the rule's own reason code.
  REFUSED: The item cannot be operated on for a reason about the request itself — today, a
    destination inside the item's own subtree.
  MEMBERS: Every outcome this plane may carry, including the four a later verb adds. Closed and
    asserted, because an outcome nothing can word is a notification the user never gets.
"""

from dataclasses import dataclass

NOOP = "noop"
PROTECTED = "protected"
REFUSED = "refused"

MEMBERS = frozenset(
    {NOOP, PROTECTED, REFUSED, "cleared", "conflict", "source_missing", "source_empty"}
)

__all__ = ["MEMBERS", "NOOP", "PROTECTED", "REFUSED", "Refusal", "outcome"]


@dataclass(frozen=True)
class Refusal:
    """One protected-location rule's answer: why, and what to say about it.

    A returned value rather than a raised error, because these refusals are PER ITEM — a protected
    item fails alone and every other item proceeds, matching the browser, which refuses the gesture
    only when every selected item is protected. A whole-request refusal would turn a select-all
    delete at a space root, which today deletes what it may and reports the rest, into one that
    deletes nothing.

    Attributes:
      reason: The stable reason code, distinct per rule so the notifier can word it without
        re-deriving which rule fired.
      detail: Operator text naming the folder. Never rendered to a user.
    """

    reason: str
    detail: str


def outcome(item_key: str, label: str, name: str, reason: str | None = None) -> dict:
    """Builds one item's outcome record.

    Args:
      item_key: The selected item's key — identity, and never the label.
      label: The item's name as a person would read it.
      name: The outcome, one of ``MEMBERS``.
      reason: The reason code, where the outcome has one.

    Returns:
      The record, carrying ``reason`` only when there is one.

    Raises:
      ValueError: If the outcome is not a member of the closed set. A record nothing can word is a
        notification the user never receives, so an unknown one fails here rather than arriving at
        the notifier as silence.
    """
    if name not in MEMBERS:
        raise ValueError(f"{name!r} is not a file-ops outcome")
    record = {"itemKey": item_key, "label": label, "outcome": name}
    if reason is not None:
        record["reason"] = reason
    return record
