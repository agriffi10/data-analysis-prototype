"""create-table — the recipient Map's final verb.

For one copied recipient: renders the cloned source definition as a
``CREATE EXTERNAL TABLE IF NOT EXISTS`` with the location repointed to the recipient's own
shared-tables prefix, runs it via Athena against the recipient database in the shared
workgroup, and polls to a terminal state — the same Lake-Formation-enforced create path the
table-builder uses. Projection properties were carried verbatim, so a partitioned clone is
queryable immediately, and the idempotent form plus the conflict guard make a replay a no-op
success.

The service name is the control plane, not the function, so one share's invocations and its
Map fan-out stay one queryable set. The per-verb identity rides as the ``verb`` field.
"""

import logging

from cpcommon import config, observability
from tscommon import athena as athena_mod
from tscommon import ddl, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-share")


def _results_location(recipient: dict, actor: str) -> str:
    """Builds the Athena results prefix for this create, under the recipient's database.

    A DDL create returns no rows, but the workgroup requires a location, and this routing
    matches the rest of the portal's.

    Args:
      recipient: The recipient, carrying its destination bucket and database.
      actor: The sender's verified username.

    Returns:
      An ``s3://`` prefix ending in a slash.

    Raises:
      KeyError: If the recipient is missing its destination bucket or database.
    """
    return f"s3://{recipient['destBucket']}/{recipient['database']}/athenaresults/{actor}/"


@observability.traced("create-table")
@notify.notifies_on_failure("create")
def handler(event, context) -> dict:
    """Recipient-Map entry point: creates the cloned table in the recipient's database.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    The recipient database is the field that matters in the record: this plane creates tables
    in databases it does not own, via the same tag-based grant whose absence caused the
    table-builder's silent-create incident. On success both the sender and the success target
    are told — a user recipient directly, a space recipient via its owner.

    Args:
      event: The Map item, carrying the recipient and the request with its cloned definition.
      context: The Lambda context, unused.

    Returns:
      The recipient and the request, threaded onward.

    Raises:
      TerminalError: ``create_failed`` or ``create_timeout``, notified to the sender before the
        per-recipient Catch records it. Sibling recipients continue.
      TransientError: On a throttling error, passed through un-notified for the SFN Retry.
    """
    recipient = event.get("recipient") or {}
    request = event.get("request") or {}
    table_name = request.get("tableName")
    database = recipient.get("database")

    query = ddl.render_create_external(
        request["tableDefinition"],
        database,
        table_name,
        f"s3://{recipient['destBucket']}/{recipient['destPrefix']}",
    )
    athena_mod.run_ddl(
        query=query,
        database=database,
        workgroup=config.ATHENA_WORKGROUP,
        output_location=_results_location(recipient, request.get("actor")),
    )

    logger.info("created table %s.%s for %s", database, table_name, request.get("actor"))
    observability.info(
        "recipient table created",
        database=database,
        table=table_name,
        actor=request.get("actor"),
    )
    notify.emit_recipient_success(event)
    return {"recipient": recipient, "request": request}
