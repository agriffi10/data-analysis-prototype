"""create-table — the recipient Map's final verb (SPEC-092).

For one (copied) recipient: render the cloned source definition as a
``CREATE EXTERNAL TABLE IF NOT EXISTS`` with LOCATION repointed to the recipient's
``shared_tables/{tableName}/`` prefix, run it via Athena against the RECIPIENT
database in the shared workgroup, and poll to a terminal state — the same
LF-enforced create path the table-builder uses (architecture §6). Projection props
were carried verbatim, so a partitioned clone is queryable immediately (no MSCK);
IF NOT EXISTS + the SPEC-091 conflict guard make a Step Function replay a no-op
success.

An Athena FAILED/CANCELLED raises TerminalError("create_failed", <reason>) — the
per-recipient Catch records it; sibling recipients continue. Query results (a DDL
create returns none) land under the recipient's athenaresults prefix for the actor,
consistent with the SPEC-055/070 routing.
"""

import logging

from tscommon import athena as athena_mod
from cpcommon import config
from tscommon import ddl, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _results_location(recipient: dict, actor: str) -> str:
    """``s3://{destBucket}/{database}/athenaresults/{actor}/`` (SPEC-055/070 routing)."""
    return f"s3://{recipient['destBucket']}/{recipient['database']}/athenaresults/{actor}/"


@notify.notifies_on_failure("create")
def handler(event, context) -> dict:
    """Recipient-Map entry point: create the cloned table in the recipient database.

    Renders the cloned source definition with LOCATION repointed to the recipient's
    ``shared_tables/`` prefix and runs it via Athena. On success, notifies the sender and
    the success target (SPEC-094). A failed/timed-out CREATE raises ``TerminalError`` (the
    sender is notified before the per-recipient ``Catch`` records it); a throttling error
    raises ``TransientError`` for the SFN ``Retry`` and is not notified.
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
    # Terminal success — tell the sender AND the success target (user recipient
    # directly; space recipient via its owner) (SPEC-094 FR-001/FR-002).
    notify.emit_recipient_success(event)
    return {"recipient": recipient, "request": request}
