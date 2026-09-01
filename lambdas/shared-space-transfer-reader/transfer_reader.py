"""shared-space transfer-reader: the operator's door into the ownership-transfer verb.

The UI cannot serve one case — an owner who has already left. So an operator drops a CSV in the
admin bucket and this reads it on a schedule, putting one request per row on the **same queue** the
UI writes to. That reuse is the point: an operator-driven transfer and a user-driven one are the
same verb doing the same work, authorized by the same code, notifying the same two people.

**It is not a verb and it runs under its own role**, which is the whole of what makes the boundary
on the other side mean anything. The plane trusts an operator message because the ``SenderId`` SQS
stamps on it names this role; sharing the orchestrator's role would make that comparison admit every
verb in the fleet, and would do it while every test stayed green.

It also carries **no domain layer**, deliberately. ``shared-space-common``'s configuration requires
the portal role ARN at import, and this function has no use for it — attaching the layer would buy a
schema-version constant at the price of a cold-start crash on a variable nobody here reads, which is
the failure that once took this plane down for nine days. The constant is local and a test pins it
to the layer's.

The reader knows nothing about spaces. It does not read the registry, does not check that a space
exists or that the named member belongs to it, and holds no grant that would let it — every one of
those questions is the validator's, and answering them twice is how two authorities disagree.

Attributes:
  INBOX: The prefix an operator writes to. It has no expiry rule, because a file this function has
    not managed to process must not be deleted out from under it.
  PROCESSED: Where a file goes once its rows are enqueued.
  REJECTED: Where a file goes when it cannot be parsed, beside a sibling naming the reason.
  HEADER: The only header row accepted. Any other set rejects the whole file rather than guessing
    which column is which — a transposed pair would transfer every named space to the wrong person.
  TIMEOUT_SECONDS: The function's own ceiling, as Terraform sets it. The row cap is derived from it.
  SEND_BUDGET_FRACTION: The share of an invocation reserved for sending, leaving the rest for the
    listing, the reads, the copies and the deletes.
  SEND_MILLISECONDS: A conservative round trip for one ``SendMessage``, the same figure this plane's
    one-shot backfill sizes its own walk with.
  MAX_ROWS_PER_INVOCATION: The computed cap. Reaching it is not a failure — the file stays in the
    inbox and the next tick continues it, and the count not processed is logged rather than dropped
    silently.
  MESSAGE_GROUP_ID: The queue's single constant group, so operator and UI requests are one strictly
    ordered stream rather than two racing ones.
  SCHEMA_VERSION: The envelope version the validator accepts.
  REQUEST_NAMESPACE: The UUID namespace the per-row request id is derived in.
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

INBOX = "ownership-transfers/inbox/"
PROCESSED = "ownership-transfers/processed/"
REJECTED = "ownership-transfers/rejected/"

HEADER = ["space", "new_owner"]

TIMEOUT_SECONDS = 60
SEND_BUDGET_FRACTION = 0.5
SEND_MILLISECONDS = 50
MAX_ROWS_PER_INVOCATION = int(TIMEOUT_SECONDS * SEND_BUDGET_FRACTION * 1000 / SEND_MILLISECONDS)

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
      The object keys, oldest-named first.

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
        keys.extend(item["Key"] for item in page.get("Contents", []) if not item["Key"].endswith("/"))
        token = page.get("NextContinuationToken")
        if not token:
            break
    return keys


def _rows(body, key):
    """Parses one CSV into ``(space, new_owner)`` pairs, or refuses the whole file.

    The header is compared as an exact list rather than as a set of expected names. A file whose
    columns are the right two in the wrong order parses perfectly and transfers every space it
    names to the wrong person, and there is no later check that would catch it.

    Args:
      body: The object's bytes.
      key: The object key, for the refusal message.

    Returns:
      The data rows as pairs.

    Raises:
      RejectedFile: On an unreadable file, a wrong header, or a row that is not two non-empty
        fields.
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RejectedFile(f"{key} is not UTF-8 text: {exc}") from exc

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise RejectedFile(f"{key} is empty — it carries not even a header row") from None

    if [column.strip() for column in header] != HEADER:
        raise RejectedFile(
            f"{key} has header {header!r}; the only header accepted is {HEADER!r}"
        )

    rows = []
    for number, row in enumerate(reader, start=2):
        if not row or all(not field.strip() for field in row):
            continue
        if len(row) != 2:
            raise RejectedFile(f"{key} line {number} has {len(row)} fields, not 2")
        space, new_owner = (field.strip() for field in row)
        if not space or not new_owner:
            raise RejectedFile(f"{key} line {number} leaves a field blank")
        rows.append((space, new_owner))
    return rows


def _request_id(key, index):
    """Derives a stable request id for one row.

    Derived rather than minted, so a tick that crashed between sending and moving the file resends
    the SAME id: the queue's deduplication then collapses the replay instead of transferring twice.
    Past that window the replay is refused as a no-op, because the named member already owns the
    space — the correct outcome rather than a silent second transfer.

    Args:
      key: The object key.
      index: The row's position in the file.

    Returns:
      The request id.

    Raises:
      None.
    """
    return str(uuid.uuid5(REQUEST_NAMESPACE, f"{key}:{index}"))


def _send(space, new_owner, request_id):
    """Puts one transfer request on the shared-space queue.

    The envelope is flat and carries no identity block at all, which is what the ``SenderId``
    comparison on the other side stands in for. The group id is the queue's single constant, so
    these interleave with the API's requests in one order rather than racing them.

    Args:
      space: The space to transfer.
      new_owner: The member taking it.
      request_id: The row's derived request id.

    Returns:
      None.

    Raises:
      ClientError: On any SQS fault.
      ConfigError: When the queue URL is unset.
    """
    body = {
        "schemaVersion": SCHEMA_VERSION,
        "requestId": request_id,
        "action": "transfer_ownership",
        "origin": "operator",
        "space": space,
        "payload": {"newOwner": new_owner},
    }
    clients.sqs().send_message(
        QueueUrl=_queue_url(),
        MessageBody=json.dumps(body, separators=(",", ":")),
        MessageGroupId=MESSAGE_GROUP_ID,
        MessageDeduplicationId=request_id,
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


def _process(key, stamp, budget):
    """Enqueues one file's rows and files the object away.

    Args:
      key: The object key in the inbox.
      stamp: The invocation timestamp.
      budget: How many rows this invocation may still send.

    Returns:
      The number of rows sent. A file left for the next tick returns what it managed.

    Raises:
      ClientError: On any S3 or SQS fault.
    """
    s3 = clients.s3()
    body = s3.get_object(Bucket=cpconfig.ADMIN_BUCKET, Key=key)["Body"].read()

    try:
        rows = _rows(body, key)
    except RejectedFile as exc:
        _move(key, REJECTED, stamp, reason=str(exc))
        logger.warning("rejected %s: %s", key, exc)
        observability.warning("rejected an ownership-transfer file", object_key=key, outcome="rejected")
        return 0

    if len(rows) > budget:
        observability.warning(
            "row cap reached; the file stays in the inbox for the next tick",
            object_key=key,
            rows_in_file=len(rows),
            rows_not_processed=len(rows),
            cap=MAX_ROWS_PER_INVOCATION,
        )
        logger.warning(
            "%s carries %d rows and only %d remain in this invocation's budget; leaving it",
            key, len(rows), budget,
        )
        return 0

    for index, (space, new_owner) in enumerate(rows, start=2):
        _send(space, new_owner, _request_id(key, index))
        logger.info("enqueued transfer of %s to %s from %s", space, new_owner, key)

    _move(key, PROCESSED, stamp)
    observability.info(
        "enqueued an ownership-transfer file",
        object_key=key,
        rows_enqueued=len(rows),
        outcome="processed",
    )
    return len(rows)


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
      ConfigError: When the queue URL is unset.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    keys = _inbox_objects()
    sent, files = 0, 0

    for key in keys:
        budget = MAX_ROWS_PER_INVOCATION - sent
        if budget <= 0:
            observability.warning(
                "row cap reached; files remain in the inbox for the next tick",
                files_not_processed=len(keys) - files,
                cap=MAX_ROWS_PER_INVOCATION,
            )
            break
        sent += _process(key, stamp, budget)
        files += 1

    logger.info("transfer-reader: %d files, %d rows enqueued", files, sent)
    observability.info(
        "ownership-transfer inbox swept",
        files_seen=len(keys),
        files_handled=files,
        rows_enqueued=sent,
    )
    return {"status": "ok", "filesSeen": len(keys), "filesHandled": files, "rowsEnqueued": sent}
