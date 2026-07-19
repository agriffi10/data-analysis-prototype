"""data-quality drop-temp-tables — cleanup, reached on EVERY path.

The state machine invokes this twice over: once on the success path, and once as
``DropTempTablesOnFailure`` from every verb's Catch (a state has one ``Next``, hence the
twin). Without the failure-path invocation, every failed request would LEAK a temp table
into the user's own Glue database, where it shows up in the Query workspace's schema rail
and eventually collides with a real table name.

Two properties make it safe to call from anywhere:

  - **It touches GLUE ONLY.** No ``s3:DeleteObject`` is granted anywhere in this arc, so
    reaching this verb from a validator failure — where the body-supplied location has not
    been authorized yet — cannot delete anything of the user's.
  - **It is idempotent, and tolerant of never having had anything to do.** ``DROP TABLE IF
    EXISTS`` makes a repeat a no-op, and a request that failed before create-temp-tables
    ran carries no table names at all, which is a successful no-op rather than an error.
"""

import logging

from cpcommon import athena, config as cpconfig
from dqcommon import messages, sql

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _drop(database: str, table: str, output_location: str) -> bool:
    """Drop one table. Returns True if the DROP ran, False if it failed (logged).

    CLEANUP NEVER RAISES — and that is a deliberate trade, not an oversight.

    On the FAILURE path, raising would replace the reason the user is actually notified
    about with a cleanup error (FR-005). On the SUCCESS path it is worse: the report is
    already written and the check genuinely succeeded, so a Glue hiccup here would tell
    the user their check failed while their report sits in S3. Neither is worth it.

    The cost of swallowing is a leaked temp table. It is bounded (one table, in one
    database), observable (this log line, at ERROR), and recoverable by hand — strictly
    better than either failure mode above. The outcome is also threaded onto the state so
    an operator can see it in the execution history without reading CloudWatch.
    """
    try:
        athena.run_ddl(
            query=sql.build_drop_table_ddl(database, table),
            database=database,
            workgroup=cpconfig.ATHENA_WORKGROUP,
            output_location=output_location,
            fail_reason=messages.QUERY_FAILED,
            timeout_reason=messages.QUERY_TIMEOUT,
        )
        logger.info("dropped %s.%s", database, table)
        return True
    except Exception:  # noqa: BLE001 - cleanup is best-effort by design (see docstring)
        logger.exception(
            "LEAKED TEMP TABLE: could not drop %s.%s — it must be removed by hand",
            database,
            table,
        )
        return False


def _cleanup(event: dict) -> dict:
    database = event.get("database")
    tables = [name for name in (event.get("tempTable"), event.get("tempRawTable")) if name]

    out = dict(event)
    if not database or not tables:
        # Reached before create-temp-tables ran — the overwhelmingly common failure case
        # (a validator or inspection failure). Nothing to do IS the correct outcome here,
        # so it is logged at INFO and reported as a clean no-op.
        logger.info(
            "nothing to drop for requestId=%s (database=%r, tables=%s)",
            event.get("requestId"),
            database,
            tables,
        )
        out["cleanup"] = {"dropped": [], "failed": [], "skipped": True}
        return out

    bucket = (event.get("space") or {}).get("bucket") or cpconfig.USER_SPACE_BUCKET
    report_prefix = (event.get("reportPrefix") or "").rstrip("/")
    ddl_output = f"s3://{bucket}/{report_prefix}/ddl/" if report_prefix else f"s3://{bucket}/"

    dropped, failed = [], []
    for table in tables:
        (dropped if _drop(database, table, ddl_output) else failed).append(table)

    out["cleanup"] = {"dropped": dropped, "failed": failed, "skipped": False}
    return out


def handler(event, context) -> dict:
    """Drop both temp tables (if any) and thread the cleanup outcome onward."""
    request = dict(event) if isinstance(event, dict) else {}
    return _cleanup(request)
