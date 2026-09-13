# Spec: Count a Result's Rows from Athena's Own Statistics, Not by Walking Every Page

**ID:** SPEC-231
**Status:** In Progress
**Last Updated:** 2026-09-10
**Depends On:** SPEC-080, SPEC-199

## Overview

The Query workspace's status bar shows a succeeded query's exact total row count ("10,000,000
rows"). It gets that number by fetching **every page** of the result, 1,000 rows at a time, and
counting them. SPEC-080 shipped that walk with a 100,000-row ceiling; the ceiling came off in #214
so the total would always be exact, on the premise, still written in the hook's JSDoc, that
*"Athena's GetQueryResults calls are free"*. That was true while the browser called Athena
directly. Since SPEC-199 put the catalog behind the API, every page is a billed Lambda invocation
on an internet-facing API, a page of rows shipped to the browser only to be counted, and a set of
log records. A 10-million-row result is about 10,000 of them, walked over about 1.7 hours, and the
walk stops only when the user leaves the page.

Athena already knows the answer. `GetQueryRuntimeStatistics` reports `Rows.OutputRows`, the number
of rows the query returned, in one call that scans nothing. This spec adds an API route that reads
it, and the status bar asks that route instead of walking. **The total stays exact**. Andrew set
that constraint on 2026-09-10: the number shown must be the true total, never an estimate and never
capped. So where Athena does not count (statements such as `SHOW TABLES`, whose outputs are small),
the browser still counts by walking, exactly as today.

### What was measured, and how

All readings are from production on 2026-09-10 and are read-only, except one query run through
the portal.

**The walk's cost.**
- A 10,000,000-row query (`UNNEST(sequence(1,2000)) CROSS JOIN UNNEST(sequence(1,5000))`, 0 bytes
  scanned) was walked at about 1.6 pages a second. The gateway's access log shows 215 calls in
  132 seconds, ending when the page was left.
- **Each walked page costs two Lambda invocations and four log-queue messages.** The `GET`
  logs a start and an end record, and so does the CORS preflight in front of it. The `$default`
  route sends every `OPTIONS` to the Lambda. The browser's preflight cache is keyed by URL, and each
  page's URL carries a new `nextToken`, so no preflight is ever reused. On the day, 2,493 GETs
  arrived with 2,486 preflights.

**The walk's share of the log backlog.** Measured from the `AWS/SQS` metrics on `dat-prod-logs.fifo`,
the API gateway's access log and `logs/service=api/`:
- Between 14:00 and 17:15 EDT the queue grew from 38 visible messages to 19,051.
- The walk wrote 9,950 of the 42,714 messages sent in that window (23%), and 5,476 of 8,288 (66%)
  during the steepest climb, 14:35–14:50.
- 2,404 of the 2,493 walked pages came from 11 executions of 20 or more pages. The largest walked
  1,359 pages.
- **Inferred, not measured:** net of the sweep's drain, the walk accounts for about half of the
  backlog's growth.

The pipeline would still have saturated without the walk. About 30% of the window's messages were
the log sweep logging its own capped runs into the queue it drains. That is a separate defect and is
out of scope here.

**`OutputRows` is the result's row count, not the dataset's, and it is exact.**

| Execution | Statement | Rows read | `OutputRows` |
|---|---|---|---|
| `c43cdd33` | the 10M `UNNEST` generator | 0 | **10,000,000**, the count by construction |
| `f394c835` | `SELECT job_title, avg(…) … GROUP BY job_title` | 5,000 | **12** |
| `1c82356c` | two `COUNT_IF` aggregates | 151 | **1** |
| `38b194b6` | `GROUP BY GROUPING SETS ((), ("$path"))` over one file | — | **2** |
| `56f487cd` | `SELECT * … ORDER BY`, no `LIMIT` | 2,012,907 | **2,012,907** (the one shape where result and dataset agree) |

**While a query runs, Athena refuses the statistics call, so it never reports a partial count.**
The 10M query was re-run through the portal (`bf22435c`, submitted 21:25:19.9 EDT, completed
21:25:28.1). Before completion the statistics call was refused outright: *"Query has not yet
finished. Current state: RUNNING"* (`INVALID_QUERY_EXECUTION_STATE`). About 2 seconds after
completion it read 10,000,000, and it read the same 4 seconds later.

**Where Athena's count is not the grid's count — the reason the rule is `SELECT`, not DML.**
Each statement below was run through the portal on 2026-09-10 (0 bytes scanned), and each was
compared with the rows the status bar showed from today's walk:

| Statement | `StatementType` / `SubstatementType` | Grid rows | `OutputRows` |
|---|---|---|---|
| `WITH t AS (…12345…) SELECT x FROM t WHERE x % 7 = 0` | `DML` / `SELECT` | 1,763 | **1,763** |
| `VALUES (1), (2), (3)` | `DML` / `SELECT` | 3 | **3** |
| `EXPLAIN SELECT …` | `DML` / **`EXPLAIN`** | 20 | **1** |
| `EXPLAIN ANALYZE SELECT …` | `DML` / **`EXPLAIN`** | 24 | **1** |
| `DESCRIBE agriffith.employees` | `UTILITY` / `DESCRIBE_TABLE` | — (failed) | — |

**A rule that trusted any DML would show "1 row" over a 20-row `EXPLAIN` plan.** A census of all
552 executions the workgroup still holds (2026-08-02 to 2026-09-10) found only these pairs:
`DML/SELECT` (383, each one beginning with `SELECT`), `DDL/CREATE_TABLE`, `DDL/DROP_TABLE`,
`DDL/CREATE_VIEW`, `DDL/CREATE_TABLE_AS_SELECT` (its `OutputRows` was 1, over 1,990 rows read),
`UTILITY/SHOW_CREATE_TABLE`, `UTILITY/SHOW_CREATE_VIEW` and `UTILITY/SHOW_TABLES`. Every `UTILITY`
and `CREATE_VIEW` it checked returned the `Timeline` block only, with no `Rows`, and so did
`CREATE TABLE`.

**Where Athena does not count.** Those statements return no `Rows` at all. AWS also documents
that row statistics are filled in asynchronously after completion. They "may not be returned in
some cases", and they are absent when a query has Lake Formation row-level filters. **This
deployment defines none**: there is no data-cells filter anywhere in `infra/`.

**The ownership proof can run before the state check.** `GetQueryExecution` carries
`ResultConfiguration.OutputLocation` while an execution is `RUNNING`. It was read on `1666634b`
4 s after submission, and also on `f6b9c166`, which failed at planning. So a user's own running
query answers 409 rather than 404. `QUEUED` lasts about 100 ms, so it was not caught here. SPEC-232's
session measured it: four executions read in the same process, and all eight `QUEUED` reads
carried the location.

### The decisions, made while authoring

- **Exact, always** (Andrew, 2026-09-10). SPEC-080's ceiling is not restored and no "N+" final
  state is introduced. The walk survives as the exact fallback for whatever Athena does not count.
  The brief's "a walk that must stop at a cap" becomes a walk that is **never issued** when Athena
  has the count. That is the test that fails on the old unbounded walk (FR-004).
- **Athena's count is trusted only for a `SELECT` at `SUCCEEDED`.** The route reads
  `GetQueryExecution` first. It answers only when the state is `SUCCEEDED` and `SubstatementType`
  is `SELECT`, which covers `WITH` and `VALUES` (measured above). `EXPLAIN` is DML too, and its
  `OutputRows` of 1 is not the grid's plan rows. `INSERT`, CTAS and `UNLOAD` report rows written or
  a summary row. For all of those the route says Athena does not count, and the browser walks as
  today.
- **A pending count is asked again, never walked.** If a `SELECT` has `SUCCEEDED` but its statistics
  have not landed, the browser asks again after 1, 2, 4, 8, 15 and 30 seconds, which is seven calls
  across about a minute. The one reading so far found the count present about 2 seconds after
  completion, and FR-003 measures the window properly. Only if Athena still has not answered after
  the last ask does the browser walk, which the documented "may not be returned" case needs for the
  total to stay exact.
- **The first number after `SUCCEEDED` is measured to be final before the browser trusts it.**
  Only the `RUNNING` refusal and one reading at +2 s have been observed, so the 0–2 s window after
  completion, where the browser's first request lands, is unmeasured. The browser caches the count
  for the session, so a partial count there would stay on screen with nothing to correct it. FR-003
  polls the deployed route every 200 ms through that window before any browser code calls it.
- **The total shown never contradicts the grid.** Two invariants cost nothing to enforce in the
  browser, and they hold whatever Athena does. Once the pager has loaded the last page, its own count
  is the total, because it counts the rows the grid actually has. A count smaller than the rows
  already loaded is not a total and is not shown (FR-005).
- **Reading Athena's classification is not inspecting SQL.** The API has a sweep,
  `test_no_route_module_inspects_sql`, that fails any route module whose string literals name a SQL
  keyword. Comparing `SubstatementType` with `"SELECT"` reads a field Athena computed from the
  statement, which is the opposite of parsing one. So the sweep admits exactly one shape: a literal
  that is a direct operand of a comparison with a `.get("SubstatementType")` read. A fixture shows
  that shape stays silent, and that a SQL literal anywhere else in the same module still fails.
- **A failed row-count request leaves the total unknown; it does not fall back to the walk.** The
  status bar keeps the loaded-count form it shows while counting ("100+ rows"). A walk-on-error
  would silently restore the full cost whenever the route regressed, behind a screen that looks
  right.
- **The route proves the execution is the caller's own.** Athena authorizes these reads by
  workgroup and there is one, so without a check any user could read any execution's count by id.
  The proof is the one results-conversion uses: the recorded output location sits under the
  caller's own results prefix and carries no dot segment. An unknown id and a foreign one get the
  same **404 `NotFound`**, so the route is not an existence oracle. The proof is written once and
  shared. `cpcommon.results.owned_results_key(location, bucket, username)` holds it, and
  `_owned_execution(context, client)` in `routes/athena.py` wraps it with one `GetQueryExecution`
  on the route's own client and the 404.

  > **Superseded in part by SPEC-232 (#730, 2026-09-13), which landed first:** the helper, its
  > tests and the shared-layer row are SPEC-232's, byte for byte what this spec agreed with it.
  > `status`, `stop` and `results` run the same proof first, and results-conversion calls the same
  > helper. This spec's route calls `_owned_execution` like the others and adds none of those
  > pieces; `TestEveryRouteNamingAnExecutionProvesItFirst` covers it by its path.
- **The row count stays on the user plane.** The route calls Athena as the caller, like every
  `/v1/queries` route, so the per-user role gains `athena:GetQueryRuntimeStatistics` on the
  workgroup. That is AWS's documented resource for the action. It is the first catalog action added
  to that role since SPEC-199, so the two guards that freeze it admit exactly this one action
  (FR-002).
- **Two code PRs, split at the inert-versus-live seam, because the measurement needs one.** The
  first ships the route and the grant with no browser caller. FR-003 runs against it once deployed.
  The second switches the browser over, only if FR-003 passes. The split also settles deploy order:
  the grant and the route are live before anything asks them.

## Scope

### In Scope

- A `GET /v1/queries/{queryExecutionId}/row-count` route, its contract entry, the regenerated
  browser contract, and the no-SQL sweep's one admission.
- `athena:GetQueryRuntimeStatistics` on the per-user analytics role, and the two IAM guards
  admitting it.
- A measurement of the route through the window after `SUCCEEDED`, before the browser uses it.
- `useResultRowCount` asks the route and walks only where Athena does not count. The workspace
  shows a total that never contradicts the grid. The JSDoc premise of `useResultRowCount` and
  `ROW_COUNT_PAGE_SIZE` is corrected.
- A live check in `e2e.md` §4.3 for the 10M-row query, a known-count filter, and two statements
  Athena does not count. §4.5's rows 5 and 15 are corrected, and `owed.md`'s defect row is updated.

### Out of Scope

- **The Data Explorer.** Checked: it pages only on **Next** (`useQueryResults.goNext`), never
  mounts `useResultRowCount`, and shows *"Rows a–b"* with no total. Nothing in it walks.
- **The results pager** (`useQueryResults`). It is user-driven, one page per gesture, and
  unchanged. Only the precedence of the total the workspace hands it changes (FR-005).
- **A `COUNT(*)` wrapper.** It re-scans the data and costs money, where this spec is free.
- **The preflight per request.** Every distinct URL gets its own preflight, and the `$default`
  route sends each one to the Lambda. That is a cost on every paged API call, not only this one, and
  a different change (answering `OPTIONS` at the gateway, or a stable URL shape).
- **The log sweep logging into its own queue** (about 30% of the backlog window). A separate defect.
- ~~**Ownership checks on `status` and `stop`.** These are recorded pre-existing exposures.~~
  Closed by SPEC-232 (#730), which landed before this spec.
- **Any change to what the status bar says.** "1,234 rows" once known, and the loaded-count form
  while counting. Help & guides already say "the exact total row count", which stays true.

---

## Functional Requirements

### FR-001: The API reports a succeeded SELECT's row count from Athena's statistics

#### Description:

`GET /v1/queries/{queryExecutionId}/row-count` (`athena.rowCount`, user plane, idempotent) answers
`{rowCount, pending}`.
- It reads `GetQueryExecution` as the caller. An execution that is unknown, or whose output is not
  under the caller's own results prefix, gets 404 `NotFound`. One that is not `SUCCEEDED` gets 409
  `QueryNotFinished`.
- For `StatementType` `DML` with `SubstatementType` `SELECT`, it reads `GetQueryRuntimeStatistics`
  and returns `Rows.OutputRows` when present. If the statistics are absent, or Athena still calls
  the query unfinished, it returns `pending: true`.
- For any other statement it returns `{rowCount: null, pending: false}` without reading the
  statistics.
- The span is stamped with `execution_id`, `substatement_type`, and either `row_count` or
  `row_count_pending`. It never carries SQL.
- `test_no_route_module_inspects_sql` admits exactly one shape: a literal that is a direct operand
  of a comparison with a `.get("SubstatementType")` read.

#### Acceptance Criteria:

- [ ] A `SUCCEEDED` `SELECT` whose statistics carry `OutputRows: 10000000` answers
  `{"rowCount": 10000000, "pending": false}`, and one carrying `OutputRows: 0` answers
  `{"rowCount": 0, …}`, so a truthiness test cannot pass. The statistics call is asserted on the
  stub installed as `identity.user_client`, which is the only way the route can reach it; that is
  what proves the user plane.
- [ ] The same execution with `Rows` absent answers `{"rowCount": null, "pending": true}`, and so
  does a statistics call Athena refuses as not finished.
- [ ] `UTILITY` (`SHOW_TABLES`), `DDL` (`CREATE_TABLE`) and a `DML` whose `SubstatementType` is
  `EXPLAIN` all answer `{"rowCount": null, "pending": false}` **and make no statistics call**. The
  `EXPLAIN` case is the measured one: its stub carries `OutputRows: 1`, so a route that keyed on
  `StatementType`, or read the statistics anyway, would answer 1 and fail.
- [ ] A statistics error other than "not finished" is **not** turned into `pending`.
  `AccessDeniedException` answers 403 `AccessDenied`, and an `InvalidRequestException` with an
  unrelated message answers 400 `InvalidRequest`. Once the browser switches over, a dropped grant
  would otherwise become seven asks and then a walk: the silent cost restoration this spec rejects.
- [ ] The span carries `substatement_type`, and either `row_count` or `row_count_pending`, asserted
  on the captured events.
- [ ] A `RUNNING` execution answers **409 `QueryNotFinished`** and makes no statistics call.
- [ ] `owned_results_key` returns the key for an owned location, and `None` for three others:
  another user's prefix, a dot segment, and a non-string. It is tested in
  `test_results_cpcommon.py`. *(Delivered by SPEC-232, #730, which landed the shared helper and
  its tests first.)*
- [ ] Three executions answer **404 `NotFound`** with identical bodies and no statistics call: one
  whose output location is under **another** user's prefix, one whose location carries a dot
  segment, and an id Athena does not know.
- [ ] The route is in `contract.py` and `apiContract.generated.ts`. The generator's tests pass, and
  so does `test_path_routing.py`, whose catalog-route count moves from 6 to 7.
- [ ] `test_every_catalog_response_forbids_a_cache` covers the new route.
- [ ] `test_no_route_module_inspects_sql` passes over the new route. A fixture shows the admitted
  shape stays silent. Another shows three things still redden in the same module: a SQL literal
  returned, a literal compared with the statement, and a literal compared with any other field.

### FR-002: The per-user role may read runtime statistics, and nothing else widens

#### Description:

`AthenaQueryExecution` in `portal-role-analytics.json.tftpl` gains `athena:GetQueryRuntimeStatistics`,
on the same workgroup resource. `test_catalog_grants_unchanged` (which reads each template's
combined action set) admits that one action on that one template. `test_portal_role_preservation`'s
analytics content test (which reads statements by `Sid`) admits that one action on that one
statement. Each admission states its reason where it lives, and each is shown to fail on a plant it
must catch.

#### Acceptance Criteria:

- [ ] The rendered policy grants `athena:GetQueryRuntimeStatistics` on the workgroup ARN, and no
  other statement changes.
- [ ] `test_this_branch_names_no_new_catalog_ACTION` passes, and reddens when a genuinely new
  catalog action (`athena:ListQueryExecutions`) is planted anywhere in the template.
- [ ] The analytics content test passes, and reddens on each of two plants: `AthenaQueryExecution`'s
  `Resource` changed, and a second action added to `AthenaQueryExecution` (`glue:GetTable`, already
  held elsewhere in the template, which is why the combined-set guard cannot see it and this one
  must).
- [ ] The portal role's inline-policy budget test passes.

### FR-003: The first count after SUCCEEDED is final, measured through the deployed route

#### Description:

Once the first PR has deployed, and before any browser code calls the route, a signed-in Chromium
page polls it every 200 ms, alongside `GET /v1/queries/{id}`. Polling starts at submission and
runs until 10 s after the status first reports `SUCCEEDED`. It covers three results: the
10,000,000-row generator, a 2,000,000-row one (`sequence(1,2000)` × `sequence(1,1000)`), and the
1,763-row `WITH` query. Every response is recorded with its timestamp. The result goes in
`docs/testing/sessions.md`, and the spec's evidence is updated with it.

#### Acceptance Criteria:

- [ ] For each of the three, every numeric `rowCount` the route returned equals the last one, and
  the last one equals the known count (10,000,000, 2,000,000 and 1,763).
- [ ] Once the status poll has first reported `SUCCEEDED`, every row-count answer is a 200. A 409
  or 400 in that window would reach the browser as a failed request, and FR-004 caches that as
  "no total" for the session. So a 409 from the route's own `GetQueryExecution` lagging the status
  poll, or a transient refusal, fails this criterion just as a changed number does.
- [ ] The number of `pending: true` answers before the first number, and the time from `SUCCEEDED`
  to the first number, are recorded for each result. The `ROW_COUNT_PENDING_DELAYS_MS` schedule
  reaches the first number within its seven asks on all three.
- [ ] **If any criterion above fails, FR-004 does not ship as written.** That covers four cases: a
  numeric answer differs from a later one, a final answer differs from the known count, a result
  produces no number within the seven asks, or a non-200 follows `SUCCEEDED`. A run that sees only `pending` or refusals has
  measured nothing, and fails. The session stops and escalates with the measurement, because a count
  Athena revises after reporting it is not one the browser may cache as exact. The measurement starts
  only after `scripts/watch_ci.py --branch main` has settled green on PR 1's merge commit, because
  the grant's deploy and the route's run in no fixed order.

### FR-004: The status bar's count comes from Athena, and the walk runs only where Athena does not count

#### Description:

`useResultRowCount` asks `getQueryRowCount` first, and a number is the total. A `pending` answer is
asked again after each delay in `ROW_COUNT_PENDING_DELAYS_MS` (1, 2, 4, 8, 15 and 30 s); only after
the seventh ask does the hook walk. `pending: false` with no number walks at once, exactly as today.
A failed request leaves the total `null` and issues no walk. The wait between asks honours the
abort signal, so leaving the page or changing the execution stops both the asking and the walk.
Keys, caching, `isCounting` and the no-error contract are unchanged.

#### Acceptance Criteria:

- [ ] **The test the old walk fails.** The results fake always returns a `nextToken`, and throws on
  its 101st call, so an old-style walk fails by assertion instead of hanging the worker. The
  row-count fake answers `{rowCount: 10000000, pending: false}`, and separately `{rowCount: 0, …}`.
  The total equals the answer, and `getQueryResults` is called **zero** times. The red run against
  today's hook is recorded in the PR.
- [ ] Pending twice, then 1,763: the total is 1,763, `getQueryRowCount` was called three times and
  `getQueryResults` zero times. With fake timers, no third ask happens before 1,000 + 2,000 ms
  have elapsed.
- [ ] Pending on every ask: `getQueryRowCount` is called exactly seven times. No page is walked
  before the 30 s wait has elapsed, and after it the walk reaches the exact total.
- [ ] Unmounting during a pending wait, and changing the execution id during one, each leave no
  further `getQueryRowCount` call and no walk for the old id after the timers are run out.
- [ ] `pending: false` with no number walks every page to the exact total. A failed row-count call
  leaves `total` null with `getQueryResults` never called.
- [ ] The workspace suites that render `QueryWorkspace` (`QueryWorkspace.test.tsx`,
  `queryWorkspaceMobile.test.tsx`, `queryWorkspaceDivider.test.tsx` and `gatedSurfaces.test.tsx`)
  mock `getQueryRowCount`, defaulting to "Athena does not count". The gate tests at
  `QueryWorkspace.test.tsx` (the first page in flight, the declined statement, and the DDL test's
  positive control) assert the `getQueryRowCount` call, which is the gate's first request. The DDL
  test asserts neither the route nor the walk is called.

### FR-005: The total shown never contradicts the grid

#### Description:

`QueryWorkspace` computes the one total it hands the status bar and both pagers, from two rules.
First, the pager's own total wins once it is known, meaning the last page is loaded. Second,
failing that, Athena's count is shown only if it is at least the number of rows already loaded.
Otherwise the bar keeps the loaded-count form.

#### Acceptance Criteria:

- [ ] With the pager's last page loaded (3 rows) and the hook answering 5, the status bar and the
  pager both read 3.
- [ ] With 100 rows loaded, more pages pending, and the hook answering 40, the bar reads "100+ rows"
  and the pager shows no total. With the hook answering 10,000,000, both read 10,000,000.

### FR-006: The premise is corrected where it is written, and the change is checked live

#### Description:

The JSDoc of `useResultRowCount` and of `ROW_COUNT_PAGE_SIZE`, and the catalog inventory row, stop
claiming the calls are free. They describe the walk as the fallback, each page of it a billed API
call. `e2e.md` §4.3 gains the live rows. §4.5's row 5 stops calling paging free, and its row 15
loses the row count the Explorer does not have. `owed.md`'s defect row reads "Fixed by SPEC-231,
pending its re-run". `ARCS.md`'s SPEC-080 line is marked superseded in place.

#### Acceptance Criteria:

- [ ] No source file, inventory row or live-check row claims `GetQueryResults` pages are free.
  Closed with `command grep -rn -i "free"` over `features/catalog/`, the inventory and `e2e.md`
  §4.3–4.5, with the output in the PR.
- [ ] `e2e.md` §4.3 has these rows, each run with **Rows per page at its default**:
  - **The 10M-row query** (0 bytes scanned). The bar reads "10,000,000 rows". The network panel
    shows one to seven `GET …/row-count` calls and **zero** `…/results?maxRows=1000`.
  - **`SELECT x FROM UNNEST(sequence(1, 12345)) AS t(x) WHERE x % 7 = 0`.** The bar reads "1,763
    rows", and the last page of the pager ends at row 1,763.
  - **`SHOW TABLES IN <your database>`.** The count is exact and arrives by the walk.
  - **`EXPLAIN SELECT x FROM UNNEST(sequence(1, 10)) AS t(x)`.** The bar reads the plan's own row
    count (20 when this was written), never 1, and it arrives by the walk. This is the row a
    `StatementType`-keyed route would fail.
- [ ] §4.5 row 15 checks the pager's `nextToken` encoding, which is still real, and no longer asks
  for a row count.

---

## Data Model

```python
# lambdas/api/apicommon/contract.py
class QueryRowCountResponse(TypedDict):
    rowCount: int | None   # Athena's OutputRows for a succeeded SELECT; None when it has none
    pending: bool          # True: a SELECT whose statistics have not landed — ask again
```

```ts
// apps/portal/src/features/catalog/catalog.types.ts
export type QueryRowCount = {
  /** Athena's own count of the rows a succeeded SELECT returned; null when it reports none. */
  rowCount: number | null;
  /** A SELECT whose statistics have not landed yet: ask again rather than walk. */
  pending: boolean;
};
```

## API / Interface Contract

```ts
// athena.service.ts
getQueryRowCount(queryExecutionId: string): Promise<ServiceResult<QueryRowCount>>;

// catalog.constants.ts
export const ROW_COUNT_PENDING_DELAYS_MS: readonly number[] = [1_000, 2_000, 4_000, 8_000, 15_000, 30_000];
```

```
GET /v1/queries/{queryExecutionId}/row-count
200 {"rowCount": 10000000, "pending": false}   succeeded SELECT, Athena counted it
200 {"rowCount": null, "pending": true}        succeeded SELECT, statistics not landed yet
200 {"rowCount": null, "pending": false}       Athena does not count this statement — walk it
404 NotFound                                   unknown id, or not the caller's own execution
409 QueryNotFinished                           not SUCCEEDED
```

## File & Folder Structure

```
lambdas/api/
├── apicommon/contract.py            # athena.rowCount route + QueryRowCountResponse
├── router.py                        # route id → handler
├── routes/athena.py                 # row_count()
├── test_athena_routes.py            # FR-001
├── test_catalog_observability.py    # FR-001: no-store list, the sweep's admission + fixtures
└── test_path_routing.py             # FR-001: catalog-route count 6 → 7
lambdas/test_catalog_grants_unchanged.py    # FR-002 admission
lambdas/test_portal_role_preservation.py    # FR-002 admission
infra/modules/analytics/policies/portal-role-analytics.json.tftpl
apps/portal/src/
├── types/apiContract.generated.ts   # regenerated (PR 1)
├── test/queryWorkspaceSupport.tsx   # FR-004: the getQueryRowCount spy and its default
└── features/
    ├── catalog/
    │   ├── athena.service.ts            # getQueryRowCount
    │   ├── catalog.constants.ts         # ROW_COUNT_PENDING_DELAYS_MS; ROW_COUNT_PAGE_SIZE doc
    │   ├── catalog.types.ts             # QueryRowCount
    │   ├── useResultRowCount.ts         # ask Athena, walk only where it does not count
    │   └── queryExecutionHooks.test.ts  # FR-004
    ├── query/QueryWorkspace.tsx         # FR-005: the one total
    ├── query/QueryWorkspace.test.tsx    # FR-004 re-pointing, FR-005
    ├── query/queryWorkspaceMobile.test.tsx, queryWorkspaceDivider.test.tsx
    └── feature-flags/gatedSurfaces.test.tsx
```

## Implementation Phases

### Phase 1: The route and the grant (PR 1, inert)

- `row_count()` in `routes/athena.py`, the contract entry, the router mapping, and the regenerated
  browser contract.
- Route tests for every FR-001 branch, with Athena stubbed at the user-plane client. The sweep's
  admission and its fixtures, the routing count, and the no-store list.
- The IAM action, the two guard admissions and their plants.

### Phase 2: The measurement (after PR 1 deploys)

- FR-003 from a signed-in Chromium page, recorded in `sessions.md`. The spec's evidence is updated
  before phase 3 starts.

### Phase 3: The browser asks first (PR 2)

- `getQueryRowCount`, `QueryRowCount` and `ROW_COUNT_PENDING_DELAYS_MS`. The hook rewrite, with an
  abortable wait.
- The FR-004 hook tests, and the red run of the forever-`nextToken` test against today's hook.
- The FR-005 total in `QueryWorkspace`, and the workspace-suite changes.
- The JSDoc corrections, the inventory row, the `e2e.md` rows, `owed.md` and the `ARCS.md` marker.

### Phase 4: The live check

- After PR 2 deploys, run §4.3's new rows in a signed-in Chromium, record them in `sessions.md`,
  and close the spec.
