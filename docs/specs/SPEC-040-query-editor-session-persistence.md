# Spec: Query Editor Session Persistence + Clear Button

**ID:** SPEC-040
**Status:** Draft
**Last Updated:** 2026-06-19
**Depends On:** SPEC-035 (query workspace + Monaco editor + Run/Stop toolbar), SPEC-034 (query data layer — unchanged)

> **Design:** Built to the editor toolbar in `docs/design/query-workspace.html` + `design-system.md` §6 (editor toolbar). Adds a **Clear** control to the existing toolbar (alongside History / Stop / Run) and a draft-persistence behavior with no new visual surface. Toolbar layout is an additive change to the §6 toolbar spec.

## Overview

Today the SQL you type into the query editor lives only in `QueryWorkspace`'s local React state (`useState(DEFAULT_SQL)`). The `/query` route is lazy-mounted under `ProtectedLayout`, so the moment you switch to the **Files** tab the workspace unmounts and your un-run query is lost; coming back (or reloading the page) resets the editor to the default boilerplate. This spec makes the editor's current text **survive tab switches and page reloads within the same browser session** by persisting it to `sessionStorage`, and adds a **Clear query** button next to **Run** that empties the editor in one click. The goal is that a user can freely move between Files and Query, or accidentally reload, without losing work they haven't run yet.

## Scope

### In Scope

- Persisting the query editor's current text to `sessionStorage` so it is restored when `QueryWorkspace` remounts (tab switch) or the page is reloaded, for the duration of the browser session
- Keying the persisted draft per-user (by `username`) so one signed-in user's draft is never shown to another on a shared machine
- Restoring the persisted draft into the Monaco editor on mount; falling back to the existing default boilerplate (`DEFAULT_SQL`) only when no draft exists for the user
- A **Clear query** button placed in the editor toolbar in the same control group as **Run** (and the existing **History** control), which empties the editor and clears the persisted draft
- Keeping the persisted draft in sync as the user types (the editor's `onChange`)

### Out of Scope

- Multiple query tabs / multiple editor windows — that is **SPEC-041**, which builds on this and supersedes the single-draft storage model below
- Persisting query **results**, the running `executionId`, status, or history-panel state across reloads — only the editor *text* is persisted (results re-fetch on a fresh run)
- Persistence across full browser **restart** or across other browser tabs/windows — `sessionStorage` is deliberately scoped to the current session/tab (user decision: "during my current session"). Use of `localStorage` is explicitly rejected for v1
- Any change to the SPEC-034 data layer, services, or IAM
- An undo affordance after Clear (Clear confirms first; no undo — see Open Questions)

---

## Functional Requirements

### FR-001: Persist the editor draft to sessionStorage

#### Description:

The current editor text is written to `sessionStorage` under a per-user key whenever it changes, so it can be restored later in the same session.

#### Acceptance Criteria:

- [ ] A single named storage-key helper produces the key `s3portal.query.draft.{username}` (constant prefix in `query.constants.ts`); the key includes the authenticated `username` so drafts are per-user
- [ ] As the user edits, the editor's current value is written to `sessionStorage` under that key (debounced or on `onChange` — implementer's choice, but a write must not be dropped before unmount)
- [ ] Writes go through a small typed wrapper that swallows `sessionStorage` failures (e.g. storage disabled / quota) and never throws — a storage failure degrades to "not persisted," never a crashed editor
- [ ] When `username` is empty/unavailable (unauthenticated dev paths), no write is attempted and the editor behaves exactly as today

### FR-002: Restore the draft on mount

#### Description:

When `QueryWorkspace` mounts, it seeds the editor from the persisted draft if one exists.

#### Acceptance Criteria:

- [ ] On mount, if a non-empty draft exists in `sessionStorage` for the current user, the editor initializes to that text instead of `DEFAULT_SQL`
- [ ] If no draft exists (first visit this session, or after Clear), the editor initializes to `DEFAULT_SQL` exactly as today
- [ ] After switching Files → Query (remount), the previously typed text is shown — verified by the checkpoint
- [ ] After a full page reload, the previously typed text is shown
- [ ] Restoration reads once at mount; it does not fight the user's subsequent typing (no flicker / no overwrite of live edits)

### FR-003: Clear query button

#### Description:

A **Clear** control in the editor toolbar empties the editor and the persisted draft.

#### Acceptance Criteria:

- [ ] A **Clear** button appears in the editor toolbar in the same right-side control group as **Run** (and **History**), styled as a ghost button per `design-system.md` §6 (never color-only state; has an accessible label e.g. `aria-label="Clear query"`)
- [ ] Clicking **Clear** when the editor is non-empty opens a warn-and-confirm dialog (reuse the SPEC-026 dialog pattern); only on confirm does it empty the editor, remove the persisted draft key from `sessionStorage`, and return focus to the editor. Cancel leaves the editor untouched
- [ ] **Clear** is disabled while a query is in flight (consistent with not mutating an executing query's context) and when the editor is already empty
- [ ] After Clear, **Run** is disabled until the user types again (Run already requires non-empty trimmed SQL — `canRun`), confirming Clear and Run share the same active-text source
- [ ] Clearing does **not** touch query history, results, or any other tab/route state

---

## Data Model

No new domain types. The persisted value is a plain `string` (the editor text). Add the storage-key prefix to `query.constants.ts`:

```ts
// apps/portal/src/features/query/query.constants.ts

// SPEC-040: sessionStorage key prefix for the per-user editor draft. The full
// key is `${QUERY_DRAFT_STORAGE_PREFIX}${username}`. sessionStorage (not local)
// is deliberate — the draft lives for the current browser session only.
export const QUERY_DRAFT_STORAGE_PREFIX = 's3portal.query.draft.';
```

## API / Interface Contract

A tiny session-storage helper (co-located in the query feature) keeps `QueryWorkspace` clean and swallows storage errors:

```ts
// apps/portal/src/features/query/queryDraft.ts
export function readQueryDraft(username: string): string | null;   // null if none / storage unavailable
export function writeQueryDraft(username: string, sql: string): void; // no-op on failure
export function clearQueryDraft(username: string): void;            // no-op on failure
```

`QueryWorkspace` initializes its `sql` state from `readQueryDraft(username) ?? DEFAULT_SQL`, calls `writeQueryDraft` on change, and `clearQueryDraft` from the Clear handler.

## File & Folder Structure

```
apps/portal/src/features/query/
├── query.constants.ts        ← + QUERY_DRAFT_STORAGE_PREFIX
├── queryDraft.ts             ← NEW: typed sessionStorage read/write/clear helper
├── queryDraft.test.ts        ← NEW: persistence + error-swallowing tests
├── QueryWorkspace.tsx        ← seed sql from draft, persist on change, Clear button + handler
└── QueryWorkspace.test.tsx   ← + restore-on-mount and Clear behavior tests
```

## Implementation Phases

### Phase 1: Persistence helper + restore/persist wiring

- Add `QUERY_DRAFT_STORAGE_PREFIX` and the `queryDraft.ts` helper (read/write/clear, error-swallowing, per-user key)
- Seed `QueryWorkspace`'s `sql` from `readQueryDraft(username) ?? DEFAULT_SQL`; write on `onChange`
- Unit-test the helper (FR-001/FR-002), including storage-unavailable and empty-username paths

#### Checkpoint

Type a query, switch to **Files**, switch back to **Query** → the typed text is still there (not `SELECT 1;`). Reload the page → the text is still there. Open in a second browser tab with no prior draft → it shows `DEFAULT_SQL` (sessionStorage is per-tab). `npm run test` + `npm run lint` pass.

### Phase 2: Clear button

- Add the **Clear** ghost button to the editor toolbar (group with History/Run), with disabled rules (in-flight, empty editor)
- Wire the handler: confirm dialog (SPEC-026 pattern) → on confirm empty the editor, `clearQueryDraft(username)`, refocus the editor; Cancel is a no-op
- Test the confirm flow, that Clear empties editor + storage on confirm, and that Run is disabled afterward (FR-003)

#### Checkpoint

Click **Clear** with text in the editor → a confirm dialog appears; confirm → the editor empties and **Run** is disabled; reload → editor is empty (no stale draft). Cancel → editor unchanged. **Clear** is disabled while a query is running and when the editor is already empty. `npm run test` + `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-19):** persistence uses **`sessionStorage`** (current-session, survives reload, clears on tab/browser close) keyed per-user — matching "during my current session." `localStorage` rejected for v1.
- [x] **Resolved (2026-06-19):** Clear **confirms first** — clicking Clear on a non-empty editor opens a warn-and-confirm dialog (SPEC-026 pattern) before wiping. No undo affordance in v1.
- [ ] **Interaction with SPEC-041 (tabs).** This spec persists a single draft string. SPEC-041 replaces that with a per-tab persisted model and will supersede `QUERY_DRAFT_STORAGE_PREFIX`/`queryDraft.ts`. Implement 040 standalone; 041 will migrate it (note added there).
