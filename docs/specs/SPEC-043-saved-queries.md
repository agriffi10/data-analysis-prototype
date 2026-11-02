---
type: Spec
id: SPEC-043
title: "Saved Queries + Global Workspace Bar"
description: "Lets users save named queries from any query tab, then list, open, update, and delete them in a slide-out drawer, with history showing which saved query ran, and moves History and Saved to a global workspace bar."
spec_status: Completed
depends_on: [SPEC-041, SPEC-036, SPEC-034, SPEC-026, SPEC-028]
arc: query-editor-round-2
arc_order: 1
---

**Dependency notes:** SPEC-041 (query tabs + `openTab` named-tab API + tab-limit dialog), SPEC-036 (history drawer pattern + history panel), SPEC-034 (query-history JSON store + `QueryHistoryEntry`), SPEC-026 (dialog pattern), SPEC-028 (Button / Input primitives)
> **Design:** Needs a design pass (done after this spec, with SPEC-044). Reuses the SPEC-036 right-drawer pattern for the saved-queries list, the SPEC-026 modal pattern for the name prompt and delete confirm, and the `db-chip`/ghost/primary buttons from `design-system.md` §6. Two layout changes: a **Save** button joins the editor toolbar (the Run bar), and **History + Saved queries** move out of the per-tab toolbar to a **global bar** on the tab-strip row.

## Overview

Users want to keep queries they'll run again — not just rely on history, which is an immutable log. This spec adds **saved queries**: from any query tab the user can **Save** the current SQL under a name, see all their saved queries in a slide-out drawer (the same style as history), and open any saved query into a new tab to run it. Saved queries are editable (re-save updates them in place), deletable (with a confirmation), and a query run from a saved query records that name in history so the log shows *which* saved query produced a result. Because saved queries and history are both workspace-wide (not tied to one tab), this spec also **hoists the History and Saved-queries buttons to a global bar** shared by all tabs, while the per-tab **Save** button lives next to **Run**. Saved queries persist per-user in the same S3 JSON-store pattern as history (no IAM change).

## Scope

### In Scope

- A **Save** button in the editor toolbar (the same bar as **Run**), acting on the **active tab**; saving prompts for a name
- A **name-prompt dialog** (modal with a text input; SPEC-026 pattern) shown on Save — empty when saving a new query, **pre-filled** when re-saving a tab already linked to a saved query
- A per-user **saved-queries store** at `{username}/athenaresults/saved-queries.json` (same prefix/IAM as history — `PutObject` overwrite; deleting an entry rewrites the JSON, never an S3 object delete), with a service + `useSavedQueries` hook
- A **Saved queries drawer** (right slide-over, mirrors the SPEC-036 history drawer): lists the user's saved queries (name, updated time, SQL preview) with **Open** and **Delete** actions
- **Open** a saved query → opens it in a **new tab** labelled with the saved query's name, linked to it (via `openTab({ label, sql, savedQueryId })`, SPEC-041 FR-009); respects the tab-limit dialog (SPEC-041 FR-008)
- **Re-save in place:** when the active tab is linked to a saved query and its SQL has changed, Save **updates that saved query** (name pre-filled); the tab's **dirty marker** clears on success
- **Name-collision handling:** saving under a name that already belongs to a *different* saved query prompts a **warn-and-confirm overwrite**
- **Delete** a saved query → an **"are you sure" confirm modal** (SPEC-026 alertdialog); on confirm the entry is removed from the JSON; any open tab linked to it is **unlinked** (keeps its text, Save now creates new)
- A **dirty indicator** on a linked tab whose editor content differs from its saved query (e.g. a `•`/`*` on the tab label) — signals "re-save needed"
- **History shows the saved-query name:** running a tab linked to a saved query records `savedQueryName` on the appended `QueryHistoryEntry`; the SPEC-036 history panel/row displays it
- **Global workspace bar:** move **History** (and add **Saved queries**) out of the per-tab toolbar onto the tab-strip row (right-aligned), shared across all tabs (user decision)

### Out of Scope

- **Pagination** of the saved-queries drawer (saved lists are expected to be small; v1 shows the full list, newest/A–Z. Add a pager later if needed — see Open Questions)
- **Sharing** saved queries between users, or any cross-user visibility (each user's store is private, like history)
- **Folders / tags / search** over saved queries (future)
- A free-form **tab rename** UI (tab labels still come only from `Query N` or a feature, per SPEC-041)
- **Scheduling** saved queries to run automatically
- Any **IAM / infra** change — the store reuses the SPEC-032/034 `athenaresults/` policy (PutObject allowed, delete denied; we only ever overwrite)
- Changing how history is **stored** (SPEC-034) — this spec only *adds* an optional field to each entry

---

## Functional Requirements

### FR-001: Save button (active tab) + name prompt

#### Description:

A Save control in the Run bar saves the active tab's SQL as a named saved query.

#### Acceptance Criteria:

- [ ] A **Save** button sits in the editor toolbar in the same group as **Run** (ghost or default variant per design); it acts on the **active tab**
- [ ] Save is **disabled** when the active tab's SQL is empty/whitespace
- [ ] Clicking Save opens a **name-prompt modal** (SPEC-026 pattern; a labelled `Input` + **Save**/**Cancel**); **Save** in the dialog is disabled until the name is non-empty (trimmed)
- [ ] On confirm for an **unlinked** tab: a new `SavedQuery` is created (new `id`, `createdAt`/`updatedAt` now), the active tab becomes **linked** to it (`savedQueryId` set, SPEC-041), and the tab label becomes the saved query's name
- [ ] Cancel/Escape closes the dialog with no change

### FR-002: Re-save in place (linked tab)

#### Description:

Saving a tab that's already linked updates the existing saved query rather than creating a new one.

#### Acceptance Criteria:

- [ ] When the active tab is **linked** (`savedQueryId` set), Save opens the name prompt **pre-filled** with the saved query's current name
- [ ] Confirming **updates the existing saved query in place** (same `id`): its `sql` is set to the tab's current SQL, `name` to the (possibly edited) name, and `updatedAt` is bumped
- [ ] After a successful re-save the tab's **dirty marker clears** and the label reflects the (possibly new) name
- [ ] If the user edits the name to one that collides with a **different** saved query, FR-003 (overwrite confirm) applies

### FR-003: Name-collision confirm

#### Acceptance Criteria:

- [ ] Saving under a name that already belongs to a **different** saved query (case-insensitive match) surfaces a **warn-and-confirm**: "A saved query named '…' already exists. Replace it?"
- [ ] Confirming **overwrites that existing saved query** (updates its `sql`/`updatedAt`, keeps its `id`); the active tab is (re)linked to that id
- [ ] Cancelling returns to the name prompt with the name still editable; nothing is saved
- [ ] Re-saving a linked tab under its **own** unchanged name is **not** a collision (it's the normal in-place update, FR-002)

### FR-004: Saved queries store (service + hook)

#### Description:

Per-user saved queries persist in S3 as JSON, read/written like the history store.

#### Acceptance Criteria:

- [ ] `savedQueries.service.ts` reads/writes `{username}/athenaresults/saved-queries.json`; all writes are `PutObject` **overwrite** (never S3 delete) — removing a saved query rewrites the JSON without it; this works under the existing SPEC-032/034 IAM (no policy change)
- [ ] Services return `ServiceResult<T>` and never throw; a missing file reads as an empty store (`{ version: 1, queries: [] }`), never an error
- [ ] `getSavedQueries`, `upsertSavedQuery` (create or update by id), and `removeSavedQuery(id)` are exposed; `useSavedQueries(username)` wraps them in TanStack Query with a `queryKeys.savedQueries(username)` key and invalidation on mutate
- [ ] Concurrent writes are **last-writer-wins** for a single user's own file (documented, acceptable as for history, SPEC-034)

### FR-005: Saved queries drawer

#### Description:

A right slide-over lists the user's saved queries with open/delete actions.

#### Acceptance Criteria:

- [ ] A **Saved queries** drawer mirrors the SPEC-036 history drawer mechanics (440px right slide-over, scrim, Escape/scrim-click/close-button to dismiss, `role="dialog"`)
- [ ] Each saved query renders as a bordered card: **name** (prominent), a relative **updated** time (absolute on hover), a single-line monospace **SQL preview** (ellipsis-truncated), and right-aligned **Open** and **Delete** actions
- [ ] The list is ordered consistently (A–Z by name, or most-recently-updated first — pick one in design); empty state: a friendly "No saved queries yet — Save a query to see it here"
- [ ] Loading and error states match the history drawer's treatment

### FR-006: Open a saved query into a new tab

#### Acceptance Criteria:

- [ ] **Open** calls `openTab({ label: name, sql, savedQueryId })` (SPEC-041 FR-009): a **new** tab opens, labelled with the saved query's name, pre-filled with its SQL, linked to it, and made active; the drawer closes
- [ ] If the workspace is at the tab cap, the **SPEC-041 FR-008 tab-limit dialog** appears and **no** tab opens (the saved query is not lost — the user closes a tab and retries)
- [ ] Opening does **not** auto-run the query (consistent with history Re-open, SPEC-036); the user presses Run
- [ ] Opening the same saved query twice yields two independent tabs (each linked to the same `savedQueryId`); editing one doesn't change the other until re-saved

### FR-007: Delete a saved query (confirm)

#### Acceptance Criteria:

- [ ] **Delete** opens an **"are you sure"** confirm modal (SPEC-026 `role="alertdialog"`; danger action) naming the saved query
- [ ] Confirming calls `removeSavedQuery(id)` (rewrites the JSON without that entry) and removes it from the drawer; cancelling does nothing
- [ ] Any **open tab linked** to the deleted saved query is **unlinked** (`savedQueryId` cleared): the tab keeps its current label and SQL, its dirty marker clears, and a subsequent **Save** creates a **new** saved query (FR-001)
- [ ] Delete never deletes an S3 object (delete is IAM-denied in `athenaresults/`); it only overwrites the JSON — verified in tests

### FR-008: Dirty indicator on linked tabs

#### Acceptance Criteria:

- [ ] A tab linked to a saved query whose **current editor SQL differs** from the linked saved query's stored SQL shows a **dirty marker** on its label (e.g. a leading `•`); when they match, no marker
- [ ] The marker clears after a successful re-save (FR-002) and appears again on the next divergent edit
- [ ] An unlinked tab never shows the marker

### FR-009: History records the saved-query name

#### Acceptance Criteria:

- [ ] `QueryHistoryEntry` gains an optional `savedQueryName?: string` (and `savedQueryId?: string`); this is an **additive** change to the SPEC-034 type — existing entries without it are unaffected
- [ ] When a tab **linked** to a saved query is Run, the appended history entry carries the linked saved query's current `name` (and `id`)
- [ ] The SPEC-036 history panel/row **displays** the saved-query name when present (e.g. a small "Saved: {name}" label/badge on the entry); entries without it render exactly as today
- [ ] Re-running from history (SPEC-036) of an entry that had a `savedQueryName` carries the name forward only if the run still originates from a linked tab (don't fabricate a link)

### FR-010: Global workspace bar (hoist History + Saved queries)

#### Description:

History and Saved-queries buttons move out of the per-tab toolbar to a workspace-global bar.

#### Acceptance Criteria:

- [ ] **History** and **Saved queries** buttons render on the **tab-strip row** (right-aligned), shared by all tabs — not in the per-tab editor toolbar (user decision); each opens its respective drawer
- [ ] The per-tab editor toolbar now holds the tab-scoped controls only: `db-chip`, **Format**, **Clear** (SPEC-040), **Save** (FR-001), **Stop**, **Run**
- [ ] Both drawers are mutually exclusive-friendly (opening one closes the other, or they stack predictably — pick one in design) and reachable from any active tab
- [ ] Keyboard-focusable with the standard focus ring; accessible labels on both buttons

### FR-011: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: new-save creates + links + relabels; re-save updates in place + clears dirty; name-collision overwrite confirm; store service round-trip (read/upsert/remove rewrites JSON, never deletes an object) including missing-file empty store; drawer Open routes through `openTab` (and hits the cap dialog at the limit); delete confirm + unlinking of open tabs; dirty marker appears/clears; history entry carries `savedQueryName` and the panel shows it; the global bar renders History + Saved queries (and they're gone from the per-tab toolbar)

---

## Data Model

```ts
// apps/portal/src/features/query/query.types.ts (additions)

export type SavedQuery = {
  id: string;          // crypto.randomUUID()
  name: string;        // user-supplied; unique-ish (collisions confirmed, FR-003)
  sql: string;
  database: string;    // = username for now (single DB), kept for forward-compat
  createdAt: string;   // ISO
  updatedAt: string;   // ISO
};

export type SavedQueriesStore = {
  version: 1;
  queries: SavedQuery[];
};

// Additive to the SPEC-034 history entry (FR-009):
export type QueryHistoryEntry = {
  // …existing fields…
  savedQueryId?: string;    // set when run from a tab linked to a saved query
  savedQueryName?: string;  // displayed in the history panel (SPEC-036)
};
```

`QueryTab.savedQueryId` (the link) is defined in SPEC-041 FR-009.

## API / Interface Contract

```ts
// savedQueries.service.ts — same S3 JSON-store pattern as queryHistory.service.ts
getSavedQueries(username: string): Promise<ServiceResult<SavedQueriesStore>>;
upsertSavedQuery(username: string, q: SavedQuery): Promise<ServiceResult<SavedQueriesStore>>; // create or replace by id
removeSavedQuery(username: string, id: string): Promise<ServiceResult<SavedQueriesStore>>;    // rewrites JSON minus id

// useSavedQueries(username) → { queries, isLoading, error, upsert, remove }  (TanStack Query)

// Opening (SPEC-041): const id = openTab({ label: q.name, sql: q.sql, savedQueryId: q.id });
//   id === null → show the SPEC-041 FR-008 tab-limit dialog.
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── query.types.ts             ← + SavedQuery, SavedQueriesStore; QueryHistoryEntry += savedQuery{Id,Name}?
├── savedQueries.service.ts    ← NEW: get / upsert / remove (S3 JSON, PutObject overwrite)
├── savedQueries.service.test.ts
├── useSavedQueries.ts         ← NEW: list + upsert/remove mutations (TanStack Query)
├── useSavedQueries.test.ts
├── SavedQueriesPanel.tsx      ← NEW: right drawer (mirrors QueryHistoryPanel)
├── SavedQueriesPanel.test.tsx
├── SaveQueryDialog.tsx        ← NEW: name-prompt modal (+ overwrite-confirm step)
├── SaveQueryDialog.test.tsx
├── queryKeys.ts               ← + queryKeys.savedQueries(username)
├── QueryWorkspace.tsx         ← Save button; hoist History; render global bar; dirty marker; link-on-open/run
├── QueryTabStrip.tsx          ← host the global History + Saved-queries buttons (right side)
└── QueryHistoryRow.tsx        ← show savedQueryName when present (SPEC-036)
```

## Implementation Phases

### Phase 1: Store + hook

- Types (`SavedQuery`, `SavedQueriesStore`, history-entry additions); `savedQueries.service.ts` + `useSavedQueries.ts`; `queryKeys.savedQueries`
- Unit-test the store (FR-004): missing-file empty store, upsert create/replace, remove rewrites JSON (asserts no `DeleteObjectCommand`)

#### Checkpoint

Service tests pass: upsert then get returns the query; remove then get omits it; a missing file yields an empty store; no S3 delete is ever issued. `npm run test` + `npm run lint` pass.

### Phase 2: Save flow + dirty + history name

- **Save** button in the toolbar; `SaveQueryDialog` (name prompt, pre-fill on re-save, overwrite-confirm); link/relabel the active tab; dirty marker (FR-001/002/003/008)
- Carry `savedQueryName`/`savedQueryId` onto the appended history entry and show it in `QueryHistoryRow` (FR-009)

#### Checkpoint

Save a new query → prompt → tab relabels to the name, no dirty marker; edit it → dirty marker appears; Save → prompt pre-filled, updates in place, marker clears; Save under an existing name → overwrite confirm. Run a linked tab → its history entry shows "Saved: {name}". `npm run test` + `npm run lint` pass.

### Phase 3: Drawer + global bar

- `SavedQueriesPanel` drawer (list, Open, Delete-with-confirm); **Open** via `openTab` (cap dialog honored); delete unlinks open tabs (FR-005/006/007)
- Hoist **History** + add **Saved queries** to the global tab-strip row; remove History from the per-tab toolbar (FR-010)

#### Checkpoint

Open the Saved-queries drawer from the global bar; Open a saved query → new named tab (and at 10 tabs, the limit dialog instead); Delete → confirm → it's gone and any linked open tab is unlinked. History and Saved-queries buttons are on the global row, not the per-tab toolbar. `npm run test` + `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-19):** Save on an edited linked tab **updates the saved query in place** (name pre-filled), not save-as-new.
- [x] **Resolved (2026-06-19):** saving under an existing name **warns and confirms overwrite**.
- [x] **Resolved (2026-06-19):** a tab opened from a saved query is **labelled with the saved query's name** and shows a **dirty marker** when edited.
- [x] **Resolved (2026-06-19):** History + Saved-queries buttons live on the **global tab-strip row** (right side).
- [x] **Default (2026-06-19):** saved queries persist at **`{username}/athenaresults/saved-queries.json`** (mirrors history; no IAM change). Flag if a different location is preferred.
- [ ] **Saved-queries drawer ordering & pagination.** v1 shows the full list with no pager; order is A–Z **or** most-recently-updated (settle in design). If saved lists grow large, add a SPEC-042-style pager later.
- [ ] **Re-save that also renames.** Re-save lets the user edit the name in the pre-filled prompt; renaming to a free name just updates the record's name, renaming onto another query's name hits the overwrite confirm (FR-003). Confirm this is the desired behavior vs. locking the name on re-save.
