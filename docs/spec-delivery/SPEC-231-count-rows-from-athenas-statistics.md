# Completed Spec — SPEC-231: Count a Result's Rows from Athena's Own Statistics, Not by Walking Every Page

## What was completed?

- **The Query workspace's total row count is Athena's own**, read in one call that scans nothing,
  where it used to fetch every page of the result. That was a billed API call and its preflight per
  1,000 rows: about 10,000 calls, and 1.7 hours, for a 10-million-row result. The total stays
  **exact and never capped** (Andrew, 2026-09-10).
- **API:** `GET /v1/queries/{queryExecutionId}/row-count` (`athena.rowCount`, user plane,
  idempotent) in `lambdas/api/routes/athena.py::row_count`. It answers `{rowCount, pending}` from
  `GetQueryRuntimeStatistics` → `Rows.OutputRows`, only for a `DML`/`SELECT` at `SUCCEEDED`. It
  proves the execution is the caller's first through `_owned_execution`. `pending` means Athena
  still calls the query unfinished, or has no `OutputRows` for it yet; any other statistics refusal
  is an error.
- **IAM:** `athena:GetQueryRuntimeStatistics` on the portal role's `AthenaQueryExecution` statement
  (`portal-role-analytics.json.tftpl`), on the workgroup.
  `test_catalog_grants_unchanged` and the analytics content test in `test_portal_role_preservation`
  each admit exactly that action. The no-SQL sweep admits exactly one shape: a literal compared with
  `.get("SubstatementType")`.
- **Browser:** `getQueryRowCount`, `QueryRowCount` and `ROW_COUNT_PENDING_DELAYS_MS`, plus a
  rewritten `useResultRowCount`. It asks first, re-asks a pending count on the schedule, and walks
  only where Athena does not count. A failed ask leaves the total missing and never walks.
  `QueryWorkspace` hands the status bar and both pagers **one total**. It is the pager's own count
  once it holds the last page; otherwise it is Athena's count, and only while that count is at least
  the rows loaded. It is a guard against an undercount below what the grid has shown, not proof of
  exactness; Athena's count being exact is what FR-003 measured.
- **Measured before the browser trusted it** (FR-003, `docs/testing/sessions.md`, 2026-09-13).
  The deployed route was polled through the window after SUCCEEDED on 10,000,000, 2,000,000 and
  1,763 rows. Each count was final on the first poll that saw SUCCEEDED, and every answer after it
  was a 200.
- **Docs:** the "GetQueryResults calls are free" premise is corrected. `e2e.md` §4.3 has four
  row-count live checks, and §4.5 rows 5 and 15 are corrected. The `owed.md` defect is closed, the
  register entry is in `docs/decisions/analytics.md` with a Fences clause, and `ARCS.md` marks
  SPEC-080's line superseded.

### Deliberate deviations

- **No cap test.** The brief asked for a walk that must stop at a cap. Andrew ruled the total must
  never be capped, so the guard is instead a walk that is **never issued** when Athena has the
  count. That is a results fake returning a `nextToken` forever, which throws on its 101st call so
  the old hook fails by assertion.
- **The ownership helper is SPEC-232's.** Both specs agreed `owned_results_key`,
  `_owned_execution` and `EXECUTION_NOT_FOUND_DETAIL` byte for byte. SPEC-232 took the lower queue
  ticket and landed first (#730), so this spec's PR 1 rebased onto it and carries none of those.
- **The FR-005 guard reads the pager's current pages.** After a page-size change it re-learns from
  the new pages. It matters only if Athena's count were wrong, which FR-003 measured not to happen,
  so no per-execution high-water mark was added.

## What changed from earlier specs?

- **SPEC-080** `useResultRowCount` no longer walks by default. Its return shape `{total,
  isCounting}` is unchanged.
- **SPEC-087 / SPEC-199:** `QueryResultsRegion` and `QueryResultsMobile` no longer combine
  `totalRowCount ?? results.totalRowCount`; the workspace computes the one total.
- **SPEC-199:** the catalog surface has a seventh route, and `test_path_routing.py`'s count moved
  from 6 to 7.

## Verification

Every local gate was green by exit code before each push: formatter, both linters, both suites with
the coverage gate, mypy, build, bundle check, contract regeneration, the doc, flag, path and queue
validators, and tofu fmt/validate. Each PR had two fresh-context diff reviews in different frames
(#731: security, then execution; #741: execution, then state over time), and every finding was fixed
or answered. FR-003 and `e2e.md` §4.3's four rows were run live on 2026-09-13 (`sessions.md`).
