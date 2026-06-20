# Spec: Multi-Tab Query Editor

**ID:** SPEC-041
**Status:** Draft
**Last Updated:** 2026-06-19
**Depends On:** SPEC-040 (editor draft persistence + Clear — superseded by the per-tab model here), SPEC-035 (query workspace + Monaco editor + Run/Stop toolbar), SPEC-034 (query data layer — unchanged)

> **Design:** **Needs new design work.** Introduces a query-tab strip above the editor that does not exist in `docs/design/query-workspace.html` / `design-system.md` §6. Phase 1 of this spec is a design pass (mockup + §6 addition) before any code. Reuse existing tokens (tabs, ghost buttons, accent underline) — see Open Questions.

> **Amended 2026-06-19 (pre-build):** two changes folded in before implementation. (1) The 10-tab cap is now enforced by a **"close a tab first" dialog** on any attempt to exceed it — the `+` is **not** disabled (FR-008). (2) Tabs may be opened **programmatically with a provided label and SQL** (and an optional linked saved-query id) by SPEC-043 (saved queries) and SPEC-044 (table options menu); only blank `+` tabs use the monotonic `Query N` label (FR-009). All tab-open paths route through one `openTab` guard so the cap dialog applies uniformly.

## Overview

Users want to keep more than one query in flight at a time — a working query, a scratch query, something they pasted to reference — without overwriting one to write another. This spec adds **query tabs** to the editor: each tab is an independent query window with its own SQL text. Tabs are labelled `Query 1`, `Query 2`, … with a counter that only ever increases during the session, so a label always refers to the same query you opened it as. Switching tabs swaps the editor (and that tab's run state) without losing any tab's text. The whole set of tabs — their text, order, the active tab, and the next number to hand out — **persists across tab switches and page reloads within the browser session** (via `sessionStorage`, same scope as SPEC-040). Whatever tab is active is the query that **Run** executes and **Clear** empties. This supersedes SPEC-040's single-draft persistence with a multi-tab model.

## Scope

### In Scope

- A horizontal **tab strip** above the SQL editor listing the open query tabs, with the active tab visually distinguished (per the new design pass)
- A **new-tab** control (e.g. a `+` button) that opens an empty query window labelled `Query N`, where `N` comes from a **monotonic per-session counter**
- A single **`openTab` entry point** that all tab-creating paths use (the `+`, SPEC-043 "open saved query", SPEC-044 "view data / view DDL"), accepting an optional **label** and starting **SQL** so other features can open pre-named, pre-filled tabs (FR-009)
- Per-tab editor text: switching tabs swaps the Monaco editor's content to the selected tab's SQL; edits are isolated to the active tab
- **Run** and **Clear** (SPEC-040 FR-003) act on the **active tab** only; Stop / status / results / CSV download all reflect the active tab's execution
- **Closable tabs** with a close (×) affordance; closing a tab that contains non-empty SQL warns-and-confirms first (reuse the dialog pattern, SPEC-026); at least one tab is always open
- **Monotonic labelling** for blank `+` tabs: the counter never decreases or refills gaps this session — closing `Query 2` does not free the label `2`; the next new blank tab is `Query 3` (user decision). Tabs opened with a provided label (saved queries, table actions) carry that label and do **not** consume a `Query N` number
- A **soft cap of 10 open tabs** (named constant) enforced by a **dialog**: the `+` (and any other open path) stays enabled, but attempting to exceed the cap opens a "close a query tab first" dialog and **does not** create the tab (FR-008)
- **Concurrent run tracking:** every tab with an in-flight query keeps polling Athena in the background, so a backgrounded query's status/results are ready the instant the user returns to its tab (user decision)
- Persisting the full tabs state (tabs + their SQL + order + `activeTabId` + `nextQueryNumber`) to `sessionStorage`, restored on remount (Files↔Query) and page reload
- Migrating/superseding SPEC-040's single-key draft storage into this per-tab model (one-time: an existing SPEC-040 draft, if present, seeds the first tab)
- Per-user keying of the persisted tabs state (by `username`), as in SPEC-040

### Out of Scope

- Persisting query **results** / running `executionId` across page reload — on reload, tabs and their SQL return but each tab starts with no results (must re-run). Run state is held **in memory per tab** during the session only (see Data Model note)
- **User-initiated** renaming of tabs (double-click to rename, etc.) — labels are either the monotonic `Query N` (blank tabs) or a label supplied by the opening feature (saved queries / table actions); there is no free-form rename UI in v1
- Reordering tabs by drag-and-drop (future; tabs render in creation order)
- An *unlimited* number of tabs — v1 enforces a soft cap of 10 (above)
- Cross-tab desktop **notifications** when a backgrounded query finishes — the result is simply ready when the user returns to that tab; no toast/notification in v1
- Cross-browser-tab or cross-restart persistence (still `sessionStorage`, per SPEC-040)
- Any change to the SPEC-034 data layer, services, or IAM

---

## Functional Requirements

### FR-001: Tab strip + active tab

#### Description:

A tab strip above the editor lists open query tabs and lets the user switch between them.

#### Acceptance Criteria:

- [ ] A tab strip renders above the Monaco editor, one item per open tab, each showing its `Query N` label, built to the new §6 design
- [ ] Exactly one tab is active; the active tab is visually distinct (per design — e.g. accent underline / surface) and is announced accessibly (`aria-selected` / `role="tab"` semantics)
- [ ] Clicking a non-active tab makes it active: the editor's content switches to that tab's SQL, and the status bar / results region switch to that tab's run state (or the empty "Run a query" state if it has none)
- [ ] There is always at least one tab; the workspace never renders zero tabs

### FR-002: New tab with monotonic labelling

#### Description:

A new-tab control opens an empty query window numbered from a session counter that only increases.

#### Acceptance Criteria:

- [ ] A new-tab control (`+`, accessible label e.g. `aria-label="New query tab"`) creates a new **blank** tab with empty SQL and makes it active, focusing the editor
- [ ] The new blank tab's label is `Query ${nextQueryNumber}`; creating a blank tab increments `nextQueryNumber` by 1
- [ ] `nextQueryNumber` is **monotonic for the session**: closing a tab never decreases it or frees a label. With tabs `Query 1, Query 2, Query 3`, closing `Query 2` then adding a blank tab yields `Query 4` (not a reused `Query 2`)
- [ ] On a brand-new session with no persisted state, the workspace opens with a single tab `Query 1` and `nextQueryNumber = 2`

### FR-003: Per-tab editor text isolation

#### Description:

Each tab owns its SQL; edits never leak between tabs.

#### Acceptance Criteria:

- [ ] Typing in the editor updates only the active tab's SQL
- [ ] Switching to another tab and back preserves each tab's text exactly (no loss, no cross-contamination)
- [ ] The SPEC-035 `insertAtCursor` (schema-browser click-to-insert) and the SPEC-036 history **Re-open** target the **active** tab's editor

### FR-004: Run / Clear / Stop act on the active tab

#### Description:

Execution controls operate on the active tab only.

#### Acceptance Criteria:

- [ ] **Run** executes the active tab's SQL; **Run** is disabled when the active tab's SQL is empty/whitespace or a query is in flight (existing `canRun` rule, now per active tab)
- [ ] **Clear** (SPEC-040 FR-003) empties the **active** tab's SQL only and clears its persisted text; other tabs are untouched; Clear is disabled while in flight or when the active tab is already empty
- [ ] **Stop**, the status bar, results table, and Download CSV all reflect the active tab's execution; switching tabs while a query runs does not cancel it
- [ ] **Concurrent polling:** each tab holding an in-flight execution polls independently in the background (its own `useQueryExecution`), so its terminal status/stats are recorded and its results are ready as soon as the user returns to that tab — no re-attach delay. Polling still respects the SPEC-034 cadence and `MAX_POLL_DURATION_MS` per execution
- [ ] History **Re-run** (SPEC-036) runs into the active tab and appends a history entry exactly as today

### FR-005: Closable tabs with confirm

#### Description:

Tabs can be closed, with a guard against losing unsaved SQL.

#### Acceptance Criteria:

- [ ] Each tab shows a close (×) control (accessible label e.g. `aria-label="Close Query 2"`)
- [ ] Closing a tab whose SQL is **non-empty** (after trim) opens a warn-and-confirm dialog (reuse SPEC-026 dialog pattern) before removing it; closing an empty tab removes it immediately
- [ ] The close control is **hidden or disabled when only one tab remains** (there is always ≥1 tab)
- [ ] Closing the **active** tab activates an adjacent tab (prefer the tab to the left, else the right) and shows its SQL/run state
- [ ] Closing a tab discards its in-memory run state (executionId/results); it does not delete query history (history is the durable record, SPEC-034/036)

### FR-006: Persist tabs across switches and reloads

#### Description:

The full tab set is persisted to `sessionStorage` and restored on mount.

#### Acceptance Criteria:

- [ ] The persisted state is `{ version, tabs: [{id, label, sql}], activeTabId, nextQueryNumber }` written under a per-user key `s3portal.query.tabs.{username}` (constant prefix in `query.constants.ts`); only the durable fields are persisted — **not** executionId/results/status
- [ ] Writes go through a typed wrapper that swallows `sessionStorage` errors and never throws (as SPEC-040); empty/unauthenticated `username` → no write
- [ ] On mount, if valid persisted state exists for the user it is restored (tabs, order, active tab, counter); after Files↔Query remount and after page reload the exact tab set and active tab return
- [ ] If persisted state is missing or fails to parse/validate, the workspace falls back to a single fresh `Query 1` tab (corrupt state never crashes the editor)
- [ ] **SPEC-040 migration:** on first load under this spec, if a SPEC-040 single draft (`s3portal.query.draft.{username}`) exists and no tabs state exists yet, seed the first tab's SQL from it, then remove the old draft key. The standalone `queryDraft.ts` is replaced by the tabs store

### FR-008: Tab-limit dialog (amended — supersedes the disabled-`+` cap)

#### Description:

When the user (or a feature) tries to open a tab while `QUERY_TABS_MAX` are already open, show a dialog telling them to close a tab first, and do not open the tab.

#### Acceptance Criteria:

- [ ] All tab-open paths call one `openTab` guard; when `tabs.length >= QUERY_TABS_MAX` (10) it **does not** create a tab and signals "at cap" to the caller
- [ ] At the cap, a modal dialog (reuse the SPEC-026 dialog pattern; `role="alertdialog"`) appears with a clear message — e.g. *"You have the maximum of 10 query tabs open. Close a tab before opening another."* — and a single **OK/Got it** dismiss action; Escape and scrim-click also dismiss
- [ ] The dialog is **purely informational**: dismissing it leaves the existing tabs and the active tab unchanged; the attempted action (new blank tab, opening a saved query, a table "view data/DDL") is **not** completed
- [ ] The `+` control is **not disabled** at the cap — clicking it is what surfaces the dialog (the prior "disabled `+`" behavior is removed). Closing any tab drops back below the cap and lets the next open succeed
- [ ] The same dialog is raised when SPEC-043 (open saved query) or SPEC-044 (view data / view DDL) attempts to open a tab at the cap

### FR-009: Programmatic named tabs (for SPEC-043 / SPEC-044)

#### Description:

Other features can open a tab pre-named and pre-filled, rather than a blank `Query N`.

#### Acceptance Criteria:

- [ ] `openTab` accepts an optional `{ label?, sql?, savedQueryId? }`: when `label` is given the new tab uses it verbatim (e.g. `"Monthly revenue"`, `"DDL: sales_2026"`) instead of a `Query N` label, and does **not** increment `nextQueryNumber`; when `sql` is given the editor opens pre-filled with it
- [ ] When `label` is omitted (the `+` path) the tab is blank and labelled with the next `Query N` (FR-002)
- [ ] `savedQueryId`, when given, is stored on the tab so SPEC-043 can detect edits ("dirty") and re-save; it is otherwise inert here
- [ ] Opening a named tab still respects the cap dialog (FR-008) and the persistence model (FR-006) — `label`, `sql`, and `savedQueryId` are durable per-tab fields

### FR-007: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover monotonic numbering across create/close (blank tabs only), the **tab-limit dialog** (opening at cap shows the dialog and creates no tab; closing a tab clears the block), **named tabs** via `openTab({label,sql})` (label used verbatim, counter not incremented), per-tab text isolation, active-tab Run/Clear targeting, **concurrent polling** of a backgrounded running tab (its status finalizes while another tab is active), close-with-confirm on non-empty tabs, last-tab-not-closable, persistence round-trip (restore after remount/reload), corrupt-state fallback, and the SPEC-040 migration seed

---

## Data Model

```ts
// apps/portal/src/features/query/query.types.ts (additions)

export type QueryTab = {
  id: string;             // stable unique id (crypto.randomUUID()); not the label
  label: string;          // "Query N" for blank tabs, or a feature-supplied name
  sql: string;            // this tab's editor text (the persisted, durable field)
  savedQueryId?: string;  // set when opened from a saved query (SPEC-043) — drives dirty/re-save
};

export type QueryTabsState = {
  version: 1;
  tabs: QueryTab[];        // display order = creation order; always length >= 1
  activeTabId: string;     // must reference an existing tab
  nextQueryNumber: number; // monotonic per-session counter for blank "Query N" tabs only
};

// In-memory only (NOT persisted): per-tab run state lives in a map keyed by tab id —
// { executionId, startedAt } — so each tab shows its own results/status while the
// session lasts; dropped on reload (results re-fetch on a fresh Run). Every tab whose
// execution is non-terminal polls concurrently (its own useQueryExecution), so a
// backgrounded query finalizes without waiting for the user to return to its tab.
```

Add the storage-key prefix to `query.constants.ts`:

```ts
// SPEC-041: sessionStorage key prefix for the per-user query-tabs state.
// Full key: `${QUERY_TABS_STORAGE_PREFIX}${username}`. Supersedes SPEC-040's
// QUERY_DRAFT_STORAGE_PREFIX (migrated once into tab 1's sql, then removed).
export const QUERY_TABS_STORAGE_PREFIX = 's3portal.query.tabs.';

// SPEC-041: soft cap on open query tabs. Enforced by a dialog (FR-008): the `+`
// stays enabled, but openTab refuses past this count and the caller shows the
// "close a tab first" dialog. Closing a tab drops back below the cap.
export const QUERY_TABS_MAX = 10;
```

## API / Interface Contract

A persistence helper + a state hook keep `QueryWorkspace` thin:

```ts
// apps/portal/src/features/query/queryTabs.ts
export function readTabsState(username: string): QueryTabsState | null; // null if none/invalid/unavailable
export function writeTabsState(username: string, state: QueryTabsState): void; // no-op on failure
export function migrateDraftToTabs(username: string): QueryTabsState | null; // SPEC-040 one-time seed
export function initialTabsState(): QueryTabsState; // single "Query 1", nextQueryNumber = 2

// apps/portal/src/features/query/useQueryTabs.ts
// Owns QueryTabsState + persistence; exposes:
//   tabs, activeTabId, activeTab
//   setActiveSql(sql), setActiveTab(id), setActiveSavedQueryId(id | undefined)
//   openTab(opts?: { label?: string; sql?: string; savedQueryId?: string }): string | null
//        // returns the new tab id, or null if at QUERY_TABS_MAX (caller shows FR-008 dialog).
//        // No opts → blank "Query N" (increments nextQueryNumber). label given → used verbatim.
//   closeTab(id)                   // enforces >=1 tab + adjacent-activate
//   clearActive()                  // SPEC-040 Clear, scoped to active tab
```

`QueryWorkspace` consumes `useQueryTabs` for editor text + tab controls, keeps a separate in-memory `Map<tabId, { executionId, startedAt }>` for per-tab run state, and renders the FR-008 tab-limit dialog when an `openTab` call returns `null`. SPEC-043 and SPEC-044 call `openTab({ label, sql, savedQueryId? })` through this same guard.

## File & Folder Structure

```
apps/portal/src/features/query/
├── query.constants.ts        ← + QUERY_TABS_STORAGE_PREFIX, QUERY_TABS_MAX
├── query.types.ts            ← + QueryTab, QueryTabsState
├── queryTabs.ts              ← NEW: sessionStorage read/write + migrate + initial state
├── queryTabs.test.ts         ← NEW
├── useQueryTabs.ts           ← NEW: tabs state + persistence hook
├── useQueryTabs.test.ts      ← NEW
├── QueryTabStrip.tsx         ← NEW: tab strip UI (labels, +, ×, active state)
├── QueryTabStrip.test.tsx    ← NEW
├── TabLimitDialog.tsx        ← NEW: FR-008 "close a tab first" alert dialog (SPEC-026 pattern)
├── queryDraft.ts             ← REMOVED (superseded; logic folded into queryTabs.ts)
└── QueryWorkspace.tsx        ← render tab strip + limit dialog; per-tab editor text + run-state map
docs/design/
├── query-workspace.html      ← + tab strip (Phase 1 design pass)
└── design-system.md          ← §6 + query tab strip pattern
```

## Implementation Phases

### Phase 1: Design pass (no app code)

- Add the query-tab strip to `docs/design/query-workspace.html` (labels, active state, always-enabled `+`, per-tab `×`) and document the pattern in `design-system.md` §6, reusing existing tokens (tab underline/accent, ghost buttons, dialog for close-confirm and the FR-008 tab-limit alert)
- Settle the exact active-tab styling within the strip; show the FR-008 "close a tab first" dialog (the `+` is never disabled)

#### Checkpoint

The updated `query-workspace.html` renders a tab strip with two or three tabs (mixing `Query N` and a feature-named tab), a clear active state, an always-enabled `+`, and per-tab `×`, plus the FR-008 tab-limit dialog; review and approve before writing code.

### Phase 2: Tabs state + persistence (data layer)

- Add types + `QUERY_TABS_STORAGE_PREFIX`; build `queryTabs.ts` (read/write/initial/migrate) and `useQueryTabs.ts`
- Implement monotonic numbering, close→adjacent-activate, ≥1-tab invariant, corrupt-state fallback, and the SPEC-040 migration; remove `queryDraft.ts`
- Unit-test the hook/helper (FR-002, FR-005, FR-006)

#### Checkpoint

Hook tests pass: creating/closing tabs yields monotonic labels; closing the active tab activates a neighbor; a corrupt stored blob falls back to a single `Query 1`; a pre-existing SPEC-040 draft seeds tab 1 and the old key is removed. `npm run test` + `npm run lint` pass.

### Phase 3: Wire into the workspace UI

- Render `QueryTabStrip`; drive the Monaco editor from the active tab; isolate edits per tab
- Maintain the in-memory per-tab run-state map so status/results/Stop/CSV follow the active tab
- Point Run / Clear / schema insert / history Re-open/Re-run at the active tab (FR-001, FR-003, FR-004)
- Close-with-confirm dialog for non-empty tabs (FR-005); the FR-008 tab-limit dialog when `openTab` returns `null`; `openTab` accepts label/sql for FR-009

#### Checkpoint

Open `Query 1`, type a `SELECT`; `+` → `Query 2`, type a different query; flip between them → each keeps its own text. Run in `Query 2`, switch to `Query 1` then back → `Query 2`'s results are already there (it kept polling). Switch to **Files** and back, then reload → both tabs and the active one return with their text (results cleared). Close `Query 2` (with text) → confirm dialog; close `Query 1` when it's the only tab → not allowed. Add a blank tab → it's `Query 3`. Open tabs until 10 are present, then `+` again → the "close a tab first" dialog appears and no 11th tab is created. `npm run test` + `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-19):** tab numbering is a **monotonic per-session counter** (closing a tab never frees/reuses a label).
- [x] **Resolved (2026-06-19):** tabs are **closable**, with a **warn-and-confirm** when the tab holds non-empty SQL; always ≥1 tab.
- [x] **Resolved (2026-06-19):** persistence is **`sessionStorage`** (same scope as SPEC-040), per-user keyed.
- [x] **Resolved (2026-06-19):** tab overflow uses a **soft cap of 10 tabs** (`QUERY_TABS_MAX`). **Amended same day:** the cap is enforced by a **"close a tab first" dialog** (FR-008), not a disabled `+`. The exact active-tab styling within the strip is settled in the Phase 1 design pass.
- [x] **Resolved (2026-06-19):** per-tab results are **dropped on reload** (only SQL text persists per tab; re-run to repopulate). Persisting/re-fetching results is a possible future follow-up, not v1.
- [x] **Resolved (2026-06-19):** **all running tabs poll concurrently** in the background, so a backgrounded query finalizes without waiting for reactivation (each tab runs its own `useQueryExecution`).
- [x] **Resolved (2026-06-19):** tabs may be opened with a **feature-supplied label + SQL** (FR-009); only blank `+` tabs use `Query N`. Saved-query tabs (SPEC-043) and table-action tabs (SPEC-044) carry descriptive labels.
