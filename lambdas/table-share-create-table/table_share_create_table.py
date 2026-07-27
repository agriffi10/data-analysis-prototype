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

from cpcommon import config, observability
from tscommon import athena as athena_mod
from tscommon import ddl, notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one share is five invocations (plus a
# recipient Map fan-out), and they are only one queryable set if they share a service name
# (SPEC-127 FR-003). The per-verb identity rides as the `verb` field.
observability.init(service="table-share")


def _results_location(recipient: dict, actor: str) -> str:
    """``s3://{destBucket}/{database}/athenaresults/{actor}/`` (SPEC-055/070 routing)."""
    return f"s3://{recipient['destBucket']}/{recipient['database']}/athenaresults/{actor}/"


# @traced is OUTERMOST, above @notifies_on_failure: the latter catches on its way out,
# so if it were outermost the span would close status="ok" on an invocation that
# actually failed and notified.
@observability.traced("create-table")
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
    # The recipient DATABASE is the field that matters: this plane creates tables in databases
    # it does not own, via the same TBAC grant whose absence caused table-builder's
    # silent-create incident (SPEC-070/111).
    observability.info(
        "recipient table created",
        database=database,
        table=table_name,
        actor=request.get("actor"),
    )
    # Terminal success — tell the sender AND the success target (user recipient
    # directly; space recipient via its owner) (SPEC-094 FR-001/FR-002).
    notify.emit_recipient_success(event)
    return {"recipient": recipient, "request": request}
