---
type: Decision
title: "A result's total is Athena's own count, and only a SELECT's count is the grid's (SPEC-231)"
description: "**A result's total is Athena's `OutputRows`, and only a `SELECT`'s count is the grid's.** A walked page is a billed API call, never \"free\", so the count comes from `GetQueryRuntimeStatistics` in one call, and the exact walk runs only where Athena does not count. `EXPLAIN` is **DML**, and it reports **1** over a many-row plan, so the rule needs `SubstatementType` `SELECT`, never `StatementType` alone — a DML-keyed rule passes every test that uses a real `SELECT`. The total is **never capped** (Andrew's ruling). A pending count walks only after the seventh ask, and a failed ask never walks, so a broken route shows as a missing total, not as the old cost."
---

**The walk was never free once the catalog moved behind the API.** SPEC-080 counted a succeeded
result by fetching every `GetQueryResults` page. That was costless while the browser called Athena
directly; after SPEC-199 every page became a billed Lambda invocation, plus its CORS preflight,
since each page's URL carries a new `nextToken` and the preflight cache is keyed by URL. Four log
records went with every page. A 10-million-row result was about 10,000 pages over about 1.7 hours,
and on 2026-09-10 the walk wrote 23% of the log queue's messages in its saturation window.

**Athena already holds the count.** `GetQueryRuntimeStatistics` → `QueryRuntimeStatistics.Rows.OutputRows`
is the number of rows the query returned, not the rows it read: a `GROUP BY` over 5,000 rows read
reports 12. It costs one call and scans nothing. While a query runs, Athena refuses the call rather
than report a partial count. Measured in production before the browser trusted it, the first number
after `SUCCEEDED` was already final on every run. `GET /v1/queries/{id}/row-count` serves it, on
the user plane, behind `_owned_execution`.

**Only a `DML`/`SELECT`'s count is the grid's count.** `EXPLAIN` and `EXPLAIN ANALYZE` are `DML`
too, labelled `SubstatementType` `EXPLAIN`. Their `OutputRows` is 1 over a plan the grid shows as
twenty or more rows. `SHOW` is `UTILITY` and reports no rows at all (measured; `DESCRIBE` is
`UTILITY` too and is expected to do the same), and CTAS reports a summary row. So the route answers a number only for a `SELECT`. For anything else it answers "not counted",
and the browser counts by the walk, which is exact. `WITH` and `VALUES` are labelled `SELECT`. A
route keyed on `StatementType` passes every test that uses a real `SELECT`. For an `EXPLAIN` it
answers 1, and so the walk is skipped. The workspace's grid guard keeps the bar honest while the
plan fits on one page, since a 1 below the rows loaded is never shown. A longer plan, though, loses
its exact total. The discriminator is the route's answer and the missing `maxRows=1000` call, never
the bar; the guard that fails on it is the `("DML", "EXPLAIN")` case in `test_athena_routes.py`.

**Exact, never capped, and never an estimate** (Andrew, 2026-09-10). A `pending` count is asked
again on a fixed schedule (1, 2, 4, 8, 15, 30 s), and the walk runs only after the seventh ask. A
failed ask leaves the total missing rather than falling back to the walk, so a broken route shows as
"100+ rows", not as a silent return of the cost. The workspace hands every surface one total: the
pager's own count once it holds the last page, otherwise Athena's count, and only while it is at
least the rows already loaded. That guard reads the pager's current pages, so after a page-size
change it starts again from the rows loaded since. It matters only if Athena's count is ever wrong.

**The no-SQL sweep admits reading Athena's classification.** `test_no_route_module_inspects_sql`
fails any route-module literal naming a SQL keyword. It admits exactly one shape: a literal that is
a direct operand of a comparison with a `.get("SubstatementType")` read, which is Athena's answer
about the statement rather than the statement itself.

Measurements: `docs/specs/SPEC-231-count-rows-from-athenas-statistics.md`; the live readings,
`docs/testing/sessions.md` (2026-09-13).

## History

### 2026-09-13

- **Settled:** SPEC-231.
