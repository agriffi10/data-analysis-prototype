"""The per-item outcome vocabulary every file-ops verb reads and extends.

An operation on a selection is not one result. Three of the selected items copy, one collides, one
names a folder the portal manages — and that has to survive from the first verb to the notification,
which is where the user learns what happened to the selection. So each selected item carries a
record, created here and CARRIED FORWARD by every later verb rather than re-created.

**The record shape is fixed by the expansion spec and adopted here rather than invented**, because
this is the first producer and a different shape now would force every later verb and test to be
rewritten. ``itemKey`` is identity and ``label`` is display; they are never swapped.

**Three members ship with the first verb and four with the expansion, and ``refused`` is the one
the expansion's own enumeration does not name.** It exists because ``protected`` means *a protected
location*, and folding an into-itself refusal into it would destroy the distinct-reason signal the
whole per-refusal reason-code rule exists to preserve.

**THREE VERBS PRODUCE OUTCOMES AND NONE OF THEM CREATES THE LIST.** validate-authorize decides the
protected locations and the no-ops, the expansion adds an entry for every item it expanded, and the
destination guard turns some of those into conflicts. Each one takes the list it was given and
returns the COMPLETE list — which is what ``carry_forward`` below is for. Wired the obvious way, a
verb's result replaces the path it is merged into rather than appending to it, so the guard would
silently drop the two producers before it, and those are exactly the per-item outcomes the model
exists to carry.

Attributes:
  NOOP: The derived destination is the source. Reported as a success that did nothing, matching
    the browser, which treats a same-key move as a no-op rather than an error.
  PROTECTED: The item names one of the portal's own folders, or would land on one. Carries the
    rule's own reason code.
  REFUSED: The item cannot be operated on for a reason about the request itself — today, a
    destination inside the item's own subtree.
  CLEARED: The item expanded and nothing stands in its way. Provisional when the expansion writes
    it: the destination guard may still turn it into a conflict.
  CONFLICT: Something already occupies a key this item would write. Carries a bounded sample.
  SOURCE_MISSING: A selected FILE is no longer there. Per item rather than whole-request: the rest
    of the selection is still exactly what the user asked for.
  SOURCE_EMPTY: The item resolved to no objects at all. Deliberately not a success — on a plane,
    "nothing happened" must be distinguishable from "it worked".
  MOVED: Terminal success for a ``move`` — copied, and the source removed.
  COPIED: Terminal success for a ``copy``.
  DELETED: Terminal success for a ``delete``.
  COPY_FAILED: At least one of the item's objects did not copy. The source is untouched, which is
    the safe direction and the reason no rollback exists.
  DUPLICATE: The item COPIED but its source was not removed, so the user now holds the data in two
    places. A state no earlier code describes and one they must be told about — it is not a
    success, and it is not a failure that changed nothing.
  DELETE_FAILED: A ``delete`` whose objects were not removed. Deliberately NOT ``DUPLICATE``:
    nothing was copied, so "you have it twice" would be a false sentence, and ``COPY_FAILED`` names
    a copy that never happened. One state, one code — the rule that put ``source_changed`` and
    ``source_delete_failed`` on ``DUPLICATE`` as REASONS is the same rule that forces this to be an
    outcome of its own.
  TERMINALS: The outcomes a run may END on. Every one of them is a statement about what happened
    to the user's data.
  GATE_VERDICTS: The outcomes that mean "this item has been decided, but not yet acted on".
    **None of them may reach a terminal** — ``cleared`` means "may proceed", and an item still
    wearing it when the machine finishes is indistinguishable from "moved successfully" to the
    producer that words the notification.
  MEMBERS: Every outcome this plane may carry. Closed and asserted, because an outcome nothing can
    word is a notification the user never gets.

**A WHOLE-REQUEST TERMINAL IS REACHABLE ONLY FROM A CAUSE THAT IS A PROPERTY OF THE REQUEST, NEVER
OF AN ITEM.** Stated as the rule rather than as a list of causes: they are spread across the
containment checks, the lock give-up, the overlapping-item refusal, the supersession guards and
every cap, and an enumeration here is wrong on the day someone adds the next one. What follows from
it is that no member of the vocabulary above may ever appear as the reason on a failure seed — a
per-item outcome is by construction not a statement about the request.
"""

from dataclasses import dataclass

NOOP = "noop"
PROTECTED = "protected"
REFUSED = "refused"
CLEARED = "cleared"
CONFLICT = "conflict"
SOURCE_MISSING = "source_missing"
SOURCE_EMPTY = "source_empty"

MOVED = "moved"
COPIED = "copied"
DELETED = "deleted"
COPY_FAILED = "copy_failed"
DUPLICATE = "duplicate"
DELETE_FAILED = "delete_failed"

GATE_VERDICTS = frozenset({CLEARED})

TERMINALS = frozenset(
    {
        NOOP,
        PROTECTED,
        REFUSED,
        CONFLICT,
        SOURCE_MISSING,
        SOURCE_EMPTY,
        MOVED,
        COPIED,
        DELETED,
        COPY_FAILED,
        DUPLICATE,
        DELETE_FAILED,
    }
)

MEMBERS = GATE_VERDICTS | TERMINALS

#: What a still-``cleared`` item becomes when its operation committed. The finaliser reads this
#: rather than branching, so "every operation has a terminal success" is a property of the table.
TERMINAL_SUCCESS = {"move": MOVED, "copy": COPIED, "delete": DELETED}

__all__ = [
    "CLEARED",
    "CONFLICT",
    "COPIED",
    "COPY_FAILED",
    "DELETED",
    "DELETE_FAILED",
    "DUPLICATE",
    "GATE_VERDICTS",
    "MEMBERS",
    "MOVED",
    "NOOP",
    "PROTECTED",
    "REFUSED",
    "SOURCE_EMPTY",
    "SOURCE_MISSING",
    "TERMINALS",
    "TERMINAL_SUCCESS",
    "Refusal",
    "carry_forward",
    "decided_keys",
    "outcome",
]


@dataclass(frozen=True)
class Refusal:
    """One protected-location rule's answer: why, and what to say about it.

    A returned value rather than a raised error, because a source refusal is PER ITEM — a protected
    item fails alone and every other item proceeds, which is why ``undeletableSelectionRefusal``
    disables Delete and Move only when every selected item is an undeletable root folder. A
    whole-request refusal would turn a select-all delete at a space root, which deletes what it may
    and reports the rest, into one that deletes nothing. The destination rule answers with the same
    value, and validate-authorize raises it as a whole-request terminal, because a request has one
    destination.

    Attributes:
      reason: The stable reason code, distinct per rule so the notifier can word it without
        re-deriving which rule fired.
      detail: Operator text naming the folder. Never rendered to a user.
    """

    reason: str
    detail: str


def outcome(item_key: str, label: str, name: str, reason: str | None = None, **extra) -> dict:
    """Builds one item's outcome record.

    Args:
      item_key: The selected item's key — identity, and never the label.
      label: The item's name as a person would read it.
      name: The outcome, one of ``MEMBERS``.
      reason: The reason code, where the outcome has one.
      **extra: Fields an outcome of this kind carries beyond the four every record has — today the
        conflict's ``sample`` and its ``more`` flag. Taken here rather than merged by the caller so
        that every record on the state is built by one function, which is what makes the shape
        assertable at all. These are DATA for the producer that words the notification, never
        message markers: the resolver substitutes by ``str.replace``, so a list reaching one would
        raise at the one moment a sentence is being composed to report a failure.

    Returns:
      The record, carrying ``reason`` and any extras only when there are some.

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
    record.update({field: value for field, value in extra.items() if value is not None})
    return record


def decided_keys(existing: list | None) -> set:
    """Returns the item keys an earlier verb has already decided.

    The expansion reads this to know which items it must NOT see. A same-key no-op is the case that
    matters: its destination subtree IS its source subtree, so expanding it would have the guard
    report every one of its own objects as a conflict and flip a success into a refusal.

    Args:
      existing: The outcome list as it arrived, which may be absent.

    Returns:
      The set of decided item keys.

    Raises:
      None.
    """
    return {
        record["itemKey"]
        for record in (existing or [])
        if isinstance(record, dict) and isinstance(record.get("itemKey"), str)
    }


def carry_forward(existing: list | None, decided: list | None) -> list:
    """Returns the COMPLETE outcome list: what arrived, updated by what this verb decided.

    **A verb's result replaces the path it is merged into; it does not append.** So a verb that
    returned only its own records would drop every earlier producer's, which are exactly the
    per-item outcomes that have to reach the notification. Each verb therefore takes the list as
    input and returns all of it.

    An entry whose key is already present is REPLACED in place, preserving the order the first
    producer set — the guard turning a provisional ``cleared`` into a ``conflict`` is that case, and
    it must not move the item to the end of a list a person reads.

    Args:
      existing: The outcome list as it arrived.
      decided: The records this verb decided, which may repeat keys already present.

    Returns:
      One record per item key, in arrival order, with later decisions winning.

    Raises:
      None.
    """
    merged = list(existing or [])
    index = {
        record["itemKey"]: position
        for position, record in enumerate(merged)
        if isinstance(record, dict) and isinstance(record.get("itemKey"), str)
    }
    for record in decided or []:
        position = index.get(record["itemKey"])
        if position is None:
            index[record["itemKey"]] = len(merged)
            merged.append(record)
        else:
            merged[position] = record
    return merged
