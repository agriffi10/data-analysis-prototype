# Completed Spec — SPEC-078: Multiple SQL Statements in One Editor

## What was completed?

The query editor now runs `;`-separated scripts: statements are split client-side (string/comment/
quoted-identifier-aware) and executed **sequentially** against Athena, stopping at the first failure,
with one history entry per statement. Frontend-only (`features/query/`); no service/IAM/infra change.

- **Pure helpers (`query.sql.ts`):** `splitSqlStatements` (FR-001, with source offsets),
  `resolveRunStatements` (FR-006: selection → cursor statement → sole statement),
  `isResultProducingSql` (SELECT/WITH/SHOW/DESCRIBE/VALUES/EXPLAIN ⇒ grid; DDL/DML ⇒ history+status
  only), `statementHint` (tab labels). Types `ParsedStatement`/`RunScope`/`ResultTab` in `query.types.ts`.
- **Batch runner (`QueryWorkspace.tsx`):** `TabRun` extended to the batch shape (scope, statements,
  currentIndex, resultTabs, done/halted/failure); the per-tab `TabExecutionPoller` finalizing
  statement *k* is what starts *k+1* (same poller re-keys to the new execution id). `runsRef` is the
  synchronous source of truth (all writes via `updateRuns`), so **Stop** (`halted`) is visible to an
  in-flight advancement immediately — a statement that outruns the cancel still never starts the next.
- **Three run scopes (FR-005):** primary **Run Statement** (⌘⏎, selection/cursor via new
  `SqlEditorHandle.getSelectionRange/getCursorOffset`), **Run Script (single result)** (⌘⇧⏎, last
  result-producing statement), **Run Script (tab per statement)** (⌘⌥⏎). All replaced by Stop in flight.
- **Result tabs (FR-007, `ResultTabs.tsx`):** WAI-ARIA tablist (QueryTabStrip keyboard model), one tab
  per result-producing statement, ephemeral per run + scoped to the query tab; each tab keeps its own
  pager position (`useQueryResults` page index is now per execution id), column widths, row-count stats,
  and Save-results source (the statement's terminal status, captured per tab at finalize).
- **Progress + failure UX (FR-004):** status bar shows "Statement k of N" while running and
  "Script finished · N statements" on full completion; the danger banner names the failing statement
  and which statements did not run.
- Help & guides: new "Run several statements at once" guide + result-tabs step (SPEC-074 sweep).

## What changed from earlier specs?

- `QueryStatusBar` gained an optional `batch` prop; `SqlEditor` gained two optional script-run props +
  two handle methods. `useQueryResults` no longer resets its page on id change — it remembers the page
  **per execution id** (a new run still starts at page 1; SPEC-038 behavior otherwise unchanged).
- The primary run button is relabeled **Run Statement** (was "Run"); single-statement behavior is
  unchanged (a 1-statement batch is exactly the old path, including the empty-grid-after-DDL view).

## Verification

`format:check`, `tsc`, ESLint, Vitest **980 passed** locally (32 new pure-helper cases covering every
FR-001/FR-006 acceptance bullet; workspace tests for sequential order, stop-on-error, per-statement
history, Stop-mid-batch, result-tab accumulation/clearing; ResultTabs + status-bar batch tests). Live
Athena deferred — `/query` is Cognito-gated; execution mechanics ride the existing SPEC-034/041 poller
covered by the component tests.
