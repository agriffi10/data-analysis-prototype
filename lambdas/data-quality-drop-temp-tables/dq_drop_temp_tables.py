"""data-quality drop-temp-tables — cleanup, reached on every path.

The state machine invokes this twice over: once on the success path, and once from every verb's
Catch, since a state has one successor. Without the failure-path invocation, every failed request
would leak a temp table into the user's own Glue database, where it shows up in the Query
workspace's schema rail and eventually collides with a real table name.

Two properties make it safe to call from anywhere. It touches Glue only — no object-delete
permission is granted anywhere in this arc, so reaching this verb from a validator failure, where
the body-supplied location has not been authorized yet, cannot delete anything of the user's. And
it is idempotent and tolerant of never having had anything to do: the drop is conditional, and a
request that failed before the tables were created carries no table names at all, which is a
successful no-op rather than an error.

The service name is the control plane, not the function: one data-quality run is nine
invocations, and they are only one queryable set if they share it. The per-verb identity rides as
the ``verb`` field.
"""

import logging

from cpcommon import athena, observability
from cpcommon import config as cpconfig
from dqcommon import messages, notify, results, sql

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="data-quality")


@observability.step("drop-table")
def _drop(database: str, table: str, output_location: str) -> bool:
    """Drops one temp table, reporting rather than raising on failure.

    Cleanup never raises, and that is a deliberate trade. On the failure path, raising would
    replace the reason the user is actually notified about with a cleanup error. On the success
    path it is worse: the report is already written and the check genuinely succeeded, so a Glue
    hiccup here would tell the user their check failed while their report sits in S3.

    The cost of swallowing is a leaked temp table. It is bounded to one table in one database,
    observable in the log at error level, and recoverable by hand — strictly better than either
    failure mode above. The outcome is threaded onto the state too, so an operator can see it in
    the execution history without reading CloudWatch, and the leak is recorded at warning rather
    than error because the request did not fail and must not read as though it did. The event
    names the table, because the recovery is a human running a drop by hand.

    Args:
      database: The database the table lives in.
      table: The table to drop.
      output_location: The ``s3://`` results prefix for the DDL statement.

    Returns:
      True when the drop ran, False when it failed.

    Raises:
      None.
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
    except Exception as exc:
        logger.exception(
            "LEAKED TEMP TABLE: could not drop %s.%s — it must be removed by hand",
            database,
            table,
        )
        observability.warning(
            "temp table leaked",
            database=database,
            table=table,
            error_type=type(exc).__name__,
        )
        return False


def _cleanup(event: dict) -> dict:
    """Drops whichever temp tables the run created and threads the outcome onward.

    A run with no database or table names was reached before the tables were created — the
    overwhelmingly common failure case, a validator or inspection failure. Nothing to do is the
    correct outcome there, so it is recorded as a clean no-op. The dropped and failed tables are
    named rather than only counted, because recovering a leaked table means running a drop by
    hand and a count does not say which one.

    Args:
      event: The task input, carrying the database and any temp table names.

    Returns:
      The event with the cleanup outcome attached.

    Raises:
      None.
    """
    database = event.get("database")
    tables = [name for name in (event.get("tempTable"), event.get("tempRawTable")) if name]

    out = dict(event)
    if not database or not tables:
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
    ddl_output = results.ddl_output(bucket, event.get("reportPrefix") or "")

    dropped, failed = [], []
    for table in tables:
        (dropped if _drop(database, table, ddl_output) else failed).append(table)

    observability.info(
        "cleaned up",
        database=database,
        tables=len(tables),
        dropped=dropped,
        failed=failed,
        skipped=False,
    )
    out["cleanup"] = {"dropped": dropped, "failed": failed, "skipped": False}
    return out


@observability.traced("drop-temp-tables")
@notify.notifies_on_failure("drop-temp-tables")
def handler(event, context) -> dict:
    """Drops both temp tables, if any, and threads the cleanup outcome onward.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Three layers keep cleanup from ever misrepresenting an outcome, because this verb runs on both
    paths and a naive version gets each one wrong in a different way. The per-table drop swallows
    a failure outright, so the ordinary case — throttling, a denial, a table that vanished — never
    becomes a terminal at all. On the failure path, anything that does escape collapses into the
    real cause, which was emitted seconds earlier under the same dedup id, pinned by test. On the
    success path there is no earlier failure to collapse into, so the notify verb suppresses
    instead: the recorded failure carries the report key, and a non-null value there means the
    report was written and the user was already told. Only a Lambda-level failure of this function
    can reach that point, which is exactly why no verb-side guard could have covered it.

    Args:
      event: The task input.
      context: The Lambda context, unused.

    Returns:
      The event with the cleanup outcome attached.

    Raises:
      None from the drops themselves; a Lambda-level failure is caught by the state machine.
    """
    request = dict(event) if isinstance(event, dict) else {}
    return _cleanup(request)
