"""acquire-refresh-lock — the refresh branch's first task, and the serialization Glue lacks.

Two refreshes of one table can overlap: ``MessageGroupId`` is the target database, so SQS
serializes delivery per database, but the Pipe starts the machine ``FIRE_AND_FORGET`` and returns
immediately. SPEC-149's in-place ``UpdateTable`` reduced the damage to last-write-wins between two
definitions and could not close it, because Glue offers no compare-and-set. This verb takes a
per-table lock so the second refresh is REFUSED rather than raced.

It runs AFTER validate-authorize and BEFORE load-table-definition. Both positions are load-bearing:
after the validator so an unauthorized request cannot touch another user's lock at all, and before
the definition read so the lock spans the whole read-modify-write rather than only the write — the
point being that run A's ``GetTable`` and run A's ``UpdateTable`` are not separated by run B's.

The holder is the REQUEST ID, not the execution ARN. The ARN is reachable only through the ASL
context object, which would mean wrapping the task payload — and every notification path in this
plane reads the request at the top level of the event, so wrapping would silence the very
notification FR-003 requires. The request id is already on the state, unique per request, and makes
a retried acquire re-entrant rather than self-refusing.
"""

import logging

from cpcommon import events, observability
from cpcommon.errors import TerminalError
from tbcommon import notify, table_lock

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")


@observability.traced("acquire-refresh-lock")
@notify.notifies_on_failure("refresh")
def handler(event: dict, context) -> dict:
    """Step Functions entry point: claims the target table's refresh lock.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that failed and
    notified.

    Args:
      event: The validated task input, carrying the space, table name and request id.
      context: The Lambda context, unused.

    Returns:
      The event with ``lock.etag`` added — what the release task conditions its write on.

    Raises:
      TerminalError: ``refresh_already_running`` when another refresh holds the lock; notified to
        the actor before the SFN Catch records it.
      ClientError: Any S3 fault that is not a precondition failure.
    """
    return _acquire_refresh_lock(event)


def _acquire_refresh_lock(event: dict) -> dict:
    """Claims the lock and threads its entity tag onto the running request object.

    The refusal is deliberately terminal rather than retried or queued. A held lock means a
    refresh of this table is ALREADY running against the same files, so a queued run would almost
    always compute an identical definition and write it a second time — paying a full
    inspect-source over the folder to produce a no-op. The user's intent is already being served
    by the run in progress.

    Args:
      event: The validated task input.

    Returns:
      The event with ``lock.etag`` added.

    Raises:
      TerminalError: ``refresh_already_running`` when the lock is held elsewhere, or
        ``malformed_event`` when a required field is missing.
      ClientError: Any S3 fault that is not a precondition failure.
    """
    database = events.require(event, "space", "database")
    table = events.require(event, "tableName")
    request_id = events.require(event, "requestId")

    acquired, etag = table_lock.acquire(database, table, request_id)
    if not acquired:
        raise TerminalError(
            "refresh_already_running",
            f"a refresh of table {table!r} in database {database!r} is already running",
        )

    logger.info("refresh lock acquired for %s.%s", database, table)
    observability.info("refresh proceeding under lock", database=database, table=table)
    return {**event, "lock": {"etag": etag}}
