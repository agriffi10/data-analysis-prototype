---
type: Spec
id: SPEC-272
title: "Typing and Dragging Leave the Query Results and the Rail Alone"
description: "Narrows what a keystroke, a divider drag and a column drag cost in the Query workspace, so none of them re-renders the result rows or the schema rail; coalesces the tabs' session storage writes; and keeps the runs context stable."
spec_status: Draft
depends_on: []
arc: render-scope
arc_order: 2
---

**Dependency notes:** the arc's opening change landed `apps/portal/src/test/renderCounter.tsx`,
which every budget below is counted with. Nothing here needs SPEC-271 or SPEC-274.

## Overview

In the Query workspace three things change many times a second: the SQL being typed, the height of
the editor while its divider is dragged, and a result column's width while its edge is dragged. All
three are held at the top of the workspace, so each keystroke and each pointer move redraws the
whole page: the schema rail, the tab strip, the toolbar, both drawers, every dialog and every row
of the result, which can be a thousand rows. Measured at `91f97fe60` with the suite this spec's
first commit adds, on a 200-row by 10-column result, one keystroke, one divider move and one
column move each re-walked 2,986 fibers and rendered every component on the page; Phase 1
re-records that figure at its own commit. This spec makes each of those gestures cost what it
changes, whatever the size of the result on screen. It also stops the workspace writing every tab
to session storage on every keystroke.

What a user does is unchanged, with one accepted exception that FR-003 names. Andrew decided on
2026-11-27 that the result grid is memoised, not windowed, and that the 1,000-row page cap stays.

## Scope

### In Scope

- What a keystroke, a divider move and a column-resize move render in the Query workspace.
- When the Query tabs are written to session storage, on every surface that opens a tab, the
  phone's hand-off included.
- The identity of the values `QueryRunsProvider` supplies.
- A render-scope suite for the workspace whose budgets fail when any of the above regresses.

### Out of Scope

- **Windowing the result grid, and the 1,000-row cap.** Andrew's decision: the one-off cost of
  drawing a large page is to be timed on the deployed build before anything is built for it.
- **`features/catalog/ColumnResizeHandle.tsx`.** It is shared with the Data Explorer and no spec of
  this arc changes it: the drag still reports every pointer move, and the fix is in who renders
  when it does.
- **Where `QueryRunsProvider` is mounted.** It stays at the signed-in shell.
- **What the phone's surface renders.** Below `tablet` there is no editor, no divider and no column
  handle, so FR-001 to FR-003 have nothing to measure there.
- **How many schema reads opening Query starts**, which is SPEC-274.
- The Data Explorer, which is SPEC-273 and takes this spec's coalesced writer.

---

## Functional Requirements

**A criterion is a condition, not a test case.** One scenario settles several, and each suite stays
within the testing rules' scenario budget for its unit.

**How every budget below is asserted.** A count of zero is also what a misspelled component name
or a gesture that did nothing reports. So each test that asserts a zero also asserts, in the same
test, the gesture's visible effect and one component that the gesture must render, by a count
above zero, and reads its counts through the counter's `count(name)`, which refuses a name no
component under the probe has had. Every budget in this spec is mutation-tested once: the memo, the stable identity or
the placement it rests on is reverted, the test is seen to fail on that count, and the mutation is
recorded in the delivery doc.

### FR-001: A keystroke renders neither the result rows nor the schema rail

#### Description:

The result's rows are drawn by a memoised component, `QueryResultRows`, whose props are the page's
rows and the first row's number; both already keep their identity across a keystroke.

The schema rail is memoised, and every prop the workspace hands it keeps its identity across a
keystroke. `connections` already does. The rail's actions do not today: the workspace builds them
on every render, over a `submitBatch` that `useTabRuns` rebuilds, an `open` that `useTableShare`
rebuilds, and closures written inline. The inline rail therefore takes its handlers the way the
phone's drawer already does in `useTableActions.tsx`: a memoised object whose handlers call the
latest ones through a ref. One member is not a handler: `canViewSourceFiles` is called while the
rail renders, so it is a function whose identity changes when `connections` does and at no other
time, never a delegate through a ref an effect sets.

`useQueryTabs` returns actions whose identity is stable for the life of the hook.

#### Acceptance Criteria:

- [ ] With a result on screen, typing one character renders `QueryResultRows` zero times and
      `SchemaBrowser` zero times, and renders the toolbar, whose Run control follows the text.
- [ ] With rows per page set to 1,000, the number of fibers a keystroke re-walks is the same with
      a 20-row result on screen as with a 200-row one.
- [ ] A table that becomes viewable when the connections list changes shows **View source files**
      in its rail menu without the rail being remounted.
- [ ] A rail action taken after the tabs have changed acts on the tabs as they are now: with the
      tab limit reached after the rail first rendered, **View data** raises the limit dialog.
- [ ] Run, Clear, Save, the dirty marker and the downloaded `.sql` all still follow the text as
      typed: the existing workspace suites pass with no assertion weakened.

### FR-002: A divider drag renders the split, and nothing above or below it

#### Description:

The editor/results split, its measurement of the column and the editor's re-layout live in one
component beneath the workspace, `EditorSplitColumn`, which receives the editor and the results
region as elements and is handed the editor's ref. A pointer move during the drag sets state in
that component alone. Nothing outside it reads the split or the measurement today.

#### Acceptance Criteria:

- [ ] One pointer move during a divider drag renders `QueryWorkspace` zero times,
      `QueryResultRows` zero times and `SchemaBrowser` zero times, and renders `EditorSplitColumn`
      once.
- [ ] The editor pane's height, the divider's `aria-valuenow` and `aria-valuetext`, and Monaco's
      re-layout still follow each pointer move at once, and the split is still stored once, on
      release: `queryWorkspaceDivider.test.tsx` passes with no assertion changed.
- [ ] A session that starts below `tablet` and widens still measures the column and can move the
      divider.

### FR-003: A column-resize drag renders the table's header, and no row

#### Description:

A result's column widths are held in `QueryResultsRegion`, which stays mounted across paging,
query-tab switches and result-tab switches while only the table beneath it unmounts, so a user's
widths still survive all three. The rows do not read the widths, which reach the table through its
`<colgroup>`.

#### Acceptance Criteria:

- [ ] One pointer move during a column-resize drag renders `QueryWorkspace` zero times,
      `QueryResultRows` zero times and `SchemaBrowser` zero times, renders `QueryResultsTable`
      once, and the `<col>` for that column carries the new width.
- [ ] A width set by the keyboard survives Next and Prev, a switch to another query tab and back,
      and a switch between result tabs; a new run starts from the defaults. The existing
      width-persistence case passes with no assertion changed.
- [ ] Widths are in memory only, as today: a reload or leaving the route starts from the defaults.
      Crossing below `tablet` and back now does too. That is new and accepted: there is no table
      below `tablet`, and the region that holds the widths is not mounted there.

### FR-004: The tabs are written to session storage at most once per delay, not once per keystroke

#### Description:

A reusable coalesced writer, `lib/coalescedWrite.ts`, holds the latest value to store and writes it
a fixed delay after the first change it has not yet written, or at once when asked to flush. The
wait is not restarted by later changes, so continuous typing still writes once per delay and what
is unwritten is never older than the delay. `useQueryTabs` stores through
it with `TAB_PERSIST_DELAY_MS` (300). The state the hook mounts with is written at once, as today,
so a fresh session's first tab keeps its id across a remount and its run is not dropped as an
orphan. Every later change is coalesced. The hook flushes when it unmounts and on the window's
`pagehide`, and after it has unmounted it writes nothing: an action that lands late, from an await
that outlived the page, changes no storage and starts no timer. The reads at mount are unchanged.

What this costs: text typed in the last 300 ms before the browser is killed without a `pagehide`
is not restored. A reload, a closed tab, a navigation and a sign-out all fire `pagehide` or
unmount the hook first. This, and FR-003's reset of widths below `tablet`, are accepted by the
author at authoring and not yet ruled on by Andrew.

Every criterion below that names the delay is decided on a fake clock (`src/test/fakeTimers.ts`).

**Existing suites change in how they read storage, and in nothing they assert.** A suite that reads
`QUERY_TABS_STORAGE_PREFIX` after a gesture now reads it after a flush: the fake clock advanced
past the delay, or the workspace unmounted. `openSqlHandoff.test.tsx` is known to; every other
suite that reads the key is checked the same way. **A negative read flushes first.** An assertion
that something was not stored passes for the wrong reason while a write is merely pending, so
every such assertion flushes before it reads.

#### Acceptance Criteria:

- [ ] Twenty changes to a tab's SQL inside one delay cause one `sessionStorage` write, holding the
      last text (measured before this spec: one per change).
- [ ] Changes arriving every 100 ms for a second cause no fewer than three writes: the wait runs
      from the first unwritten change, and is not pushed back by the ones after it.
- [ ] A fresh session's first tab is in storage before any timer runs, and a remount restores it
      under the same tab id.
- [ ] Unmounting the workspace inside the delay writes the last text before the unmount completes,
      so the next mount restores it; this criterion also runs under the harness's `strictMode`,
      whose doubled effects must neither lose the write nor leave a timer.
- [ ] A `pagehide` inside the delay writes the last text.
- [ ] Opening, closing and switching a tab are stored within the delay, and a remount after it
      restores them; a tab opened by a hand-off from the Data Explorer is stored the same way, on
      the phone's surface too.
- [ ] `openTab` called after the hook has unmounted writes nothing and leaves no timer.
- [ ] A storage that throws on write is swallowed, as today.
- [ ] After a flush, no timer is left pending.

### FR-005: The runs context changes only when a run does

#### Description:

`QueryRunsProvider` supplies memoised values, and every function the engine returns keeps its
identity for the life of the provider.

#### Acceptance Criteria:

- [ ] When the provider's parent re-renders with the same children, and no run, status, error or
      dismissal has changed, `QueryWorkspace` renders zero times and the provider renders once.
- [ ] `submitBatch`, `handleStop` and `dropRunState` are each the same function before and after a
      run is submitted and settles.
- [ ] A run submitted from one render and stopped from a later one still stops, and a batch still
      advances statement by statement: the existing run suites pass with no assertion weakened.

---

## Data Model

```ts
// src/lib/coalescedWrite.ts
export type CoalescedWrite<T> = {
  /** Holds `value`, and writes the latest held value `delayMs` after the first unwritten call. */
  set: (value: T) => void;
  /** Writes what is held now, if anything, and clears the timer. */
  flush: () => void;
};
export function coalescedWrite<T>(write: (value: T) => void, delayMs: number): CoalescedWrite<T>;

// src/features/query/query.constants.ts
export const TAB_PERSIST_DELAY_MS = 300;
```

## File & Folder Structure

```
apps/portal/src/
├── lib/coalescedWrite.ts            (+ test)
└── features/query/
    ├── QueryWorkspace.tsx           (hands the split its editor and results as elements)
    ├── EditorSplitColumn.tsx        (owns the measurement, the split and the editor re-layout)
    ├── QueryResultsTable.tsx        (the rows move into a memoised QueryResultRows)
    ├── QueryResultsRegion.tsx       (owns the column widths)
    ├── SchemaBrowser.tsx            (memoised)
    ├── useTableActions.tsx          (the inline rail's actions keep their identity)
    ├── useTabRuns.ts                (a stable submitBatch and handleStop)
    ├── QueryRunsProvider.tsx, useQueryRunsEngine.tsx, useQueryTabs.ts
    ├── query.constants.ts           (the delay)
    └── queryRenderScope.test.tsx    (the budgets)
```

`src/test/queryWorkspaceSupport.tsx` and the workspace's existing suites are this spec's to edit
while it is in flight; SPEC-274 adds files beside them and changes none.

## Implementation Phases

### Phase 1: Baseline, then the two drags

- Add the render-scope suite in its measuring form and record the baseline at that commit.
- `EditorSplitColumn` (FR-002); the column widths in the region and the memoised rows (FR-003, and
  FR-001's rows).

### Phase 2: The keystroke

- Stable actions from `useQueryTabs`, `useTabRuns` and the runs engine, and memoised context
  values (FR-005).
- The memoised rail and its stable actions (FR-001).

### Phase 3: Coalesced storage, budgets, close-out

- The coalesced writer and the tabs' use of it (FR-004).
- Turn the suite's measurements into asserted budgets and mutation-test each.
- Completion ritual: the delivery doc carries the before and after counts, each anchored to its
  commit. The arc's row in `docs/testing/owed.md` gains this spec's lines: the feel of typing and
  of both drags over a large result, and the timing of a 1,000-row page arriving, which is what
  Andrew's decision on windowing waits on.
