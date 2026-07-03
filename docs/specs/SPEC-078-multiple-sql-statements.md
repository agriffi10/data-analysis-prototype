# Spec: Multiple SQL Statements in One Editor

**ID:** SPEC-078
**Status:** Completed
**Last Updated:** 2026-07-03
**Depends On:** SPEC-041 (multi-tab editor), SPEC-038 (results pager), SPEC-034/036 (history)

> **Design pass complete.** The run/display model that was previously open is now
> resolved (see **§ Run model (resolved)** and FR-005…FR-007). The settled execution
> mechanics (statement splitting, sequential execution, stop-on-error, per-statement
> history) remain as FR-001…FR-004.

## Overview

Athena's `StartQueryExecution` runs exactly **one** statement per call and rejects a
semicolon-separated batch. Today the editor sends its entire contents as a single
statement, so a user who writes several statements (e.g. a `CREATE TABLE` followed
by a `SELECT`, or a few setup statements before a query) cannot run them together.
Users have asked to **write and run multiple SQL statements in one editor.** This
spec parses the editor into individual statements and runs them **sequentially**
against Athena, threading each through the existing per-tab execution/history
machinery.

Two user-facing concepts are introduced:

1. **Three explicit run scopes** the user chooses between — **Run Statement** (the
   selection, or the statement under the cursor, or the sole statement), **Run Script
   → single result** (run the whole file, show the last result-producing statement),
   and **Run Script → tab per statement** (run the whole file, keep every result set
   in its own result tab). This mirrors how established SQL clients separate
   "run current statement" from "run script."
2. **Result tabs** — the results region gains tabs so that when a run produces more
   than one result set (the per-statement scope), each statement's output is
   independently viewable after the batch finishes.

## Scope

### In Scope

- Split the active query tab's editor text into individual SQL statements, respecting
  string literals, `--`/`/* */` comments, and quoted identifiers (a semicolon
  inside a string is not a separator).
- Run the resulting statements **sequentially** in order, each as its own Athena
  execution, **stopping at the first failure** (later statements do not run).
- Record **one query-history entry per statement executed** (each with its own
  execution id, status, bytes scanned, duration).
- Reflect batch progress in the status bar (e.g. "Statement 2 of 4…") while running.
- Surface a failed statement's error (which statement, and Athena's reason) via the
  existing danger banner; make clear later statements were skipped.
- **Three run scopes** exposed as distinct affordances (buttons + keyboard
  shortcuts): Run Statement (primary, ⌘⏎), Run Script → single result, Run Script →
  tab per statement.
- **Statement resolution** for Run Statement: run the selection if there is one,
  else the statement under the cursor, else the sole statement.
- **Result tabs** in the results region: one tab per result-producing statement in
  the per-statement scope; a single result view for the single-result scopes. Each
  result tab owns its own grid, pager (SPEC-038), and stats (SPEC-080).
- Preserve single-statement behavior exactly when the editor holds one statement (a
  bare ⌘⏎ runs it and shows one result, as today).

### Out of Scope

- Transactional / all-or-nothing semantics — Athena has none; a partial batch can
  leave earlier statements' effects in place (a dropped/created table stays).
- Parallel execution — statements run strictly in order in **every** scope (a later
  statement may depend on an earlier one, e.g. CREATE then SELECT). (Note: some tools
  run their "separate tabs" mode in parallel; we deliberately do not.)
- Cross-database targeting rules — inherited from SPEC-077 (fully-qualified names, no
  active-database context); this spec does not change execution context.
- Client-side SQL validation/linting beyond splitting.
- A dedicated result view/tab for **non-result-producing** statements (DDL/DML such
  as `CREATE`/`INSERT`) — their outcome lives in history + the status bar; they do
  not create a grid tab.
- Persisting result tabs across page reloads — result tabs are ephemeral per run
  (cleared when the next run starts), unlike the editor query tabs (SPEC-041).
- The editor/results layout presets (SPEC-079) and total-row-count stats (SPEC-080),
  though result tabs must compose with both.

---

## Run model (resolved)

Established SQL clients converge on separating **run one statement** from **run the
whole script**, with multiple result sets shown either collapsed into one pane or one
tab per statement:

- **DBeaver** — *Execute SQL Statement* (Ctrl+Enter, cursor/selection, one result),
  *Execute SQL Script* (all statements, results stacked in one tab), *Execute
  Statements in Separate Tabs* (one result tab per statement).
- **DataGrip** — run-current-statement by default; results open in per-statement
  tabs (configurable to reuse a tab).
- **MySQL Workbench** — *Execute Current Statement* (Ctrl+Enter) vs *Execute All or
  Selection* (Ctrl+Shift+Enter).

This spec adopts that convention with three scopes:

| Scope | Trigger | Runs | Results |
|---|---|---|---|
| **Run Statement** (default) | ⌘⏎ / primary Run button | the selection, else the statement under the cursor, else the sole statement | one result view |
| **Run Script → single result** | secondary button / ⌘⇧⏎ | all statements, sequential, stop-on-error | the **last result-producing** statement's rows |
| **Run Script → tab per statement** | secondary button / ⌘⌥⏎ | all statements, sequential, stop-on-error | **one result tab per result-producing statement** |

All three scopes share the same execution mechanics (FR-001…FR-004): sequential
execution, stop-on-first-failure, one history entry per executed statement, and batch
progress/failure surfacing. Shortcuts above are the intended defaults; the **buttons**
are the firm requirement.

---

## Functional Requirements

### FR-001: Statement splitting

#### Description:

Parse an editor buffer into an ordered list of individual statements. A semicolon
terminates a statement **only** when it is not inside a single-/double-quoted string
or a comment; empty statements (whitespace/comment-only) are dropped.

#### Acceptance Criteria:

- [ ] `A; B; C` → three statements `A`, `B`, `C`.
- [ ] A semicolon inside a string literal (e.g. `SELECT ';'`) does not split.
- [ ] A semicolon inside a `--` line or `/* */` block comment does not split.
- [ ] A trailing semicolon / trailing whitespace yields no extra empty statement.
- [ ] A single statement with no semicolon yields exactly one statement (unchanged
      behavior).
- [ ] Each parsed statement retains its **source offset range** in the buffer (so the
      cursor/selection can be mapped to a statement for FR-006).

### FR-002: Sequential execution, stop on first failure

#### Description:

Run the statements in scope in order, each as its own Athena execution, waiting for
one to reach a terminal state before starting the next. If a statement fails (or is
cancelled), no subsequent statement runs.

#### Acceptance Criteria:

- [ ] Given N statements that all succeed, all N run in order.
- [ ] If statement k fails, statements k+1…N do not start.
- [ ] A single-statement buffer runs exactly as today.
- [ ] **Stop** mid-batch cancels the in-flight statement and halts the remainder (no
      further statements start).

### FR-003: One history entry per executed statement

#### Description:

Each statement that starts execution appends its own query-history entry (its SQL,
execution id, terminal status, bytes scanned, duration).

#### Acceptance Criteria:

- [ ] Running a 3-statement batch that succeeds adds 3 history entries.
- [ ] A batch that fails at statement 2 adds entries for statements 1 and 2 only.
- [ ] Each entry's stored SQL is that single statement, not the whole buffer.

### FR-004: Batch progress + failure surfacing

#### Description:

While a batch runs, the status bar indicates progress across the batch; a failure is
surfaced with which statement failed and Athena's reason, and indicates that later
statements were skipped.

#### Acceptance Criteria:

- [ ] The status bar shows the current statement index and total while running
      (e.g. "Statement 2 of 4").
- [ ] On failure, the error banner names the failing statement's position and shows
      Athena's `stateChangeReason`.
- [ ] The banner (or status) makes clear remaining statements did not run.

### FR-005: Three run scopes

#### Description:

The workspace exposes three distinct run affordances. Run Statement is the primary
action (bound to the existing ⌘⏎). The two Run Script actions run the whole file and
differ only in how results are displayed (single result vs. tab per statement). All
three obey FR-002’s sequential/stop-on-error mechanics.

#### Acceptance Criteria:

- [ ] There are three visible, separately-labeled run affordances: **Run Statement**,
      **Run Script (single result)**, **Run Script (tab per statement)**.
- [ ] **Run Statement** runs exactly the FR-006 resolved statement(s) and shows a
      single result view.
- [ ] **Run Script (single result)** runs every statement sequentially and the result
      view shows the **last statement that produced rows**; if no statement produced
      rows, the result view is empty and the status bar reflects completion.
- [ ] **Run Script (tab per statement)** runs every statement sequentially and
      produces the result tabs of FR-007.
- [ ] ⌘⏎ triggers Run Statement (unchanged primary shortcut); the two script scopes
      are reachable by button (and, if implemented, ⌘⇧⏎ / ⌘⌥⏎).
- [ ] While any run is in flight, all three affordances are disabled/replaced by Stop
      (per FR-002).

### FR-006: Statement resolution for Run Statement

#### Description:

Run Statement resolves what to execute from the editor state: a non-empty selection
wins; otherwise the statement under the cursor; otherwise, if the buffer holds exactly
one statement, that statement.

#### Acceptance Criteria:

- [ ] With a non-empty selection, Run Statement executes the selected text (split per
      FR-001 and run sequentially if it spans multiple statements, showing the last
      result-producing one).
- [ ] With no selection and multiple statements, Run Statement executes the statement
      whose source range (FR-001) contains the cursor.
- [ ] With no selection and exactly one statement in the buffer, Run Statement
      executes that statement (today’s behavior).
- [ ] With the cursor in the whitespace between statements, resolution falls back
      to the nearest preceding statement (or the sole statement) rather than erroring.
      (A comment between statements attaches to the statement it precedes — the
      cursor inside it resolves to that following statement. Amended at
      implementation: leading comments are part of a statement's source range,
      matching how established clients attach them.)

### FR-007: Result tabs

#### Description:

The results region gains a tab strip. In the per-statement scope each
**result-producing** statement gets its own result tab, in execution order; the user
switches tabs to view each statement’s output after the batch finishes. Single-result
scopes render a single result with no tab chrome (or one implicit tab). Result tabs
are ephemeral: a new run clears the prior run’s tabs.

#### Acceptance Criteria:

- [ ] Run Script (tab per statement) over a batch with M result-producing statements
      yields M result tabs, ordered by execution order.
- [ ] Each result tab owns its own grid, pager (SPEC-038), and row-count stats
      (SPEC-080); paging one tab does not affect another.
- [ ] Tabs are labeled to identify their statement (e.g. index and a short hint), and
      the active tab is visually indicated.
- [ ] Non-result-producing statements (e.g. `CREATE`/`INSERT`) do **not** create a
      result tab; their outcome remains in history + the status bar.
- [ ] Run Statement and Run Script (single result) show a single result view (no
      multi-tab strip).
- [ ] Result tabs belong to the active **query tab** (SPEC-041) and are cleared when a
      new run starts; switching query tabs does not leak result tabs between them.
- [ ] A batch that fails partway shows result tabs for the statements that produced
      rows before the failure, plus the FR-004 failure surfacing.

---

## Data Model

```ts
// apps/portal/src/features/query/query.types.ts (candidate)
export type ParsedStatement = {
  index: number;        // 0-based position in the batch
  sql: string;          // the individual statement text
  range: { start: number; end: number }; // source offsets in the buffer (FR-006)
};

export type RunScope = 'statement' | 'script-single' | 'script-tabs';

// One result set produced by a statement in a batch (drives a result tab).
export type ResultTab = {
  statementIndex: number;   // which ParsedStatement produced it
  executionId: string;      // its Athena execution
  label: string;            // tab label (index + short hint)
  // + the existing per-result grid/pager/stats state (SPEC-038/080)
};

// Per-query-tab run state (SPEC-041 `TabRun`) extends to a batch:
//   scope: RunScope; currentIndex; total; executionIds: string[];
//   resultTabs: ResultTab[]; activeResultTabIndex: number.
```

## API / Interface Contract

```ts
// Pure helpers (co-located, unit-tested independently of Athena):
splitSqlStatements(buffer: string): ParsedStatement[];
resolveRunStatements(
  statements: ParsedStatement[],
  selection: { start: number; end: number } | null,
  cursor: number,
): ParsedStatement[];   // FR-006: selection → cursor stmt → sole stmt

// The workspace's submit(...) takes a RunScope and runs the resolved statements
// sequentially (reusing runQuery + the existing poller/finalizer), halting on the
// first non-SUCCEEDED terminal state. For 'script-tabs' it accumulates a ResultTab
// per result-producing statement; for 'statement'/'script-single' it keeps the
// single (last result-producing) result set.
submit(scope: RunScope): Promise<void>;
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── query.sql.ts            # splitSqlStatements + resolveRunStatements (+ query.sql.test.ts)
├── QueryWorkspace.tsx      # scope-aware submit(); progress + failure surfacing
├── QueryToolbar.tsx        # three run affordances (buttons + shortcuts)  [or in QueryWorkspace]
├── ResultTabs.tsx          # result-tab strip + active-tab switching (+ .test.tsx)
├── QueryStatusBar.tsx      # "Statement k of N" while running a batch
├── SqlEditor.tsx           # expose selection/cursor for statement resolution
└── *.test.tsx              # splitting, resolution, sequential-run, stop-on-error,
                            #   history-per-stmt, result-tab construction
```

## Implementation Phases

### Phase 1: Statement splitting + resolution (pure)

- Implement + unit-test `splitSqlStatements` (strings, comments, quoted identifiers,
  trailing semicolons, single-statement passthrough, source ranges) and
  `resolveRunStatements` (selection / cursor / sole statement).

### Phase 2: Sequential batch runner + per-statement history

- Extend `submit(scope)` to run the resolved statements in order via the existing
  execution machinery, stop-on-failure, one history entry per statement; mid-batch
  Stop cancels the in-flight statement and halts the rest.

### Phase 3: Run scopes (buttons + shortcuts)

- Wire the three affordances (Run Statement = ⌘⏎ primary; the two script scopes as
  buttons + optional ⌘⇧⏎ / ⌘⌥⏎); Run Statement uses `resolveRunStatements`.

### Phase 4: Result tabs

- `ResultTabs` strip; accumulate a `ResultTab` per result-producing statement in the
  `script-tabs` scope; single result view for the other scopes; each tab owns its own
  pager/stats; ephemeral per run and scoped to the active query tab.

### Phase 5: Progress + failure UX

- Status-bar batch progress ("Statement k of N"); failure banner naming the failing
  statement and Athena's reason; partial-batch result tabs shown alongside the error.

### Phase 6: Completion ritual

- Delivery doc, INDEX status, component-inventory rows for reusable pieces
  (`splitSqlStatements`, `resolveRunStatements`, batch runner, `ResultTabs`), and the
  SPEC-074 Help content sweep (new run scopes + result tabs are user-facing).
