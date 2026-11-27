---
type: Spec
id: SPEC-272
title: "Typing and Dragging Leave the Query Results and the Rail Alone"
description: "Narrows what a keystroke, a divider drag and a column drag cost in the Query workspace, so none of them re-renders the result rows or the schema rail; coalesces the tabs' session storage writes; keeps the runs context stable; and bounds the parallel reads behind autocomplete and the data-quality list."
spec_status: Draft
depends_on: []
arc: render-scope
arc_order: 2
---

**Dependency notes:** the arc's opening change landed `apps/portal/src/test/renderCounter.tsx`,
which every budget below is counted with. Nothing here needs SPEC-271.

## Overview

In the Query workspace three things change many times a second: the SQL being typed, the height of
the editor while its divider is dragged, and a result column's width while its edge is dragged. All
three are held at the top of the workspace, so each keystroke and each pointer move redraws the
whole page: the schema rail, the tab strip, the toolbar, both drawers, every dialog and every row
of the result, which can be a thousand rows. Measured before this spec on a 200-row by 10-column
result, one keystroke, one divider move and one column move each re-walked 2,986 fibers and
rendered every component on the page. This spec makes each of those gestures cost what it changes,
whatever the size of the result on screen. It also stops the workspace writing every tab to session
storage on every keystroke, and stops opening Query from starting one schema read per database all
at once against an account whose Lambda concurrency is ten.

Nothing a user does changes. Andrew decided on 2026-11-27 that the result grid is memoised, not
windowed, and that the 1,000-row page cap stays.

## Scope

### In Scope

- What a keystroke, a divider move and a column-resize move render in the Query workspace.
- When the Query tabs are written to session storage.
- The identity of the values `QueryRunsProvider` supplies.
- How many schema reads, and how many data-quality index reads, are in flight at once, and how
  soon autocomplete's copy of a schema is read again.
- A render-scope suite for the workspace whose budgets fail when any of the above regresses.

### Out of Scope

- **Windowing the result grid, and the 1,000-row cap.** Andrew's decision: the one-off cost of
  drawing a large page is to be timed on the deployed build before anything is built for it.
- **`features/catalog/ColumnResizeHandle.tsx`.** It is shared with the Data Explorer and neither
  spec of this arc changes it: the drag still reports every pointer move, and the fix is in who
  renders when it does.
- **Where `QueryRunsProvider` is mounted.** It stays at the signed-in shell.
- **The mobile surface.** Below `tablet` there is no editor, no divider and no column handle.
- The Data Explorer, which is SPEC-273 and takes this spec's coalesced writer.

---

## Functional Requirements

### FR-001: A keystroke renders neither the result rows nor the schema rail

#### Description:

The result's rows are drawn by a memoised component, `QueryResultRows`, whose props are the page's
rows and the first row's number. The schema rail is memoised, and everything the workspace hands it
keeps its identity across a keystroke. `useQueryTabs` returns actions whose identity is stable for
the life of the hook.

#### Acceptance Criteria:

- [ ] With a result on screen, typing one character renders `QueryResultRows` zero times and
      `SchemaBrowser` zero times (before this spec the table and the rail both render).
- [ ] The number of fibers a keystroke re-walks is the same with a 20-row result on screen as with
      a 200-row one.
- [ ] Each of those two assertions fails when the memo it rests on is removed (mutation-tested
      once each, recorded in the delivery doc).
- [ ] Run, Clear, Save, the dirty marker and the downloaded `.sql` all still follow the text as
      typed: the existing workspace suites pass with no assertion weakened.

### FR-002: A divider drag renders the split, and nothing above or below it

#### Description:

The editor/results split, its measurement of the column and the editor's re-layout live in one
component beneath the workspace, which receives the editor and the results region as elements. A
pointer move during the drag sets state in that component alone.

#### Acceptance Criteria:

- [ ] One pointer move during a divider drag renders `QueryWorkspace` zero times,
      `QueryResultRows` zero times and `SchemaBrowser` zero times.
- [ ] The editor pane's height, the divider's `aria-valuenow` and `aria-valuetext`, and Monaco's
      re-layout still follow each pointer move at once, and the split is still stored once, on
      release: `queryWorkspaceDivider.test.tsx` passes with no assertion weakened.
- [ ] A session that starts below `tablet` and widens still measures the column and can move the
      divider.

### FR-003: A column-resize drag renders the table's header, and no row

#### Description:

A result's column widths are held beneath the workspace, in a component that stays mounted across
paging, query-tab switches and result-tab switches, so a user's widths still survive all three.
The rows do not depend on the widths, which reach the table through its `<colgroup>`.

#### Acceptance Criteria:

- [ ] One pointer move during a column-resize drag renders `QueryWorkspace` zero times,
      `QueryResultRows` zero times and `SchemaBrowser` zero times, and the `<col>` for that column
      carries the new width.
- [ ] A width set by the keyboard survives Next and Prev, a switch to another query tab and back,
      and a switch between result tabs; a new run starts from the defaults. The existing
      width-persistence case passes with no assertion weakened.
- [ ] Widths are in memory only, as today: a reload, leaving the route, or crossing below `tablet`
      and back starts from the defaults. The last of the three is new, and accepted: there is no
      table below `tablet`.

### FR-004: The tabs are written to session storage once per pause, not once per keystroke

#### Description:

A reusable coalesced writer, `lib/coalescedWrite.ts`, holds the latest value to store and writes it
`TAB_PERSIST_DELAY_MS` (300) after the last change. Every criterion below that names the delay is decided on a fake clock (`src/test/fakeTimers.ts`), and one of them runs under the harness's `strictMode`, whose doubled effects must not lose a write. It writes at once when asked to flush, and the
tabs hook flushes when it unmounts and on the window's `pagehide`. `useQueryTabs` stores through
it. The reads at mount are unchanged.

#### Acceptance Criteria:

- [ ] Twenty changes to a tab's SQL inside one delay cause one `sessionStorage` write, holding the
      last text (before this spec: twenty).
- [ ] Unmounting the workspace inside the delay writes the last text before the unmount completes,
      so the next mount restores it.
- [ ] A `pagehide` inside the delay writes the last text.
- [ ] Opening, closing and switching a tab are stored within the same delay, and a remount after
      it restores them.
- [ ] A storage that throws on write is swallowed, as today.
- [ ] After a flush or a write, no timer is left pending.

### FR-005: The runs context changes only when a run does

#### Description:

`QueryRunsProvider` supplies memoised values, and every function the engine returns keeps its
identity for the life of the provider.

#### Acceptance Criteria:

- [ ] A render of `QueryRunsProvider` that changes no run, status, error or dismissal renders
      `QueryWorkspace` zero times.
- [ ] `submitBatch`, `handleStop` and `dropRunState` are each the same function before and after a
      run is submitted and settles.
- [ ] A run submitted from one render and stopped from a later one still stops, and a batch still
      advances statement by statement: the existing run suites pass with no assertion weakened.

### FR-006: Reads that fan out across spaces are bounded

#### Description:

`lib/limitConcurrency.ts` supplies a limiter that runs at most a given number of tasks at once and
starts the rest in the order they were asked for. Schema reads share one limiter of
`SCHEMA_READ_CONCURRENCY` (4): a database's two Glue calls run in sequence inside one task, so at
most four Lambda invocations are in flight for schemas, under half the account's ten. The
data-quality list reads its per-space indexes through a limiter of the same size. Autocomplete's
observers of the schema queries take a `staleTime` of `COMPLETION_SCHEMA_STALE_MS` (five minutes);
the rail's own observer keeps the app default, so an expanded database is still re-read as it is
today, and a DDL statement still invalidates both.

#### Acceptance Criteria:

- [ ] Opening Query with twelve usable databases never has more than four schema reads in flight,
      and ends with all twelve loaded (before this spec: twelve at once).
- [ ] A schema read that fails releases its place, and the databases behind it still load.
- [ ] Returning to Query between thirty seconds and five minutes after its schemas loaded re-reads
      only the databases expanded in the rail.
- [ ] `invalidateSchema` still re-reads a database's schema for both the rail and autocomplete.
- [ ] The data-quality list over twelve spaces never has more than four index reads in flight, and
      still shows every space that answered and names every one a retry could clear.

---

## Data Model

```ts
// src/lib/coalescedWrite.ts
export type CoalescedWrite<T> = {
  /** Holds `value` and writes it `delayMs` after the last call. */
  set: (value: T) => void;
  /** Writes what is held now, if anything, and clears the timer. */
  flush: () => void;
  /** Drops what is held without writing it, and clears the timer. */
  cancel: () => void;
};
export function coalescedWrite<T>(write: (value: T) => void, delayMs: number): CoalescedWrite<T>;

// src/lib/limitConcurrency.ts
export function limitConcurrency(max: number): <T>(task: () => Promise<T>) => Promise<T>;

// src/features/query/query.constants.ts
export const TAB_PERSIST_DELAY_MS = 300;

// src/features/catalog/catalog.constants.ts
export const SCHEMA_READ_CONCURRENCY = 4;
export const COMPLETION_SCHEMA_STALE_MS = 5 * 60_000;
```

## File & Folder Structure

```
apps/portal/src/
├── lib/
│   ├── coalescedWrite.ts            (+ test)
│   └── limitConcurrency.ts          (+ test)
├── features/query/
│   ├── QueryWorkspace.tsx           (hands the split its editor and results as elements)
│   ├── EditorSplitColumn.tsx        (owns the measurement, the split and the editor re-layout)
│   ├── QueryResultsTable.tsx        (the rows move into a memoised QueryResultRows)
│   ├── QueryResultsRegion.tsx       (owns the column widths)
│   ├── QueryRunsProvider.tsx, useQueryRunsEngine.tsx, useQueryTabs.ts
│   └── queryRenderScope.test.tsx    (the budgets)
├── features/catalog/useSchema.ts    (the limiter, autocomplete's staleTime)
└── features/data-quality/useDataQualityRuns.ts
```

## Implementation Phases

### Phase 1: Baseline, then the two drags

- Add the render-scope suite in its measuring form and record the baseline at that commit.
- The split column component (FR-002); the column widths beneath the workspace and the memoised
  rows (FR-003, and FR-001's first half).

### Phase 2: The keystroke

- Stable actions from `useQueryTabs` and the runs engine, memoised context values (FR-005), and
  the memoised rail with stable props (FR-001).
- The coalesced writer and the tabs' use of it (FR-004).

### Phase 3: Bounded reads, budgets, close-out

- The limiter, the schema reads and the data-quality list (FR-006).
- Turn the suite's measurements into asserted budgets and mutation-test FR-001's two.
- Completion ritual: the delivery doc carries the before and after counts, each anchored to its
  commit. The signed-in pass stays owed in `docs/testing/owed.md`; it gains the timing of a
  1,000-row page arriving, which is what Andrew's decision on windowing waits on.
