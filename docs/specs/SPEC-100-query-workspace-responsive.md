# Spec: Query Workspace — Responsive Layout

**ID:** SPEC-100  
**Status:** Completed  
**Last Updated:** 2026-08-03  
**Depends On:** SPEC-095

## Overview

The Query workspace (`features/query/`) was built desktop-first: a fixed three-pane shell (248px schema rail + Monaco editor/toolbar/tab-strip + results table) that assumes a wide viewport. On a phone that shell collapses awkwardly — the rail is hidden by an inherited `tablet:` class, the Monaco editor is unusable at ~390px, and the fixed-column results table overflows. This spec makes the workspace **responsive across the three SPEC-095 breakpoints** using presentation-only changes. Desktop (`desktop`) is untouched. Tablet (`tablet`) keeps full editing with a tighter rail and icon-only toolbar. On mobile (`< tablet`) the workspace is **pared to a browse-first surface**: no free-text SQL editor — the user lands on their Saved queries and History, taps to run one, and reads paginated results as row cards. SQL authoring stays a desktop/tablet capability; nothing about how queries execute or where results/history live changes.

## Scope

### In Scope

- A responsive `QueryWorkspace` shell that renders three distinct layouts keyed off the SPEC-095 breakpoints (mobile = base `< tablet`, tablet = `tablet`, desktop = `desktop`).
- **Desktop (`desktop`):** unchanged — the shipped schema rail + Monaco + tab strip + editor toolbar + status bar + results table.
- **Tablet (`tablet`):** schema rail narrows to ~220px (flat table list, tap-to-expand columns reusing the existing node expand); Monaco editor and tab strip stay mounted; editor-toolbar actions collapse to icon-only buttons (labels dropped, `aria-label`s kept); results table keeps its Prev/Next pager.
- **Mobile (`< tablet`) — browse-first:** the Monaco editor, editor toolbar (Run/Clear/Save/Create view), and multi-tab strip are **not mounted**; the workspace lands on a Saved queries / History home; the schema rail moves off-canvas into the SPEC-095 `AppNavDrawer` contextual slot.
- A mobile **results view**: read-only SQL preview + a Succeeded/row-count status strip + one card per row (column → value) + a fixed Prev/Next pager, reached by running a saved query or history entry.
- New presentation components (`QueryMobileView.tsx`, `QueryResultsMobile.tsx`) plus co-located tests, and the responsive-branch wiring in `QueryWorkspace.tsx`.

### Out of Scope

- **No change to query execution** — the run path (`runQuery`/`submitBatch`, `useQueryExecution`, `stopQuery`), statement-splitting, or run scopes are untouched; mobile reuses the existing single-statement run for a saved/history entry.
- **No change to the Athena/Glue services** (`query.service.ts`) or any AWS SDK call.
- **No change to the data layer** — `useQueryResults`, `useResultRowCount`, `useResultsPageSize`, `useQueryHistory`, `useSavedQueries`, `useConnections`, `useSchema` are consumed as-is; no new query, mutation, or fetch is added.
- **No change to history or saved-query storage** — the `{username}/user_settings/` JSON files, their shapes, and their read/write paths are unchanged.
- **No change to IAM, infra, Lambdas, env vars, or `.tftpl` policies** — this is a client-side presentation spec only.
- Removing the editing feature: the mobile change **hides** the SQL editor (Monaco is simply not mounted below `tablet`); the full authoring experience remains fully available on tablet and desktop. This spec does not delete or gate any editing capability at the data/service level.
- Result **charts/visualizations**, mobile column resizing, and any new pagination model (results pagination stays Prev/Next everywhere, matching shipped behavior — no infinite scroll).

---

## Functional Requirements

### FR-001: Breakpoint-keyed layout selection

#### Description:

`QueryWorkspace` chooses one of three layouts from the SPEC-095 breakpoints — desktop (`desktop`, ≥1300px), tablet (`tablet`, 900–1299px), mobile (base, `< tablet`, ~390px) — and is mobile-first (base styles target mobile; `tablet:`/`desktop:` utilities layer up). The desktop and tablet layouts share the existing editor/results shell; the mobile layout is a separate browse-first surface.

#### Acceptance Criteria:

- [ ] At `desktop` (≥1300px) the rendered DOM is the shipped desktop shell: schema rail, tab strip, editor toolbar, Monaco editor, status bar, and results table are all present and unchanged in structure.
- [ ] At `tablet` (900–1299px) the tablet layout renders (per FR-002/FR-003): rail present, Monaco present, toolbar icon-only.
- [ ] Below `tablet` (< 900px) the mobile browse-first layout renders (per FR-004): no Monaco, no editor toolbar, no multi-tab strip.
- [ ] Layout selection is driven by CSS breakpoints / a shared responsive hook consistent with SPEC-095 — not by user-agent sniffing.
- [ ] No horizontal page scroll is introduced at any of the three widths (the results region scrolls internally, not the shell).

### FR-002: Tablet schema rail (~220px, flat table list)

#### Description:

At `tablet` the schema rail stays on-page but narrows from 248px to ~220px and presents a flat list of tables (per-database), with columns revealed on tap by reusing the existing rail node expand behavior. Below `tablet` the rail is not on-page (FR-005).

#### Acceptance Criteria:

- [ ] At `tablet` the schema rail is visible on-page and its width is ~220px (narrower than the 248px desktop/`desktop` rail).
- [ ] At `desktop` the schema rail width is the shipped 248px.
- [ ] Tapping a table row in the tablet rail expands/collapses its columns using the existing node-expand mechanism (no new expand logic).
- [ ] The rail's data source (`useConnections`/`useSchema`) and per-table actions are unchanged from desktop.

### FR-003: Tablet editor toolbar collapses to icon-only

#### Description:

At `tablet` the editor stays mounted, but the editor-toolbar action buttons (Clear, Save, Create view, the Run-scope buttons, Stop) drop their text labels and render icon-only to fit the narrower main column. Each keeps its existing `aria-label`. Desktop shows the labels as shipped.

#### Acceptance Criteria:

- [ ] At `tablet` the Monaco editor and the query tab strip are still mounted and functional.
- [ ] At `tablet` the editor-toolbar buttons render without visible text labels (icon-only) while retaining their `aria-label` (e.g. Clear, Save, Create view, Run statement, Stop).
- [ ] At `desktop` the same toolbar buttons render with their visible text labels, exactly as shipped.
- [ ] The toolbar buttons' `onClick` handlers and disabled logic are unchanged across breakpoints.

### FR-004: Mobile browse-first home (Saved queries / History)

#### Description:

Below `tablet` the workspace does not mount Monaco, the editor toolbar, or the multi-tab strip. Instead it lands on a browse-first home that toggles between **Saved queries** and **History**, each as a scrollable list of cards. Tapping **Run** on a card runs that query through the existing run path and navigates to the mobile results view (FR-006). A **View** affordance is available for a saved-query card. This is the mockup's "Option B (browse-first)".

#### Acceptance Criteria:

- [ ] Below `tablet`, `SqlEditor` (Monaco) is **not rendered** in the DOM, and neither the editor toolbar (Run/Clear/Save/Create view) nor the multi-tab strip is rendered.
- [ ] Below `tablet`, the workspace home shows a Saved / History segmented toggle; Saved is the default surface.
- [ ] The Saved list renders one card per saved query (name, relative updated time, single-line monospace SQL preview) sourced from `useSavedQueries` — no new fetch.
- [ ] The History list renders one card per history entry (status, relative timestamp, SQL preview) sourced from `useQueryHistory` — no new fetch, and paginated with the existing Prev/Next pager.
- [ ] Tapping **Run** on a saved or history card submits that entry's SQL through the existing run path (the same `submitBatch`/run mechanism the desktop uses) and navigates to the mobile results view (FR-006).

### FR-005: Mobile schema rail moves off-canvas

#### Description:

Below `tablet` the schema rail is not rendered inline; instead its content is carried by the SPEC-095 `AppNavDrawer` contextual slot (the off-canvas nav drawer opened from the mobile topbar's menu button). At `tablet`/`desktop` the rail stays inline (FR-002).

#### Acceptance Criteria:

- [ ] Below `tablet`, the schema rail is not present in the inline workspace layout.
- [ ] Below `tablet`, the schema rail content is reachable via the SPEC-095 `AppNavDrawer` contextual slot (off-canvas).
- [ ] At `tablet` and `desktop`, the schema rail renders inline and the off-canvas slot does not duplicate it.
- [ ] The rail component's data + actions are shared between the inline and off-canvas placements (one source, no forked logic).

### FR-006: Mobile results view (read-only SQL, status, row cards, fixed pager)

#### Description:

Running a saved/history query on mobile opens a results view: a back control + the query name, a **Run** (re-run) button, a read-only syntax-styled SQL preview, a status strip (Succeeded + row count · duration, or the failure banner), a scrollable list of **row cards** (one card per result row; each card lists column name → value), and a fixed Prev/Next pager at the bottom.

#### Acceptance Criteria:

- [ ] The results view shows the run SQL as a **read-only** preview (no Monaco / no editable input).
- [ ] A status strip shows the execution outcome — Succeeded with `N rows · duration` on success; the SPEC-028 danger banner with the Athena reason on failure; a running indicator while in flight — reusing the existing status source (`QueryStatusBar` data / `useQueryExecution`), never color-only.
- [ ] On a row-returning success, results render as one card per row of the current page, each card mapping column name → cell value, sourced from `useQueryResults` (no new fetch).
- [ ] A **fixed** Prev/Next pager sits at the bottom of the results view; Prev is disabled on the first page, Next is disabled on the last page, and **both are disabled when a single page holds all rows**.
- [ ] Pagination is replace-style Prev/Next (one page in the DOM) — there is **no infinite scroll** and no "Load more".
- [ ] A back control returns to the browse-first home (FR-004); a Run/re-run control re-submits the same SQL through the existing run path.

### FR-007: Desktop parity preserved

#### Description:

The `desktop` layout is a pure pass-through to the shipped workspace — no regression to editing, running, tabs, status bar, results table, drawers, or dialogs.

#### Acceptance Criteria:

- [ ] At `desktop`, every shipped Query capability (multi-tab editing, all three run scopes, Stop, Save/Create view, Save results, history/saved drawers, table actions, result-tab strip) is present and behaves as before this spec.
- [ ] No desktop-only DOM, class, or handler is removed or altered by the responsive branching.
- [ ] Existing Query workspace tests continue to pass unchanged (the responsive branch defaults to desktop under the test viewport unless a test opts into a narrower width).

---

## Data Model

No new persisted data. The mobile surfaces reuse existing in-memory/derived types from `query.types.ts` (`SavedQuery`, `QueryHistoryEntry`, `QueryStatus`, `ResultTab`) and the existing results-page shape from `useQueryResults`. A small local UI type keys the mobile view:

```ts
// features/query/query.types.ts (local UI state — no persistence)

// Which surface the mobile browse-first workspace is showing.
type MobileQueryView =
  | {kind: 'home'; tab: 'saved' | 'history'}
  | {kind: 'results'; sql: string; title: string};
```

---

## File & Folder Structure

```
apps/portal/src/features/query/
├── QueryWorkspace.tsx          # MODIFIED — responsive branch: desktop/tablet shell vs mobile browse-first
├── QueryMobileView.tsx         # NEW — mobile browse-first home (Saved/History toggle + cards + Run)
├── QueryMobileView.test.tsx    # NEW
├── QueryResultsMobile.tsx      # NEW — mobile results view (read-only SQL + status + row cards + fixed pager)
├── QueryResultsMobile.test.tsx # NEW
├── SchemaBrowser.tsx           # MODIFIED — ~220px at md; off-canvas placement below md (via AppNavDrawer slot)
├── query.types.ts              # MODIFIED — add MobileQueryView UI type
└── (unchanged) SqlEditor.tsx, QueryTabStrip.tsx, editor toolbar, QueryStatusBar.tsx,
    QueryResultsTable.tsx, QueryHistoryPanel.tsx, SavedQueriesPanel.tsx, hooks, query.service.ts
```

## Implementation Phases

### Phase 1: Responsive shell + desktop/tablet

- Introduce the breakpoint branch in `QueryWorkspace` (mobile-first; `tablet`/`desktop` layer up), defaulting to the shipped desktop shell at `desktop`.
- Narrow the schema rail to ~220px at `tablet` (flat table list, reuse existing node expand); keep 248px at `desktop`.
- Collapse the editor-toolbar buttons to icon-only at `tablet` (drop labels, keep `aria-label`s); labels shown at `desktop`.
- Confirm no horizontal page scroll at `tablet`/`desktop` and that existing tests pass.

### Phase 2: Mobile browse-first home

- Build `QueryMobileView`: Saved/History segmented toggle + card lists sourced from `useSavedQueries` / `useQueryHistory` (existing Prev/Next pager for history).
- Below `tablet`, mount `QueryMobileView` instead of the editor shell (no Monaco / toolbar / tab strip).
- Wire the schema rail off-canvas into the SPEC-095 `AppNavDrawer` contextual slot; drop the inline rail below `tablet`.
- Wire each card's **Run** to the existing run path and transition to the results view.

### Phase 3: Mobile results view

- Build `QueryResultsMobile`: back control + query name + Run/re-run, read-only syntax-styled SQL preview, status strip (reusing existing status source), row cards from `useQueryResults`, and a fixed Prev/Next pager (both disabled when one page holds all rows).
- Ensure Prev/Next is replace-style (no infinite scroll) and mirrors the desktop pager semantics.

### Phase 4: Tests + polish

- Co-located tests: Monaco not rendered `< tablet`; Saved is the mobile home default; tapping Run shows the results view with row cards + fixed pager; toolbar icon-only at `tablet`; rail ~220px at `tablet`; rail off-canvas `< tablet`; desktop shell unchanged at `desktop`.
- Accessibility pass: focus order across the mobile home ↔ results transition, `aria-label`s on icon-only controls, status strip as a live region, hit targets ≥ 44px on the pager.
