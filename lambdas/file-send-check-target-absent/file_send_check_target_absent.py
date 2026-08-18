"""check-target-absent — the per-recipient conflict guard.

For ONE recipient: short-circuits a recipient validate-authorize could not resolve, works out
where their inbox is, and refuses the recipient if any selected item name is already taken
there. Read-only — it decides whether a copy may start, and never starts one.

**A send never overwrites, and this is where that is enforced.** The destination layout keys by
item NAME, so a second send of ``notes.txt`` collides where a first send of
``reports/`` to the same recipient does not. Refusing rather than merging is the recorded
behaviour: a merge would leave a recipient's folder holding two sends' worth of files with no
way to tell which arrived when, and an overwrite would destroy data this plane holds no delete
right over.

**An expected refusal is a RETURN VALUE, not an exception, and that is the one place this verb
departs from table-share's guard.** A conflict has to name the colliding item so the sender can
be told which file was already there (FR-001 AC5) — and a raised ``TerminalError`` cannot carry
it: its tokens are deliberately kept out of the exception message, and its detail is operator
text that may quote raw service output and must never be rendered to a user. Parsing
a filename back out of a Step Functions ``Cause`` would be both fragile and a rule break. So the
two refusals this verb EXPECTS — an unresolved recipient and a name conflict — come back as a
uniform record with a reason and a detail field, and the Map item's ``Catch`` is left for what
it is actually good at: the faults nobody predicted.

**The refusal is per RECIPIENT, never per request.** One person already holding ``notes.txt``
must not cost everybody else the send. The whole-request failures on this plane happen upstream,
before any recipient runs.

It notifies nobody, and that is deliberate rather than an omission. Every per-recipient outcome
on this plane — this refusal included — is told to the sender ONCE, by the producer
reading the terminal summary. Table-share notifies from its own guard verb because it has no
such producer; reproducing that here would send two messages about one conflict.

The service name is the control plane, not the function, so one send's invocations and its Map
fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import observability
from cpcommon.errors import TerminalError
from fscommon import authz, inbox, paths

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="file-send")

CONFLICT = "conflict"


def _item_names(source: dict) -> list:
    """Reads the names the selection would create in a recipient's inbox.

    Order is the SELECTION's, not sorted: when several names collide, the one reported is the
    first the sender picked, which is the one they will look for.

    Args:
      source: The authorized source, carrying the normalised items.

    Returns:
      The item names, in selection order.

    Raises:
      TerminalError: ``no_items`` when the selection reaches here empty, and ``forbidden`` when
        an item key has no final segment.

        **The empty case fails CLOSED, and that is not defensive padding.** A guard with no
        names to check finds no collisions, so it would clear every recipient and report ``ok``
        over an inbox that already holds the send — the one answer this verb must never give.
        The selection cannot be empty through validate-authorize, which refuses it outright; it
        can be empty if the Map's ``ItemSelector`` stops threading the source, which is a
        wiring fault whose only other trace would be ``items: 0`` in a span nobody reads.
    """
    items = source.get("items") or []
    if not items:
        raise TerminalError(
            "no_items", "the guard was handed no selection, so it has nothing to check"
        )
    return [paths.item_name(item["key"]) for item in items]


def _outcome(recipient: dict, status: str, reason: str = "", detail: str = "") -> dict:
    """Shapes one recipient's guard record.

    Every field is always present. The Map's records are read by ASL Pass states downstream, and
    a Pass referencing an absent path raises an uncatchable ``States.Runtime`` — so a sparse
    record would kill the execution on exactly the refusal it was recording.

    Args:
      recipient: The recipient, resolved on the clear path and as-annotated on a refusal.
      status: ``ok`` or ``failed``.
      reason: The refusal's stable code, empty when clear.
      detail: The colliding item name for a conflict, empty otherwise. USER-FACING — the
        sender's own item name, never service text.

    Returns:
      The record.

    Raises:
      None.
    """
    return {"status": status, "recipient": recipient, "reason": reason, "detail": detail}


@observability.traced("check-target-absent")
def handler(event, context) -> dict:
    """Guard-Map entry point: confirms nothing this recipient holds would be overwritten.

    No ``@notifies_on_failure``: see the module docstring — a per-recipient outcome is notified
    once, from the terminal summary, and a decorator emit here would be the second message.

    Args:
      event: The Map item, carrying the recipient and the whole request.
      context: The Lambda context, unused.

    Returns:
      The recipient's guard record: cleared, or refused with a reason.

    Raises:
      TransientError: On a listing fault — a guard that cannot see the destination retries and
        then fails its own Map item, and never falls through to "nothing is there", which is the
        one answer that ends in an overwrite.
      TerminalError: ``no_items`` when the selection arrived empty, or ``forbidden`` for a
        recipient kind the resolver does not know or an item with no name. None of the three
        reaches here through validate-authorize; each fails the item rather than guessing.
    """
    return _check_target_absent(event)


def _check_target_absent(event) -> dict:
    """Short-circuits an unresolved recipient, resolves the inbox, and checks every item name.

    The unresolved case costs NO S3 call, which is the point of annotating upstream rather than
    failing there: a send to five recipients where two do not exist should not list two inboxes
    that do not exist either.

    Args:
      event: The Map item.

    Returns:
      The guard record. On the clear path the recipient carries the destination bucket and root,
      so the manifest builder resolves a destination once per recipient rather than once per
      object.

    Raises:
      TransientError: On a listing fault.
      TerminalError: ``no_items``, or ``forbidden`` from the resolver or the item namer.
    """
    recipient = event.get("recipient") or {}
    request = event.get("request") or {}
    kind, name = recipient.get("kind"), recipient.get("name")

    invalid = recipient.get("invalid")
    if invalid:
        logger.info("recipient %s:%s was not resolvable (%s)", kind, name, invalid)
        observability.info(
            "recipient unresolved",
            recipient=name,
            recipient_kind=kind,
            reason=invalid,
            outcome="refused",
        )
        return _outcome(recipient, "failed", invalid)

    sender = (request.get("actor") or {}).get("username") or ""
    location = authz.recipient_location(kind, name)
    names = _item_names(request.get("source") or {})

    taken = inbox.existing_item_names(location["bucket"], location["root"], sender)
    collisions = [item for item in names if item in taken]
    if collisions:
        logger.info(
            "conflict for %s:%s — %d name(s) already in the inbox", kind, name, len(collisions)
        )
        observability.info(
            "recipient conflict",
            recipient=name,
            recipient_kind=kind,
            reason=CONFLICT,
            outcome="refused",
            conflicts=len(collisions),
            exists=True,
        )
        return _outcome(recipient, "failed", CONFLICT, collisions[0])

    resolved = {**recipient, "destBucket": location["bucket"], "destRoot": location["root"]}
    logger.info("target clear for %s:%s — %s/%s", kind, name, location["bucket"], location["root"])
    observability.info(
        "target absent",
        recipient=name,
        recipient_kind=kind,
        dest_bucket=location["bucket"],
        dest_root=location["root"],
        items=len(names),
        exists=False,
    )
    return _outcome(resolved, "ok")
