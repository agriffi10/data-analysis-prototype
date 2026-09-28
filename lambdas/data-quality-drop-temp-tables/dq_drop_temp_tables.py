"""data-quality drop-temp-tables — cleanup, reached on every path.

The state machine invokes this twice over: once on the success path, and once from every verb's
Catch, since a state has one successor. Without the failure-path invocation, every failed request
would leak a temp table into the user's own Glue database, where it shows up in the Query
workspace's schema rail and eventually collides with a real table name.

Two properties make it safe to call from anywhere. It touches Glue only — no object-delete
permission is granted anywhere in this arc, so reaching this verb from a validator failure, where
the body-supplied location has not been authorized yet, cannot delete anything of the user's. And
it is idempotent and tolerant of never having had anything to do: the drop is conditional, and a
request that failed before the create verb was reached has nothing to name, which is a successful
no-op rather than an error.

What it must NOT do is read the names off the create verb's output alone. A Catch keeps the state
that went INTO the failed state, so a create that died between its two statements returns no names
at all — the one path where reading them back leaks the table it had already built. The names and
the database are re-derived from the request id when the state carries none.

Cleanup is bounded in time as well as swallowed, because a drop that is only slow raises nothing
for the swallow to catch. On the success path this verb runs after assemble-report has told the
user the check completed, and a Lambda timeout here lands in the state's Catch, which records the
run as failed. So every Athena call of both drops — each start and each poll — runs under one
``cpcommon.budget`` on ``cpcommon.clients.athena_bounded``, and a drop reached once the budget is
spent is not started. ``test_cleanup_cannot_outlast_the_verbs_timeout`` holds the worst case under
half the verb's Terraform timeout.

A budget abandons a call without cancelling it, so only a call whose late completion is harmless
may run under one. Both of these qualify. A late poll is a read. A late start submits the same
if-exists drop the on-time one would have, of a table named from this run's request id, which
``dqcommon.run_claim`` lets only one execution ever hold; if it lands in a later invocation of the
container, it finishes the cleanup this run wanted and can reach no other run's table.

The service name is the control plane, not the function: one data-quality run is nine
invocations, and they are only one queryable set if they share it. The per-verb identity rides as
the ``verb`` field.

Attributes:
  DROP_DEADLINE_SECONDS: How long the drops together may keep starting Athena calls. The worst
    case is this plus one call cap and one poll interval: a poll started just inside the deadline
    may run for the cap, and ``run_ddl`` sleeps once more before the budget refuses the next. It is
    set a few seconds under what the half-timeout line allows, so that line stays a margin rather
    than becoming the budget.
"""

import logging

from cpcommon import athena, budget, clients, observability
from cpcommon import config as cpconfig
from dqcommon import messages, notify, results, sql

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="data-quality")

DROP_DEADLINE_SECONDS = 20


@observability.step("drop-table")
def _drop(database: str, table: str, output_location: str, calls: budget.Budget) -> bool:
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

    The drop is polled only while the shared budget lasts, and that has a cost of its own: a drop
    still running when polling stops is logged as leaked even if Athena completes it moments
    later, because stopping the poll does not stop the statement. That errs toward a false alarm,
    and the recovery is an if-exists drop, which is harmless on a table already gone; erring the
    other way is the Lambda timeout the budget exists to prevent. A drop reached once the budget
    is spent is not started at all; that table really is left behind, and is logged the same way.

    Args:
      database: The database the table lives in.
      table: The table to drop.
      output_location: The ``s3://`` results prefix for the DDL statement.
      calls: The budget every Athena call of every drop in this invocation runs under.

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
            client=clients.athena_bounded(),
            call=calls.call,
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


def _targets(event: dict) -> tuple[str | None, list[str]]:
    """Resolves the database and table names this run may have left behind.

    The create verb's OUTPUT carries them, and on every path where it returned they are read
    straight off the state. On the path where it did not, they are re-derived — and that half is
    the point of this function. A Catch merges its error under ``$.error`` and keeps the state
    that went INTO the failed state, so a create that built the typed table and then died —
    raw-table DDL refused, or the invocation killed between the two — hands cleanup a state with
    no names in it at all. Read-only, that is a silent no-op over a table that exists, which
    shows up in the user's own schema rail and eventually collides with a real table name.

    Re-derivation is safe because both verbs build the names and the database from the same
    ``dqcommon.sql`` helpers, so there is no second derivation to disagree with.

    ``manifestKey`` is what says the create verb was reached: inspect-source is the only writer
    of it and the create verb requires it, so its presence means the run got at least as far as
    the state that creates tables. A failure before that — a validator refusal, an inspection
    refusal, the overwhelmingly common case — carries no manifest key and stays the clean no-op
    it is. Should some later change put the key in the state earlier, this errs toward two
    if-exists drops over tables that were never built, which costs a statement and is correct.

    Args:
      event: The task input, carrying the space, the actor and whatever the run reached.

    Returns:
      The database (or None) and the table names to drop, in typed-then-raw order.

    Raises:
      None.
    """
    named = [name for name in (event.get("tempTable"), event.get("tempRawTable")) if name]
    if named:
        return event.get("database"), named

    if not event.get("manifestKey") or not event.get("requestId"):
        return event.get("database"), []

    request_id = event["requestId"]
    database = event.get("database") or sql.temp_database(event.get("space") or {}, event.get("actor"))
    derived = [sql.temp_table_name(request_id)]
    if event.get("format") == "csv":
        derived.append(sql.raw_table_name(request_id))
    return database, derived


def _cleanup(event: dict) -> dict:
    """Drops whichever temp tables the run created and threads the outcome onward.

    A run with no database and no tables to name was reached before the tables could have been
    created. Nothing to do is the correct outcome there, so it is recorded as a clean no-op. The
    dropped and failed tables are named rather than only counted, because recovering a leaked
    table means running a drop by hand and a count does not say which one.

    Args:
      event: The task input, carrying the database and any temp table names.

    Returns:
      The event with the cleanup outcome attached.

    Raises:
      None.
    """
    database, tables = _targets(event)

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

    calls = budget.Budget(DROP_DEADLINE_SECONDS, f"dropping the temp tables in {database}")
    dropped, failed = [], []
    for table in tables:
        (dropped if _drop(database, table, ddl_output, calls) else failed).append(table)

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
