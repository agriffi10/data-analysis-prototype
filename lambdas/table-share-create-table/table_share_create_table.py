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
from tscommon import config, ddl

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _results_location(recipient: dict, actor: str) -> str:
    """``s3://{destBucket}/{database}/athenaresults/{actor}/`` (SPEC-055/070 routing)."""
    return f"s3://{recipient['destBucket']}/{recipient['database']}/athenaresults/{actor}/"


def handler(event, context) -> dict:
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
    return {"recipient": recipient, "request": request}
