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

from cpcommon import athena, observability
from cpcommon import config as cpconfig
from dqcommon import messages, notify, sql

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one data-quality run is nine
# invocations, and they are only one queryable set if they share a service name
# (SPEC-127 FR-003). The per-verb identity rides as the `verb` field on each span.
observability.init(service="data-quality")


@observability.step("drop-table")
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
    except Exception as exc:  # cleanup is best-effort by design (see docstring)
        logger.exception(
            "LEAKED TEMP TABLE: could not drop %s.%s — it must be removed by hand",
            database,
            table,
        )
        # WARNING, not error: the request did not fail and must not read as though it did
        # (SPEC-132 FR-003). What it costs is one leaked table, by design — so the event says
        # which one, because the recovery is a human running a DROP by hand.
        observability.warning(
            "temp table leaked",
            database=database,
            table=table,
            error_type=type(exc).__name__,
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
        observability.info("nothing to drop", tables=0, dropped=0, failed=0, skipped=True)
        out["cleanup"] = {"dropped": [], "failed": [], "skipped": True}
        return out

    bucket = (event.get("space") or {}).get("bucket") or cpconfig.USER_SPACE_BUCKET
    report_prefix = (event.get("reportPrefix") or "").rstrip("/")
    ddl_output = f"s3://{bucket}/{report_prefix}/ddl/" if report_prefix else f"s3://{bucket}/"

    dropped, failed = [], []
    for table in tables:
        (dropped if _drop(database, table, ddl_output) else failed).append(table)

    observability.info(
        "cleaned up",
        database=database,
        tables=len(tables),
        # Named, not just counted: recovering a leaked table means running a DROP by hand,
        # and a count does not say which one.
        dropped=dropped,
        failed=failed,
        skipped=False,
    )
    out["cleanup"] = {"dropped": dropped, "failed": failed, "skipped": False}
    return out


# @traced is OUTERMOST, above @notifies_on_failure, deliberately: notifies_on_failure
# catches on its way out, so if it were outermost the span would close status="ok" on an
# invocation that actually failed and notified. Outermost traced sees the exception the
# handler really raised.
@observability.traced("drop-temp-tables")
@notify.notifies_on_failure("drop-temp-tables")
def handler(event, context) -> dict:
    """Drop both temp tables (if any) and thread the cleanup outcome onward.

    THREE LAYERS KEEP CLEANUP FROM EVER MISREPORTING AN OUTCOME, because this verb runs on
    both paths and a naive version gets each one wrong in a different way:

    1. ``_drop`` swallows a failed DROP outright, so the ordinary case — Glue throttling,
       an AccessDenied, a table that vanished — never becomes a terminal at all.
    2. On the FAILURE path, anything that does escape collapses into the real cause: it was
       emitted seconds earlier under the same ``{requestId}:failure`` dedup id (pinned by
       ``test_a_cleanup_failure_cannot_mask_the_real_reason``).
    3. On the SUCCESS path there is no earlier failure to collapse into, so notify-failure
       suppresses instead: ``RecordFailure`` carries ``$.reportKey``, and a non-null value
       there means the report was written and the user was already told. Only a
       LAMBDA-LEVEL failure of this function — an import error, a timeout — can reach that
       point, which is exactly why no verb-side guard could have covered it.
    """
    request = dict(event) if isinstance(event, dict) else {}
    return _cleanup(request)
