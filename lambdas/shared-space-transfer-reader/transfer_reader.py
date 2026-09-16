"""shared-space transfer-reader: the operator's door into the shared-space membership verbs.

The UI cannot serve the cases where the person who should act is the person who is absent — an
owner who has already left, a contractor whose access should have ended on Friday, a
re-organisation moving ten people into a space whose owner is on leave. So an operator drops a
CSV in the admin bucket and this reads it on a schedule, putting requests on the **same queue**
the UI writes to. That reuse is the point: an operator-driven add and a user-driven one are the
same verb doing the same work, authorized by the same predicate, notifying the same people.

**It is not a verb and it runs under its own role**, which is the whole of what makes the boundary
on the other side mean anything. The plane trusts an operator message because the ``SenderId`` SQS
stamps on it names this role; sharing the orchestrator's role would make that comparison admit every
verb in the fleet, and would do it while every test stayed green.

It **imports no domain module**, deliberately. ``shared-space-common``'s configuration requires the
portal role ARN at import, and this function has no use for it — importing it would buy a
schema-version constant at the price of a cold-start crash on a variable nobody here reads, which is
the failure that once took this plane down for nine days. The image puts the package on
``/opt/python`` for every function, so what holds this open is the absent import and nothing else.
The three constants that must agree with the plane are therefore local copies, and a test pins
each to the shared one's.

The reader knows nothing about spaces. It does not read the registry, does not check that a space
exists or that a named member belongs to it, and holds no grant that would let it — every one of
those questions is the validator's, and answering them twice is how two authorities disagree. Its
per-row checks are **syntactic only**, and the one that is not obviously so earns its place because
the verbs disagree about case: ``normalize_members`` lowercases, so ``Alice`` in an add row silently
becomes ``alice``, while ``transfer_refusal`` compares verbatim, so ``Alice`` in a transfer row
refuses as "not a member". One spelling, two behaviours, neither visible to the operator.

**A replay is safe by the verbs' idempotency, not by deduplication, and it has two residuals.**
The schedule fires hourly and the FIFO deduplication window is five minutes, so no two sweeps ever
fall inside one window. A re-add of a current member is skipped, a re-removal of an absent member
is skipped and a re-transfer to the current owner is refused. What that does not cover is a change
somebody made in between: a replayed ``remove`` removes a member who was legitimately re-added, and
a replayed ``add`` **re-grants** access to someone the owner removed. The second is the worse one
and is why both are written here. Recorded, not solved — the fix is a request ledger the plane does
not have.

**A removal does not revoke a live session.** The principal tag is stamped when credentials are
vended, nothing in the fleet revokes a token, and the pool client sets no token validity — so the ID
token's Cognito default of one hour is the window, plus the life of any presigned URL already
minted. Revocation is exactly what this door is for, so an operator must not believe Friday's row
took effect on Friday.

Attributes:
  INBOX: The prefix an operator writes to. It has no expiry rule, because a file this function has
    not managed to process must not be deleted out from under it.
  PROCESSED: Where a file goes once its rows are enqueued.
  REJECTED: Where a file goes when it cannot be parsed, beside a sibling naming the reason.
  HEADER: The only header row accepted, compared as an ORDERED list rather than as a set of
    expected names. A file whose columns are the right names in the wrong order parses perfectly
    and acts on every row against the wrong argument, and there is no later check that would
    catch it.
  RETIRED_HEADER: The header this file used to accept. Named so an operator who wrote yesterday's
    file is told what changed rather than getting the generic wrong-header sentence.
  ACTIONS: The operator's three words mapped to the actions the plane knows. The operator's
    vocabulary, not the wire's: a row names one person, so ``add_members`` reads wrong on it and
    somebody writing this file by hand should not have to know the wire. A test holds the mapping
    to ``config.OPERATOR_ACTIONS`` in both directions and holds it injective — set equality alone
    forces a word to exist for every admitted action and forces one to go when an action is
    withdrawn, but it collapses two words mapping to one action and agrees.
  TIMEOUT_SECONDS: The function's own ceiling, as Terraform sets it. The row cap is derived from it.
  SEND_BUDGET_FRACTION: The share of an invocation reserved for sending, leaving the rest for the
    listing, the reads, the copies and the deletes.
  SEND_MILLISECONDS: A conservative round trip for one ``SendMessage``, the same figure this plane's
    one-shot backfill sizes its own walk with.
  MAX_ROWS_PER_INVOCATION: The computed cap on rows READ in one run, and it separates two cases
    that look alike. A file larger than the WHOLE cap can never be processed by any tick, so it is
    refused with a reason telling the operator to split it — deferring it would leave it in an inbox
    that deliberately has no expiry, forever, behind a log line nobody is alerted on. A file larger
    than what is LEFT of this invocation's budget is deferred, and the sweep stops there rather than
    skipping it, because a later smaller file overtaking it would break the listing order that makes
    a sequence of operator files replayable. Neither is silent. Coalescing made this cap
    conservative — a file's sends are now at most its distinct ``(space, action)`` pairs — and that
    is deliberate rather than an oversight to be re-derived away: this function was never the
    expensive half, and a cap re-derived from a per-row PARSE cost would run to five figures, leave
    the over-cap rejection unreachable and bound nothing anyone cares about.
  ADD_MEMBERS_TIMEOUT_SECONDS: The add-members verb's EFFECTIVE timeout, and reading it has two
    traps that both ship green. The verb takes the module's ``lookup`` DEFAULT, because
    ``local.shared_space_function_timeouts`` carries one entry and ``add-members`` is not it — so a
    test parsing the map finds nothing and a test parsing the resource finds the ``lookup``
    expression rather than an integer. The test therefore reads the declared default AND asserts
    ``add-members`` has no override, so it reddens the day one is added.
  ADD_MEMBERS_BUDGET_FRACTION: The share of that verb's invocation this cap is allowed to plan for.
    The rest pays for a cold start at 128 MB, the registry read, and the compare-and-swap retries
    ``cpcommon.cas.MAX_ATTEMPTS`` allows.
  ROUND_TRIP_MILLISECONDS: One S3 or SQS round trip, the same conservative figure as
    ``SEND_MILLISECONDS``.
  POOL_ROUND_TRIP_MILLISECONDS: One Cognito admin call, taken at twice an S3 round trip because
    those calls are slower and account-rate-limited. Unmeasured, and deliberately pessimistic.
  PER_MEMBER_MILLISECONDS: What one requested member costs the verb — the pool lookup and the slot
    assignment, the membership index read and written under compare-and-swap, and one notification.
  PER_ROSTER_MEMBER_MILLISECONDS: What one member of the RESULTING roster costs, which is a cache
    document read and written under compare-and-swap. The fan-out is O(roster) rather than
    per-member, so a cost model without this term is too permissive for exactly the large space the
    cap exists to protect.
  REGISTRY_MILLISECONDS: The registry compare-and-swap, once per message.
  REFERENCE_ROSTER: The roster size the cap is sized against. There is no per-space roster cap
    anywhere in the product — ``MAX_SHARED_MEMBERSHIPS`` bounds spaces per USER — and this function
    holds no registry grant, so it cannot know the real number. **The residual is recorded rather
    than solved:** a space whose roster already exceeds this can exhaust the verb's budget for any
    number of added members, which is a pre-existing property of that verb rather than something
    this cap creates or fixes.
  MAX_MEMBERS_PER_MESSAGE: The computed cap on members in one message. What justifies it is the
    PARTIAL STATE a timed-out add leaves behind, not a lost notification: this machine declares no
    top-level ``TimeoutSeconds`` and ``AddMembers`` carries a ``States.ALL`` catch, so a verb that
    runs out of time is caught and reported — what it leaves is slots assigned, the registry
    unwritten and ``_release_slots`` never reached. **It is derived from the ADD verb's cost and
    applied to removals too**, which is conservative rather than an oversight: a removal does the
    same shape of work per member and the same O(roster) fan-out, minus the pool existence check.
    A transfer group is refused above one row long before this is consulted.
  MAX_SPACES_PER_FILE: How many distinct spaces one file may name. Not a resource budget and not
    computed — a blast-radius control. One file is one operator action, and without a ceiling it is
    up to the row cap's worth of grants across as many spaces, with no dual control, no approval and
    no outcome ledger. Chosen to cover a re-organisation affecting a department while stopping one
    mistake from reaching every space in the estate.
  MAX_ADD_ROWS_PER_FILE: How many ``add`` rows one file may carry, on the same reasoning and for the
    direction that grants rather than revokes. Chosen above any single legitimate operator action
    and well below what the row cap would otherwise allow.
    **Both ceilings bound a FILE, not a tick, and that is the honest limit of what they are.** One
    sweep processes every file in the inbox, so six files each sitting exactly on both ceilings
    grant six times either number in one tick, and nothing bounds it across ticks. Against a
    careless operator the per-file framing is the right one — one mistake is one file. Against the
    wider write set the register enumerates, who can upload ten files as easily as one, these are
    not a control at all, and the reader is the wrong place to build one: it holds no registry
    grant and no memory between ticks.
  MAX_FILE_BYTES: The size above which a file is refused WITHOUT being read, and the ceiling that
    is checked before every other one. The parse materialises the whole file — it must, to number
    lines and to see a duplicate row — and this function runs on 128 MB, so a CSV of a few
    megabytes exhausts it. That failure is not a refusal: it kills the invocation, so the file
    never reaches ``rejected/``, no reason is written, and it sits in a prefix with no expiry
    ahead of every later-named file in listing order, blocking them on every tick from then on —
    the same permanent wedge an unparseable file used to cause, reached through size instead of
    syntax. The row cap cannot prevent it, because the rows have to be parsed before they can be
    counted. Sized against that cap rather than against the runtime: 600 rows at a generous 200
    bytes each is 120 KB, so this leaves roughly eight times the headroom a legitimate file needs
    while staying an order of magnitude below the memory ceiling. The size comes from the listing,
    so the refusal costs no ``GetObject`` at all.
  DONE: A file that is out of the inbox — enqueued, or rejected.
  DEFERRED: A file this invocation had no budget left for, which stops the sweep.
  MESSAGE_GROUP_ID: The queue's single constant group, so operator and UI requests are started as
    one ordered stream rather than two. The runs still overlap, which ``_requests`` refuses to hide.
  SCHEMA_VERSION: The envelope version the validator accepts.
  REQUEST_NAMESPACE: The UUID namespace the per-request id is derived in.
"""

import csv
import io
import json
import logging
import uuid
from datetime import UTC, datetime

from cpcommon import clients, observability
from cpcommon import config as cpconfig

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")

INBOX = "operator-requests/inbox/"
PROCESSED = "operator-requests/processed/"
REJECTED = "operator-requests/rejected/"

HEADER = ["space", "action", "username"]
RETIRED_HEADER = ["space", "new_owner"]

ACTIONS = {
    "add": "add_members",
    "remove": "remove_members",
    "transfer": "transfer_ownership",
}

TIMEOUT_SECONDS = 60
SEND_BUDGET_FRACTION = 0.5
SEND_MILLISECONDS = 50
MAX_ROWS_PER_INVOCATION = int(TIMEOUT_SECONDS * SEND_BUDGET_FRACTION * 1000 / SEND_MILLISECONDS)

ADD_MEMBERS_TIMEOUT_SECONDS = 60
ADD_MEMBERS_BUDGET_FRACTION = 0.5
ROUND_TRIP_MILLISECONDS = 50
POOL_ROUND_TRIP_MILLISECONDS = 100
PER_MEMBER_MILLISECONDS = 2 * POOL_ROUND_TRIP_MILLISECONDS + 3 * ROUND_TRIP_MILLISECONDS
PER_ROSTER_MEMBER_MILLISECONDS = 2 * ROUND_TRIP_MILLISECONDS
REGISTRY_MILLISECONDS = 2 * ROUND_TRIP_MILLISECONDS
REFERENCE_ROSTER = 100
MAX_MEMBERS_PER_MESSAGE = int(
    (
        ADD_MEMBERS_TIMEOUT_SECONDS * ADD_MEMBERS_BUDGET_FRACTION * 1000
        - REGISTRY_MILLISECONDS
        - REFERENCE_ROSTER * PER_ROSTER_MEMBER_MILLISECONDS
    )
    / (PER_MEMBER_MILLISECONDS + PER_ROSTER_MEMBER_MILLISECONDS)
)

MAX_SPACES_PER_FILE = 25
MAX_ADD_ROWS_PER_FILE = 100

MAX_FILE_BYTES = 1_048_576

#: The two things a file can be after one pass, as constants rather than bare literals at five
#: call sites. A typo in one of those would compare unequal to "deferred" and fall through to the
#: skip — which is precisely the overtaking behaviour this function was corrected for, and it
#: would be silent.
DONE = "done"
DEFERRED = "deferred"

MESSAGE_GROUP_ID = "shared-space"
SCHEMA_VERSION = 1
REQUEST_NAMESPACE = uuid.UUID("2f6d1c7e-0b3a-4a6f-9d1e-7c5b2a8e4f13")


class RejectedFile(Exception):
    """A CSV this function will not act on. Its rows are enqueued neither wholly nor partly."""


def _queue_url():
    """Reads the shared-space request queue's URL.

    Read at call time rather than at import so a deploy that lands the code before the variable
    fails one invocation rather than every cold start.

    Args:
      None.

    Returns:
      The queue URL.

    Raises:
      ConfigError: When the variable is unset.
    """
    return cpconfig.require("SHARED_SPACE_REQUESTS_QUEUE_URL")


def _inbox_objects():
    """Lists the inbox in listing order, which is lexicographic by key.

    Args:
      None.

    Returns:
      ``(key, size)`` pairs, oldest-named first. The size rides along because refusing an
      oversized file has to happen before it is read, and the listing already knows it.

    Raises:
      ClientError: On any S3 fault.
    """
    s3 = clients.s3()
    keys, token = [], None
    while True:
        kwargs = {"Bucket": cpconfig.ADMIN_BUCKET, "Prefix": INBOX}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        keys.extend(
            # NOT `.get("Size", 0)`: a default of zero passes every file through the ceiling
            # below, which is the one direction this guard must never fail. S3 always sends it.
            (item["Key"], item["Size"])
            for item in page.get("Contents", [])
            if not item["Key"].endswith("/")
        )
        token = page.get("NextContinuationToken")
        if not token:
            break
    return keys


def _rows(body, key):
    """Parses one CSV into ``(line, space, word, username)`` rows, or refuses the whole file.

    Every check here is syntactic and every failure refuses the WHOLE file. Partial enqueueing is
    not an option this reader has: a file's rows go on the queue wholly or not at all, and mixing
    three actions in one file does not change that.

    The header is compared as an exact list rather than as a set of expected names, for the reason
    ``HEADER`` gives. The retired header gets its own sentence because an operator who wrote
    yesterday's file needs to be told what changed, not that their columns are wrong.

    **Lines are numbered by ``reader.line_num``, not by counting records.** A quoted field carrying
    a newline spans several physical lines and is one record, so an enumeration drifts from the
    operator's editor the moment one appears — and every refusal after it then names a line they
    cannot find, which is the one thing a message whose whole job is to be actionable must not do.
    It drifts on a skipped blank line too. What ``line_num`` gives for a record spanning several
    lines is its LAST one, which is the closest thing to a single number that is true of it.

    Args:
      body: The object's bytes.
      key: The object key, for the refusal message.

    Returns:
      The data rows, in file order.

    Raises:
      RejectedFile: On an unreadable file, a wrong header, a row that is not three non-empty
        fields, a word outside the accepted three, or a space or username that is not a
        catalog-safe identifier.
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RejectedFile(f"{key} is not UTF-8 text: {exc}") from exc

    # `newline=""` is the csv module's own requirement, and without it a file saved with lone-CR
    # endings raises `_csv.Error` instead of parsing. That error is the reason the whole parse is
    # wrapped below rather than only the header read.
    reader = csv.reader(io.StringIO(text.lstrip("\ufeff"), newline=""))
    try:
        header = next(reader)
    except StopIteration:
        raise RejectedFile(f"{key} is empty — it carries not even a header row") from None
    except csv.Error as exc:
        raise RejectedFile(f"{key} is not readable as CSV: {exc}") from exc

    columns = [column.strip() for column in header]
    if columns == RETIRED_HEADER:
        raise RejectedFile(
            f"{key} has the retired header {RETIRED_HEADER!r}. The header is now {HEADER!r}, and "
            f"`action` is one of {sorted(ACTIONS)!r} — one word per row, because a row names one "
            "person."
        )
    if columns != HEADER:
        raise RejectedFile(f"{key} has header {header!r}; the only header accepted is {HEADER!r}")

    rows = []
    # The iteration itself is guarded, not just the header: `csv` raises on a field over its own
    # size limit, which one unmatched quote in a large file produces. Uncaught, that escapes the
    # sweep — and the file it came from stays in an inbox with no expiry, ahead of every
    # later-named file in listing order, so one bad upload silences the door for good.
    try:
        # `reader.line_num` is read AFTER the iterator yields, so it is that record's last
        # physical line — the one the operator's editor shows for a row, multi-line or not.
        records = [(reader.line_num, row) for row in reader]
    except csv.Error as exc:
        raise RejectedFile(f"{key} is not readable as CSV: {exc}") from exc

    for number, row in records:
        # A row of empty FIELDS is not a blank line: `,,` and `"","",""` both parse to three empty
        # strings, and skipping them silently drops a row the operator wrote, with no line named
        # and no refusal. Only a truly empty record or a single whitespace-only field is skipped.
        if not row or (len(row) == 1 and not row[0].strip()):
            continue
        if len(row) != 3:
            raise RejectedFile(f"{key} line {number} has {len(row)} fields, not 3")
        space, word, username = (field.strip() for field in row)
        if not space or not word or not username:
            raise RejectedFile(f"{key} line {number} leaves a field blank")
        if word not in ACTIONS:
            raise RejectedFile(
                f"{key} line {number} asks for {word!r}; action must be one of {sorted(ACTIONS)!r}"
            )
        for field, value in (("space", space), ("username", username)):
            if not cpconfig.CATALOG_IDENTIFIER_RE.fullmatch(value):
                raise RejectedFile(
                    f"{key} line {number} has {field} {value!r}, which is not a valid name — "
                    "lowercase letters, digits and underscores, starting with a letter"
                )
        rows.append((number, space, word, username))
    return rows


def _requests(rows, key):
    """Coalesces a file's rows into one request per ``(space, action)``, or refuses the file.

    **One message per space and action, never one per member.** The Pipe is ``batch_size = 1`` and
    ``FIRE_AND_FORGET``, so N messages for one space are N overlapping executions, each a
    compare-and-swap against a single registry object whose contention the shared helper's
    docstring assumes is rare, and each dragging a full roster fan-out — so N single-member adds to
    one space cost O(N²) cache writes. The verbs already take a list; one message is one
    compare-and-swap and one fan-out.

    **One space appears under at most one action per file.** Two actions on one space read as a
    sequence and are not one: their executions overlap, so a ``transfer`` row and a ``remove`` row
    on the same space can be validated in either order, and the losing order refuses with advice
    the other line has already taken. A file cannot express a sequence, and this refuses the shape
    that hides it rather than pretending otherwise. Two transfers of one space are the same race
    written a different way, so a transfer group of more than one row is refused too.

    Args:
      rows: The parsed rows, in file order.
      key: The object key, for the refusal message.

    Returns:
      The requests as ``(space, wire_action, usernames, lines)``, in the order their first row
      appeared.

    Raises:
      RejectedFile: On a duplicate row, a space named under two actions, two transfers of one
        space, a group larger than the members cap, or a file over either blast-radius ceiling.
    """
    seen_triples, actions_by_space, groups = {}, {}, {}
    for number, space, word, username in rows:
        triple = (space, word, username)
        if triple in seen_triples:
            raise RejectedFile(
                f"{key} repeats {space}/{word}/{username} on lines {seen_triples[triple]} and "
                f"{number}; a file has no way to mean anything by that"
            )
        seen_triples[triple] = number
        if space in actions_by_space and actions_by_space[space][0] != word:
            other_word, other_line = actions_by_space[space]
            raise RejectedFile(
                f"{key} names {space!r} under {other_word!r} on line {other_line} and {word!r} on "
                f"line {number}. One space takes one action per file: the two requests would run "
                "at the same time, so the file cannot say which happens first. Split it."
            )
        actions_by_space.setdefault(space, (word, number))
        groups.setdefault((space, word), ([], []))
        groups[(space, word)][0].append(username)
        groups[(space, word)][1].append(number)

    if len(actions_by_space) > MAX_SPACES_PER_FILE:
        raise RejectedFile(
            f"{key} names {len(actions_by_space)} spaces; one file may name at most "
            f"{MAX_SPACES_PER_FILE}. Split it and re-upload."
        )
    added = sum(1 for _number, _space, word, _username in rows if word == "add")
    if added > MAX_ADD_ROWS_PER_FILE:
        raise RejectedFile(
            f"{key} carries {added} add rows; one file may carry at most {MAX_ADD_ROWS_PER_FILE}. "
            "Split it and re-upload."
        )

    requests = []
    for (space, word), (usernames, lines) in groups.items():
        if word == "transfer" and len(usernames) > 1:
            raise RejectedFile(
                f"{key} transfers {space!r} twice, on lines {lines}. Two transfers of one space "
                "are a race whichever way they are read."
            )
        if len(usernames) > MAX_MEMBERS_PER_MESSAGE:
            raise RejectedFile(
                f"{key} names {len(usernames)} people to {word} on {space!r}; at most "
                f"{MAX_MEMBERS_PER_MESSAGE} fit in one request. Split it and re-upload."
            )
        requests.append((space, ACTIONS[word], usernames, lines))
    return requests


def _request_id(key, space, action):
    """Derives a stable request id for one coalesced request.

    Derived rather than minted so one enqueued request is traceable to the lines that asked for
    it, and so a tick that crashed between sending and moving the file resends the SAME id. It is
    NOT the deduplication key: see ``_send``.

    Args:
      key: The object key.
      space: The space the request is about.
      action: The wire action.

    Returns:
      The request id.

    Raises:
      None.
    """
    return str(uuid.uuid5(REQUEST_NAMESPACE, f"{key}:{space}:{action}"))


def _dedup_id(request_id, etag):
    """Derives the FIFO deduplication token for one request, salted with the object's ETag.

    Neither the request id nor a random value, and each half of that answers the other. See
    ``_send`` for the two failures being traded off: a guessable token lets a signed-in user
    suppress an operator's row, and a random one lets Lambda's own asynchronous retry deliver the
    same request twice.

    Args:
      request_id: The request's derived id.
      etag: The source object's ETag, or an empty string when S3 returned none.

    Returns:
      The deduplication token.

    Raises:
      None.
    """
    return str(uuid.uuid5(REQUEST_NAMESPACE, f"{request_id}:{etag}"))


def _send(space, action, usernames, request_id, etag):
    """Puts one coalesced request on the shared-space queue.

    The envelope is flat and carries no identity block at all, which is what the ``SenderId``
    comparison on the other side stands in for. The group id is the queue's single constant, so
    these are started in one order with the API's requests, though the runs still overlap. The
    action is the WIRE action, never the operator's word — the validator's vocabulary is
    ``VALID_ACTIONS`` and a message naming ``add`` is refused as unknown.

    **The deduplication id is NOT the request id, and is NOT random either.** It is salted with
    the object's ``ETag``, and both halves of that are the point.

    Not the request id, because the operator is not this queue's only producer of these ids: the
    API's dedup id here is the CALLER'S OWN ``payload["requestId"]``, unaltered, on the same queue
    and the same message group. A purely derived key is a value any signed-in user can compute
    from constants in this repository — the namespace is a literal above and the object key is a
    guess — and claim first on a harmless self-scoped action. SQS would then accept the operator's
    real row and DISCARD it as a duplicate; nothing reads the send response, the file moves to
    ``processed/`` and the log reports the row as enqueued. A suppressed revocation, reported as
    success, to the one channel the operator has. The ``ETag`` closes that: it is the content of a
    file in a bucket the caller cannot read, so it cannot be guessed the way the key can.

    Not random, because the sweep is invoked ASYNCHRONOUSLY by EventBridge and this function sets
    no ``maximum_retry_attempts``, so Lambda's own two retries fire roughly a minute and three
    minutes later — INSIDE the five-minute deduplication window, not outside it like the hourly
    schedule. A random id lets a crash between a send and the file move deliver the whole set
    twice. For the two member verbs that is harmless, but a duplicate ``transfer_ownership``
    arrives after the first has committed, refuses as ``TransferTargetIsOwner``, and notifies the
    new owner that the transfer was refused a minute after telling them it succeeded. Salting
    with the ``ETag`` reproduces the id across a retry of the same bytes, so SQS collapses it,
    while a corrected re-upload under the same key gets a new ``ETag`` and is sent.

    Args:
      space: The space the request is about.
      action: The wire action.
      usernames: The people the request names, in file order.
      request_id: The request's derived id.
      etag: The source object's ``ETag``, salting the deduplication id.

    Returns:
      None.

    Raises:
      ClientError: On any SQS fault.
      ConfigError: When the queue URL is unset.
    """
    if action == "transfer_ownership":
        payload = {"newOwner": usernames[0]}
    else:
        payload = {"members": list(usernames)}
    body = {
        "schemaVersion": SCHEMA_VERSION,
        "requestId": request_id,
        "action": action,
        "origin": "operator",
        "space": space,
        "payload": payload,
    }
    clients.sqs().send_message(
        QueueUrl=_queue_url(),
        MessageBody=json.dumps(body, separators=(",", ":")),
        MessageGroupId=MESSAGE_GROUP_ID,
        MessageDeduplicationId=_dedup_id(request_id, etag),
    )


def _move(key, destination_prefix, stamp, reason=None):
    """Copies one object aside, confirms the copy, then deletes the original.

    **The order is the requirement, not the implementation.** A delete that ran first, followed by
    a failed copy, would lose the operator's file with nothing to recover it from — and the loss
    would be silent, because the next tick simply finds an empty inbox.

    Args:
      key: The object key in the inbox.
      destination_prefix: ``PROCESSED`` or ``REJECTED``.
      stamp: The invocation timestamp the destination is grouped under.
      reason: The refusal, written beside the file when there is one.

    Returns:
      The destination key.

    Raises:
      ClientError: On any S3 fault. The original is left in place, so the next tick retries.
    """
    s3 = clients.s3()
    name = key[len(INBOX) :]
    destination = f"{destination_prefix}{stamp}/{name}"

    s3.copy_object(
        Bucket=cpconfig.ADMIN_BUCKET,
        Key=destination,
        CopySource={"Bucket": cpconfig.ADMIN_BUCKET, "Key": key},
    )
    if reason is not None:
        s3.put_object(
            Bucket=cpconfig.ADMIN_BUCKET,
            Key=f"{destination}.reason.txt",
            Body=reason.encode("utf-8"),
            ContentType="text/plain",
        )
    s3.delete_object(Bucket=cpconfig.ADMIN_BUCKET, Key=key)
    return destination


def _process(key, size, stamp, budget):
    """Enqueues one file's requests and files the object away.

    The budget is counted in ROWS READ rather than in messages sent, which coalescing makes
    conservative and which is the point: this function was never the expensive half.

    Args:
      key: The object key in the inbox.
      size: The object's size in bytes, from the listing.
      stamp: The invocation timestamp.
      budget: How many rows this invocation may still read.

    Returns:
      A ``(rows_read, disposition)`` pair. ``DONE`` means the file is out of the inbox one way or
      another; ``DEFERRED`` means this invocation ran out of budget and the sweep must stop, so
      the remaining files keep their place in listing order.

    Raises:
      ClientError: On any S3 or SQS fault.
    """
    s3 = clients.s3()
    if size > MAX_FILE_BYTES:
        reason = (
            f"{key} is {size} bytes; at most {MAX_FILE_BYTES} can be read in one run, and a file "
            f"this size would exhaust the function rather than be refused. Split it and re-upload."
        )
        _move(key, REJECTED, stamp, reason=reason)
        logger.warning("rejected %s: %s", key, reason)
        observability.warning(
            "rejected an operator request file larger than one invocation can read",
            object_key=key,
            bytes_in_file=size,
            cap=MAX_FILE_BYTES,
            outcome="rejected",
        )
        return 0, DONE

    obj = s3.get_object(Bucket=cpconfig.ADMIN_BUCKET, Key=key)
    body = obj["Body"].read()
    # NOT `.get(... ) or ""`. An empty salt silently reverts the deduplication token to a value
    # computable from two literals in this repository, which is the whole thing the salt exists to
    # prevent — and it would do it with no log line and no refusal. S3 always returns an ETag, so
    # a KeyError here means something is wrong that should stop the file rather than degrade it:
    # raising leaves it in the inbox for the next tick.
    etag = obj["ETag"]

    try:
        rows = _rows(body, key)
        requests = _requests(rows, key)
    except RejectedFile as exc:
        _move(key, REJECTED, stamp, reason=str(exc))
        logger.warning("rejected %s: %s", key, exc)
        observability.warning("rejected an operator request file", object_key=key, outcome="rejected")
        return 0, DONE

    if len(rows) > MAX_ROWS_PER_INVOCATION:
        reason = (
            f"{key} carries {len(rows)} rows; at most {MAX_ROWS_PER_INVOCATION} are read in one "
            f"run, so this file could never be handled. Split it and re-upload."
        )
        _move(key, REJECTED, stamp, reason=reason)
        logger.warning("rejected %s: %s", key, reason)
        observability.warning(
            "rejected an operator request file larger than one invocation",
            object_key=key,
            rows_in_file=len(rows),
            rows_not_processed=len(rows),
            cap=MAX_ROWS_PER_INVOCATION,
            outcome="rejected",
        )
        return 0, DONE

    if len(rows) > budget:
        observability.warning(
            "row budget spent; the file stays in the inbox for the next tick",
            object_key=key,
            rows_in_file=len(rows),
            rows_not_processed=len(rows),
            cap=MAX_ROWS_PER_INVOCATION,
        )
        logger.warning(
            "%s carries %d rows and only %d remain in this invocation's budget; leaving it",
            key, len(rows), budget,
        )
        return 0, DEFERRED

    for space, action, usernames, lines in requests:
        _send(space, action, usernames, _request_id(key, space, action), etag)
        logger.info("enqueued %s on %s for %s from %s lines %s", action, space, usernames, key, lines)
        observability.info(
            "enqueued an operator request",
            object_key=key,
            space=space,
            action=action,
            members=len(usernames),
            lines=lines,
        )

    _move(key, PROCESSED, stamp)
    observability.info(
        "enqueued an operator request file",
        object_key=key,
        rows_enqueued=len(rows),
        requests_enqueued=len(requests),
        outcome="processed",
    )
    return len(rows), DONE


@observability.traced("transfer-reader")
def handler(event, context):
    """Sweeps the inbox once, on the schedule's tick.

    An empty or absent inbox is a successful no-op that enqueues nothing. That is a requirement
    rather than a nicety: a newly created schedule fires against an inbox no operator has ever
    written to, and a reader that treated that as a failure would report one on every deploy.

    Args:
      event: The EventBridge scheduled event, unused.
      context: The Lambda context, unused.

    Returns:
      A summary of what the tick did.

    Raises:
      ClientError: On any S3 or SQS fault. The file stays in the inbox and the next tick retries.
      KeyError: When S3 returns an object with no ETag, which would otherwise degrade the
        deduplication token to a guessable one.
      ConfigError: When the queue URL is unset.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    keys = _inbox_objects()
    read, files = 0, 0

    for key, size in keys:
        budget = MAX_ROWS_PER_INVOCATION - read
        rows_read, disposition = (
            (0, DEFERRED) if budget <= 0 else _process(key, size, stamp, budget)
        )
        if disposition == DEFERRED:
            observability.warning(
                "row budget spent; the rest of the inbox waits for the next tick",
                files_not_processed=len(keys) - files,
                cap=MAX_ROWS_PER_INVOCATION,
            )
            break
        read += rows_read
        files += 1

    logger.info("transfer-reader: %d files, %d rows read", files, read)
    observability.info(
        "operator request inbox swept",
        files_seen=len(keys),
        files_handled=files,
        rows_enqueued=read,
    )
    return {"status": "ok", "filesSeen": len(keys), "filesHandled": files, "rowsEnqueued": read}
