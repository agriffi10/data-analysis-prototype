# Completed Spec — SPEC-080: Total Row Count in Query Stats

## What was completed?

The query status bar now reports a succeeded query's **exact total row count** ("1,384 rows") regardless of
which result page is shown, instead of the loaded-count "N+" form. Frontend-only; no IAM/infra/data-layer change.

- **Background page-walk counter (FR-001/FR-005):** new `useResultRowCount(queryExecutionId)` hook — a `useQuery`
  keyed on `queryKeys.rowCount(id)` (separate from the 20/page visible pager key, so counting never perturbs it),
  `staleTime/gcTime: Infinity` for free reuse on tab-switch-back. Its `queryFn` walks every `GetQueryResults` page
  at `ROW_COUNT_PAGE_SIZE = 1000` (free calls, no extra scan), honors the `AbortSignal` (cancels/recomputes on id
  change), stops at `ROW_COUNT_CEILING = 100_000`, and never surfaces an error (a failed page → `total` stays null).
  Returns `{total, isCounting, atCeiling}`.
- **Status-bar display (FR-002/FR-003/FR-004):** `QueryStatusBar` gained `hasResultSet`/`totalRowCount`/`atRowCeiling`
  props and a `rowCountLabel` helper — exact `toLocaleString()` total once known, today's `loadedRowCount + '+'`
  while counting, `"{ceiling}+ rows"` at the ceiling. `QueryWorkspace` gates the counter on `results.columns.length
  > 0`, so DDL/no-result statements show **no** row-count stat.
- New `formatCount` in `query.format.ts`; `ROW_COUNT_PAGE_SIZE`/`ROW_COUNT_CEILING` in `query.constants.ts`;
  `queryKeys.rowCount`.

### Deliberate deviation (reversible/technical, in-session)

- FR-004's "unchanged from today" parenthetical was slightly off — today a DDL success showed "0 rows". Per the FR's
  explicit acceptance criterion, DDL/no-result now shows **no** row-count segment (scanned + duration still shown).

## What changed from earlier specs?

`QueryStatusBar` gained props (all optional/defaulted — no other call site changed). No signature changes to the
SPEC-034 `getQueryResults` service (reused as-is) or the SPEC-038 pager.

## Verification

`format:check`, `tsc`/`build`, ESLint, and Vitest green (new `useResultRowCount` hook tests: multi-page total,
single-page, empty=0, ceiling, disabled, degrade-on-failure, recompute-on-id-change; new `QueryStatusBar` display
tests). Live browser deferred — `/query` is Cognito-gated and needs live Athena (dev-unauth covers only `/files`),
same limitation as SPEC-040→077.
