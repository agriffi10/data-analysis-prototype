# Spec: Multiple SQL Statements in One Editor

**ID:** SPEC-078
**Status:** Draft
**Last Updated:** 2026-07-01
**Depends On:** SPEC-041 (multi-tab editor), SPEC-038 (results pager), SPEC-034/036 (history)

> ⚠️ **Not build-ready.** The user wants to support all three interaction models
> below and has asked to **dive deeper on the display/run model before this is
> implemented.** The *settled* parts (statement splitting, sequential execution,
> stop-on-error, per-statement history) are written as firm FRs; the *unsettled*
> part (which statement's results show, and how "run selection / run current" is
> triggered) is captured in **§ Design decisions to resolve before build**. Resolve
> that section — collapsing it into concrete FRs — before generating an
> implementation plan.

## Overview

Athena's `StartQueryExecution` runs exactly **one** statement per call and rejects a
semicolon-separated batch. Today the editor sends its entire contents as a single
statement, so a user who writes several statements (e.g. a `CREATE TABLE` followed
by a `SELECT`, or a few setup statements before a query) cannot run them together.
Users have asked to **write and run multiple SQL statements in one editor.** This
spec parses the editor into individual statements and runs them **sequentially**
against Athena, threading each through the existing per-tab execution/history
machinery. The remaining product decision — how the user chooses what to run (all
vs. selection vs. current statement) and which result set is displayed — is flagged
for a design pass before build.

## Scope

### In Scope

- Split the active tab's editor text into individual SQL statements, respecting
  string literals, `--`/`/* */` comments, and quoted identifiers (a semicolon
  inside a string is not a separator).
- Run the resulting statements **sequentially** in order, each as its own Athena
  execution, **stopping at the first failure** (later statements do not run).
- Record **one query-history entry per statement executed** (each with its own
  execution id, status, bytes scanned, duration).
- Reflect batch progress in the status bar (e.g. "Statement 2 of 4…") while running.
- Surface a failed statement's error (which statement, and Athena's reason) via the
  existing danger banner; make clear later statements were skipped.
- Preserve single-statement behavior exactly when the editor holds one statement.

### Out of Scope

- Transactional / all-or-nothing semantics — Athena has none; a partial batch can
  leave earlier statements' effects in place (a dropped/created table stays).
- Parallel execution — statements run strictly in order (a later statement may
  depend on an earlier one, e.g. CREATE then SELECT).
- Cross-database targeting rules — inherited from SPEC-077 (fixed personal default
  context + fully-qualified names); this spec does not change execution context.
- Client-side SQL validation/linting beyond splitting.
- The editor/results splitter (SPEC-079) and total-row-count stats (SPEC-080).

---

## Design decisions to resolve before build

These three models are all desired; the deeper design pass must decide how they
combine into one interaction (they are not mutually exclusive — a likely outcome is
"Run all" as the primary button **plus** a "Run selection / current statement"
affordance). Each has UI and results-display consequences:

1. **Run all → show the last result-producing statement.** One primary Run action
   runs every statement top-to-bottom; the results pane shows the last statement
   that returned rows. Simplest; matches most SQL consoles' default.
2. **Run all → show each result set.** Same sequential run, but every
   result-producing statement's output is retained and browsable (e.g. a result-set
   switcher, or one results tab per statement). More build surface (results model
   must hold N result sets, not one).
3. **Run selection / current statement.** Run only the highlighted text, or the
   statement under the cursor, via a separate action/shortcut; "Run all" remains for
   the whole editor. Needs cursor→statement resolution and a second run affordance.

Open points for the design pass: which is the default primary action; whether (2)'s
multiple result sets are tabs, a dropdown, or stacked; how history rows link back to
their statement in the editor; keyboard shortcuts (⌘⏎ today runs the tab); and how
"Stop" behaves mid-batch (cancel the in-flight statement and halt the rest).

---

## Functional Requirements

<!-- FR-001..FR-004 are settled regardless of which display model is chosen.
     FR-005 is intentionally a placeholder to be replaced once the design pass
     resolves the model above. -->

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

### FR-002: Sequential execution, stop on first failure

#### Description:

Run the split statements in order, each as its own Athena execution, waiting for one
to reach a terminal state before starting the next. If a statement fails (or is
cancelled), no subsequent statement runs.

#### Acceptance Criteria:

- [ ] Given N statements that all succeed, all N run in order.
- [ ] If statement k fails, statements k+1…N do not start.
- [ ] A single-statement buffer runs exactly as today.

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

### FR-005: Run model + results display *(to be finalized in the design pass)*

#### Description:

**Placeholder.** Replace with concrete FRs once § Design decisions is resolved —
covering the primary Run action's scope (all vs. selection vs. current), any
secondary run affordance, and exactly which result set(s) the results pane shows.

#### Acceptance Criteria:

- [ ] *(to be written after the design pass)*

---

## Data Model

```ts
// apps/portal/src/features/query/query.types.ts (candidate)
// A batch is the ordered statements parsed from one tab's buffer, plus per-statement
// run state. The exact shape depends on the resolved display model (single vs. many
// result sets) — finalize with FR-005.
export type ParsedStatement = {
  index: number;   // 0-based position in the batch
  sql: string;     // the individual statement text
};

// Per-tab run state (SPEC-041 `TabRun`) extends to a batch:
//   currentIndex, total, and either a single active executionId (models 1/3)
//   or a list of executionIds (model 2).
```

## API / Interface Contract

```ts
// New pure helper (co-located, unit-tested independently of Athena):
splitSqlStatements(buffer: string): ParsedStatement[];

// The workspace's `submit(...)` gains a batch runner that awaits each statement to
// terminal before starting the next (reuses runQuery + the existing poller/finalizer),
// halting on the first non-SUCCEEDED terminal state.
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── query.sql.ts            # add splitSqlStatements (+ tests in query.sql.test.ts)
├── QueryWorkspace.tsx      # batch runner in submit(); progress + failure surfacing
├── QueryStatusBar.tsx      # "Statement k of N" while running a batch
├── SqlEditor.tsx           # (model-dependent) run-selection / run-current affordance
└── *.test.tsx              # splitting, sequential-run, stop-on-error, history-per-stmt
```

## Implementation Phases

### Phase 0: Resolve the design decisions

- Turn § Design decisions into concrete FR-005 criteria (default Run scope, secondary
  affordance, results-display model, mid-batch Stop). **Gate:** do not start Phase 2+
  UI work until this lands.

### Phase 1: Statement splitting (pure)

- Implement + unit-test `splitSqlStatements` (strings, comments, quoted identifiers,
  trailing semicolons, single-statement passthrough).

### Phase 2: Sequential batch runner + per-statement history

- Extend `submit()` to run the parsed statements in order via the existing execution
  machinery, stop-on-failure, one history entry per statement.

### Phase 3: Progress + failure UX (+ resolved run/display model)

- Status-bar batch progress; failure banner naming the statement; implement the
  FR-005 run/display model decided in Phase 0.

### Phase 4: Completion ritual

- Delivery doc, INDEX status, component-inventory row if `splitSqlStatements`/batch
  runner is reusable.
