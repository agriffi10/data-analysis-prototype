"""A declared byte bound for every caller-controlled field on an enqueue request.

A request travels four representations, each capped by Step Functions at 256 KiB, and the chain
cannot be measured while its inputs are unbounded. Most of them were: ``requestId`` was declared
``str`` on every enqueue route and spread onto the wire verbatim, data-quality's ``location`` and
shared-spaces' ``space`` were caller strings nothing bounded anywhere, and both reach a
``RecordFailure`` — a ``Pass`` with no ``Catch``, where a breach raises ``States.DataLimitExceeded``
outside anything that could notify the user their request failed.

**The bound is declared on the CONTRACT, and that is the only place the population is derivable.**
A state-machine template cannot tell a caller's value from a stamped one: archive's
``RecordFailure`` reads ``$.mode``, which looks exactly like ``$.location`` and is written by the
sender. Resolving those needs data flow across ASL and eight verbs. Reading the contract needs
neither — every declared string or list field on an enqueue request either carries a bound here or
is a finding — and that is strictly stronger, because it catches a field before any template names
it.

**A bound says which question its number answers, and three of them look alike as integers.** Most
are SERIALIZED JSON bytes, because that is what ``enqueue.build_message`` puts on the wire, escaping
and all, and it is the quantity the plane selection caps already measure. A key's bound is in the
UTF-8 bytes of the value itself, because that is the unit S3 states its own limit in — measured on
the serialized form instead, a 171-character accented path is refused at a third of what S3 allows,
which is a new refusal wearing a measurement's clothes. And a recipient or member cap is a COUNT.
An earlier draft had one field for all three, and spent a count of fifty recipients as fifty bytes:
the worst case it built carried one recipient, understating the model the fleet cap is derived from
by seven and a half kilobytes.

**Every declared path carries its OWN bound, and a container carries one too.** ``source.items``
has a byte bound and so does ``source.items[].key``, because the two answer different questions:
one is how much selection may travel, the other is how long a single key may be. An earlier draft
let a leaf inherit its container's number, which is TRUE as a validation rule — a key cannot exceed
the list holding it — and useless as a construction rule: the worst case built from it was a single
partition key of forty kilobytes, and the guard meant to catch a field pinned small was satisfied
by one pinned absurdly large. ``bound_for`` still resolves outwards, so an inherited bound is a
backstop; the guard requires the exact path.

Attributes:
  MAX_REQUEST_ID_BYTES: What a caller's own request id may serialize to. Its budget is
    ``cpcommon.config.MAX_FIFO_KEY_CHARS``: nine of the eleven routes make the id the SQS
    ``MessageDeduplicationId`` verbatim, and ``fifo._checked`` refuses a derived key over that
    length — after the body is assembled. This is the CHAIN's bound on the same field and does not
    supersede that one; it is set at the worst escaping the queue's own character class permits, so
    it refuses no id ``_checked`` would accept.
  MAX_IDENTIFIER_BYTES: What a catalog-safe name may serialize to. Usernames, space names,
    databases and tables answer to ``CATALOG_IDENTIFIER_RE``, three to sixty-three characters of
    a lowercase alphabet, and partition-key names to ``PARTITION_KEY_NAME_RE``, one to
    sixty-three of the same — **none of which escapes**, so the serialized form is the name plus
    its quotes rather than twice it. Both rules share the ceiling, so one bound serves both.
  MAX_S3_KEY_BYTES: How long an object or folder key may be, in the UTF-8 bytes S3 counts. Not a
    serialized length: a key of accented characters serializes to three times its own size, and a
    bound stated on the serialized form would refuse a third of what S3 permits.
  MAX_BUCKET_NAME_BYTES: What a bucket name may serialize to. S3's own maximum, and its character
    class escapes nothing.
  MAX_TIMESTAMP_BYTES: What an ISO-8601 instant may serialize to. Its character class escapes
    nothing either.
  MAX_PARTITION_KEYS_BYTES: What a declared partition-key list may serialize to. It mirrors
    ``tbcommon.config.REFRESH_MAX_DEFINITION_BYTES``, the plane's own budget for a table definition
    on the state, because the declared keys become part of that definition. Mirrored rather than
    imported for the reason ``Bound.owner`` gives, and a guard holds the two equal.
  MAX_PARTITION_VALUE_BYTES: How long one projected partition value may be, in the UTF-8 bytes S3
    counts. A value becomes a segment of the table's own S3 path, so S3's key-segment budget sizes
    it — and it is measured in the same unit as ``MAX_S3_KEY_BYTES``, which cites the same budget.
  MAX_PARTITION_VALUES_BYTES: What one key's enumerated values may serialize to together. **A
    share of the definition budget rather than a derivation of it** — nothing in the plane says
    how many projected keys a table may declare, so a quarter is a choice, and it is written down
    as one. What actually binds is the ``partitionKeys`` bound above, which IS derived; this only
    stops a single key from spending the whole definition on its own enum.
  MAX_MEMBERS_PER_REQUEST: How many members one shared-space request may name — a COUNT, because
    a byte bound cannot express one: at the shortest legal username a twelve-kilobyte allowance
    admits two thousand names. **It mirrors the fleet's existing derivation rather than adding a
    second**, ``transfer_reader.MAX_MEMBERS_PER_MESSAGE``, which charges the add-members verb's
    timeout for the per-member round trips AND the per-roster-member fan-out this one first
    dropped. Two answers to one question, differing by more than twice, would have let the API
    admit a request the operator path already refuses as unable to finish. A guard holds them
    equal.
  MAX_COLUMN_INDEXES_PER_REQUEST: How many result columns one conversion may choose — a COUNT,
    like the member cap and for the same reason: the values are small integers, and a byte
    budget over them would say nothing about how many there are. Its budget is
    ``rccommon.config.MAX_RESULT_COLUMNS``, the widest result this plane converts in any format:
    a request cannot choose more columns than the result it is chosen from may have, so the two
    are one number and a guard holds them equal. Mirrored rather than imported, for the reason
    ``Bound.owner`` gives. It is an ``api`` bound rather than a ``verb`` one because the list is
    the field that makes the chain's worst case unmeasurable while it is unbounded, and that has
    to be settled before the message is built.
  FIELD_BOUNDS: Every declared bound, one per (route, path).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from cpcommon.config import MAX_FIFO_KEY_CHARS

from .contract import EnqueueRoute, Route


def _escaped(characters: int) -> int:
    """The serialized size of a string whose every character escapes to two bytes.

    The worst expansion ``json.dumps`` produces for printable ASCII: a quote or a backslash costs
    two bytes where an ordinary character costs one. Used where allowing that expansion is cheap.

    Args:
      characters: How many characters the value may carry.

    Returns:
      The serialized byte length, quotes included.

    Raises:
      None.
    """
    return 2 * characters + 2


def _plain(byte_length: int) -> int:
    """The serialized size of a string that escapes to nothing.

    Used where the value's own budget is already a byte length and allowing the escaped worst case
    would multiply the fleet cap: an S3 key of control characters serializes to six bytes a
    character, and a bound set there would cost the chain six kilobytes for a case no real key
    reaches. A value that does escape costs its real size and is refused earlier, which is what the
    three plane selection caps already do.

    Args:
      byte_length: The value's own byte budget.

    Returns:
      The serialized byte length, quotes included.

    Raises:
      None.
    """
    return byte_length + 2


MAX_REQUEST_ID_BYTES: Final[int] = _escaped(MAX_FIFO_KEY_CHARS)
MAX_IDENTIFIER_BYTES: Final[int] = _plain(63)
MAX_S3_KEY_BYTES: Final[int] = 1024
MAX_BUCKET_NAME_BYTES: Final[int] = _plain(63)
MAX_TIMESTAMP_BYTES: Final[int] = _plain(32)
MAX_MEMBERS_PER_REQUEST: Final[int] = 44
MAX_COLUMN_INDEXES_PER_REQUEST: Final[int] = 1_500
MAX_PARTITION_KEYS_BYTES: Final[int] = 40 * 1024
MAX_PARTITION_VALUE_BYTES: Final[int] = 255
MAX_PARTITION_VALUES_BYTES: Final[int] = MAX_PARTITION_KEYS_BYTES // 4


@dataclass(frozen=True)
class Bound:
    """One declared byte bound on one caller-controlled field.

    Attributes:
      route_id: The enqueue route the bound applies to.
      path: The field, as a dotted path from the body's root. A bound on a container covers every
        field beneath it.
      max_bytes: The bound's number, in the unit ``measured`` names. For a bound this service
        applies.
        ``None`` for a ``verb`` bound, whose number lives in the plane that enforces it — copying
        it here would be the same rule written twice, in two languages, with nothing holding the
        copies together.
      measured: WHICH QUESTION the number answers, because three different ones look alike as
        integers and an earlier draft spent a count as though it were a byte budget. ``wire`` is
        serialized JSON bytes, what the sender puts on the queue. ``value`` is the UTF-8 bytes of
        the string itself, which is the unit S3 states its key limit in — bounding a key on its
        serialized form instead refuses a 171-character accented path, a third of what S3 allows.
        ``items`` is a list's element count, which is what the recipient and member caps are.
      enforced_at: Where the bound is applied. An ``api`` bound is checked before the message is
        built and therefore bounds every link of the chain; a ``verb`` bound is applied inside
        ``validate-authorize`` and so bounds only what a failure state can carry, never what the
        Pipe has to start an execution with. The two are not interchangeable and the distinction is
        recorded rather than inferred.
      owner: Where a ``verb`` bound's number lives, as ``module.CONSTANT``. Empty for an ``api``
        bound. **Named rather than imported, and the reason is a boundary rather than a crash**:
        this service does not depend on the plane layers, which is why ``protected`` and ``spaces``
        each carry their own implementation of a rule ``focommon`` also has. Importing six domain
        configs to read six integers would reverse that for values this service never applies.
        (It would not fail — every plane ``config`` imports cleanly with no environment, because
        the env-backed ones resolve on first read. An earlier draft of this docstring said
        otherwise and was wrong.)
      budget: What sized the number. Never a round figure — the sentence names the quota, rule or
        measurement the bound is derived from, so a later reader can re-derive it rather than
        trust it.
    """

    route_id: str
    path: str
    max_bytes: int | None
    enforced_at: Literal["api", "verb"]
    budget: str
    owner: str = ""
    measured: Literal["wire", "value", "items"] = "wire"


FIELD_BOUNDS: Final[tuple[Bound, ...]] = (
    Bound(
        "sharedSpace.enqueue", "requestId", MAX_REQUEST_ID_BYTES, "api",
        "the FIFO deduplication key this id becomes verbatim, at the worst escaping its character class permits",
    ),
    Bound(
        "sharedSpace.enqueue", "space", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule a creatable space name already answers to",
    ),
    Bound(
        "sharedSpace.enqueue", "payload.members", MAX_MEMBERS_PER_REQUEST, "api",
        "the fleet's existing derivation of what add-members finishes inside its timeout",
        "",
        "items",
    ),
    Bound(
        "sharedSpace.enqueue", "payload.members[]", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule every username answers to",
    ),
    Bound(
        "sharedSpace.enqueue", "payload.newOwner", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule every username answers to",
    ),
    Bound(
        "notifications.enqueue", "id", MAX_IDENTIFIER_BYTES, "api",
        "the notification id shape the browser and the writer share, which is inside the catalog rule's length",
    ),
    *(
        bound
        for route_id in ("tableBuild.create", "tableBuild.refresh")
        for bound in (
            Bound(
                route_id, "requestId", MAX_REQUEST_ID_BYTES, "api",
                "the FIFO deduplication key this id becomes verbatim, at the worst escaping its character class permits",
            ),
            Bound(
                route_id, "space.bucket", MAX_BUCKET_NAME_BYTES, "api",
                "S3's own maximum bucket name length",
            ),
            Bound(
                route_id, "space.prefix", MAX_S3_KEY_BYTES, "api",
                "S3's own maximum key length, which a space prefix is a prefix of",
                measured="value",
            ),
            Bound(
                route_id, "space.database", MAX_IDENTIFIER_BYTES, "api",
                "the catalog identifier rule every database name answers to",
            ),
            Bound(
                route_id, "tableName", None, "verb",
                "the catalog identifier rule, already applied inside validate-authorize",
                "cpcommon.config.CATALOG_IDENTIFIER_RE",
            ),
            Bound(
                route_id, "partitionKeys", MAX_PARTITION_KEYS_BYTES, "api",
                "the plane's own budget for a table definition on the state, which the declared keys become part of",
            ),
            Bound(
                route_id, "partitionKeys[].name", MAX_IDENTIFIER_BYTES, "api",
                "the partition-key name rule the plane checks every key name against, whose ceiling is the catalog identifier rule's",
            ),
            Bound(
                route_id, "partitionKeys[].range", 2 + 2 * (MAX_IDENTIFIER_BYTES + 1), "api",
                "the two projection bounds a range declares, each a number or a date in the declared format",
            ),
            Bound(
                route_id, "partitionKeys[].range[]", MAX_IDENTIFIER_BYTES, "api",
                "one projection bound, a number or a date in the declared format",
            ),
            Bound(
                route_id, "partitionKeys[].format", MAX_IDENTIFIER_BYTES, "api",
                "a date format string, which is shorter than the names it formats values for",
            ),
            Bound(
                route_id, "partitionKeys[].values", MAX_PARTITION_VALUES_BYTES, "api",
                "a quarter of the plane's definition budget, so several projected keys still fit one definition",
            ),
            Bound(
                route_id, "partitionKeys[].values[]", MAX_PARTITION_VALUE_BYTES, "api",
                "S3's key-segment budget, which a projected partition value becomes",
                "",
                "value",
            ),
            Bound(
                route_id, "partitionKeys[].intervalUnit", MAX_IDENTIFIER_BYTES, "api",
                "a projection interval unit, one word from Athena's own closed set",
            ),
        )
    ),
    Bound(
        "tableShare.enqueue", "source.database", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule every database name answers to",
    ),
    Bound(
        "tableShare.enqueue", "source.table", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule every table name answers to",
    ),
    Bound(
        "tableShare.enqueue", "tableName", None, "verb",
        "the catalog identifier rule, already applied inside validate-authorize",
        "cpcommon.config.CATALOG_IDENTIFIER_RE",
    ),
    Bound(
        "tableShare.enqueue", "recipients", None, "verb",
        "the plane's own recipient count cap, whose per-recipient name this service bounds",
        "tscommon.config.SHARE_MAX_RECIPIENTS",
        "items",
    ),
    Bound(
        "tableShare.enqueue", "recipients[].name", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule every username and space name answers to",
    ),
    Bound(
        "dataQuality.enqueue", "requestId", MAX_REQUEST_ID_BYTES, "api",
        "the FIFO deduplication key this id becomes verbatim, at the worst escaping its character class permits",
    ),
    Bound(
        "dataQuality.enqueue", "space.bucket", MAX_BUCKET_NAME_BYTES, "api",
        "S3's own maximum bucket name length",
    ),
    Bound(
        "dataQuality.enqueue", "space.prefix", MAX_S3_KEY_BYTES, "api",
        "S3's own maximum key length, which a space prefix is a prefix of",
        measured="value",
    ),
    Bound(
        "dataQuality.enqueue", "location", MAX_S3_KEY_BYTES, "api",
        "S3's own maximum key length, which the folder being checked is",
        measured="value",
    ),
    Bound(
        "fileSend.enqueue", "requestId", MAX_REQUEST_ID_BYTES, "api",
        "the FIFO deduplication key this id becomes verbatim, at the worst escaping its character class permits",
    ),
    Bound(
        "fileSend.enqueue", "source.space.name", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule every space name answers to",
    ),
    Bound(
        "fileSend.enqueue", "source.items", None, "verb",
        "the plane's own serialized selection cap, applied where the selection is normalised",
        "fscommon.config.SEND_MAX_ITEM_BYTES",
    ),
    Bound(
        "fileSend.enqueue", "source.items[].key", MAX_S3_KEY_BYTES, "api",
        "S3's own maximum key length, which every selected item names",
        measured="value",
    ),
    Bound(
        "fileSend.enqueue", "recipients", None, "verb",
        "the plane's own recipient count cap, whose per-recipient name this service bounds",
        "fscommon.config.SEND_MAX_RECIPIENTS",
        "items",
    ),
    Bound(
        "fileSend.enqueue", "recipients[].name", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule every username and space name answers to",
    ),
    Bound(
        "archive.archive", "requestId", MAX_REQUEST_ID_BYTES, "api",
        "the FIFO deduplication key this id becomes verbatim, at the worst escaping its character class permits",
    ),
    Bound(
        "archive.archive", "source.space.name", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule every space name answers to",
    ),
    Bound(
        "archive.archive", "source.items", None, "verb",
        "the plane's own serialized selection cap, applied where the selection is normalised",
        "arcommon.config.ARCHIVE_MAX_ITEM_BYTES",
    ),
    Bound(
        "archive.archive", "source.items[].key", MAX_S3_KEY_BYTES, "api",
        "S3's own maximum key length, which every selected item names",
        measured="value",
    ),
    Bound(
        "archive.restore", "requestId", MAX_REQUEST_ID_BYTES, "api",
        "the FIFO deduplication key this id becomes verbatim, at the worst escaping its character class permits",
    ),
    Bound(
        "archive.restore", "space.name", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule every space name answers to",
    ),
    Bound(
        "archive.restore", "archiveId", MAX_REQUEST_ID_BYTES, "api",
        "the request id of the archive it names, which carries that field's own bound",
    ),
    Bound(
        "fileOps.enqueue", "requestId", MAX_REQUEST_ID_BYTES, "api",
        "the FIFO deduplication key this id becomes verbatim, at the worst escaping its character class permits",
    ),
    Bound(
        "fileOps.enqueue", "source.space.name", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule every space name answers to",
    ),
    Bound(
        "fileOps.enqueue", "source.items", None, "verb",
        "the plane's own serialized selection cap, applied where the selection is normalised",
        "focommon.config.FILE_OPS_MAX_SELECTION_BYTES",
    ),
    Bound(
        "fileOps.enqueue", "source.items[].key", MAX_S3_KEY_BYTES, "api",
        "S3's own maximum key length, which every selected item names",
        measured="value",
    ),
    Bound(
        "fileOps.enqueue", "source.items[].targetName", None, "verb",
        "the plane's own cap on a per-item destination name, which is S3's key-segment budget",
        "focommon.config.MAX_TARGET_NAME",
           "value",
    ),
    Bound(
        "fileOps.enqueue", "destination.space.name", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule every space name answers to",
    ),
    Bound(
        "fileOps.enqueue", "destination.prefix", MAX_S3_KEY_BYTES, "api",
        "S3's own maximum key length, which the destination folder is",
        measured="value",
    ),
    Bound(
        "fileOps.enqueue", "submittedAt", MAX_TIMESTAMP_BYTES, "api",
        "an ISO-8601 instant's own length",
    ),
    Bound(
        "resultsConversion.enqueue", "requestId", MAX_REQUEST_ID_BYTES, "api",
        "the FIFO deduplication key this id becomes verbatim, at the worst escaping its character class permits",
    ),
    Bound(
        "resultsConversion.enqueue", "queryExecutionId", MAX_IDENTIFIER_BYTES, "api",
        "an Athena execution id, which is a UUID and so inside the catalog rule's length",
    ),
    Bound(
        "resultsConversion.enqueue", "destination.space.name", MAX_IDENTIFIER_BYTES, "api",
        "the catalog identifier rule every space name answers to",
    ),
    Bound(
        "resultsConversion.enqueue", "destination.prefix", MAX_S3_KEY_BYTES, "api",
        "S3's own maximum key length, which the destination folder is",
        measured="value",
    ),
    Bound(
        "resultsConversion.enqueue", "destination.filename", None, "verb",
        "the plane's own file name cap, which is S3's key-segment budget",
        "rccommon.config.MAX_FILENAME_BYTES",
           "value",
    ),
    Bound(
        "resultsConversion.enqueue", "submittedAt", MAX_TIMESTAMP_BYTES, "api",
        "an ISO-8601 instant's own length",
    ),
    Bound(
        "resultsConversion.enqueue", "columnIndexes", MAX_COLUMN_INDEXES_PER_REQUEST, "api",
        "the widest result this plane converts, which is the most columns there can be to choose",
        "",
        "items",
    ),
)


def bound_for(route_id: str, path: str) -> Bound | None:
    """The bound covering one field, its own or its nearest bounded ancestor's.

    Every declared path carries its own bound, so this normally answers on the first candidate.
    Resolution still walks outwards afterwards, because a byte bound on a container really does
    bound every value inside it — a key cannot exceed the list holding it — and that backstop is
    what makes a newly declared field safe rather than unbounded until someone notices. The leaf
    wins where both exist, which is the narrower answer.

    Args:
      route_id: The enqueue route.
      path: The dotted field path, with ``[]`` for a list's element.

    Returns:
      The bound covering that field, or None if nothing does.

    Raises:
      None.
    """
    declared = {b.path: b for b in FIELD_BOUNDS if b.route_id == route_id}
    breaks = [index for index, character in enumerate(path) if character in ".[" and index > 0]
    for candidate in [path, *(path[:index] for index in reversed(breaks))]:
        if candidate in declared:
            return declared[candidate]
    return None


def _values(body: object, path: str) -> list[object]:
    """Every value a dotted path names in one body.

    A path crossing a list yields one value per element, because a bound applies to each of them
    rather than to the first.

    Args:
      body: The parsed request body.
      path: The dotted field path, with ``[]`` for a list's element.

    Returns:
      The values found, empty when the path is absent.

    Raises:
      None.
    """
    found: list[object] = [body]
    for step in path.replace("[]", ".[]").split("."):
        if not step:
            continue
        nxt: list[object] = []
        for value in found:
            if step == "[]":
                if isinstance(value, list):
                    nxt.extend(value)
            elif isinstance(value, Mapping) and step in value:
                nxt.append(value[step])
        found = nxt
    return found


def over_bound(route: Route, body: object) -> Bound | None:
    """The first bound this body breaches, if any.

    Runs after shape validation, so every value it sees is already the declared type. Only ``api``
    bounds are consulted: a ``verb`` bound is applied inside ``validate-authorize`` and says
    nothing about what the Pipe can start an execution with.

    An ``api`` bound carrying no number is skipped rather than raised on, and that is a fail-open
    this request path accepts because it cannot happen: the shape is a declaration defect, and
    ``test_a_verb_bound_says_where_its_number_lives_and_an_api_bound_carries_one`` refuses it at
    build time. Raising here would turn a table typo into a 500 on every request to that route.

    Args:
      route: The route the body was sent to.
      body: The validated request body.

    Returns:
      The breached bound, or None when the body is within every one of them.

    Raises:
      None.
    """
    if not isinstance(route, EnqueueRoute):
        return None
    for bound in FIELD_BOUNDS:
        if bound.route_id != route.id or bound.enforced_at != "api":
            continue
        if bound.max_bytes is None:
            continue
        for value in _values(body, bound.path):
            if _size(value, bound.measured) > bound.max_bytes:
                return bound
    return None


def _size(value: object, measured: str) -> int:
    """One value's size, in the unit a bound states its number in.

    Args:
      value: The value to measure.
      measured: Which question to answer — ``wire``, ``value`` or ``items``.

    Returns:
      The size, or zero where the value is the wrong shape for the unit, which shape validation
      has already refused.

    Raises:
      None.
    """
    if measured == "items":
        return len(value) if isinstance(value, list) else 0
    if measured == "value":
        return len(value.encode("utf-8")) if isinstance(value, str) else 0
    return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))
