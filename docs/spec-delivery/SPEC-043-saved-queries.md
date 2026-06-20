# Completed Spec — SPEC-043: Saved Queries + Global Workspace Bar

## What was completed?

- Users can **Save** the active tab's SQL under a name, browse all saved queries in a right slide-out
  drawer, **Open** any into a new linked tab, **re-save** in place, **delete** (with confirm), and see a
  **dirty marker** when a linked tab's SQL diverges. A run from a linked tab records the saved query's
  **name in history**. History + Saved-queries buttons move to a **workspace-global bar** on the tab strip.
- `query.types.ts` — `SavedQuery`, `SavedQueriesStore`; `QueryHistoryEntry` += `savedQueryId?` /
  `savedQueryName?` (additive).
- `savedQueries.service.ts` — `getSavedQueries` / `upsertSavedQuery` / `removeSavedQuery` at
  `{username}/athenaresults/saved-queries.json`, same JSON-store pattern as history: `PutObject`
  overwrite only (remove rewrites the JSON — **never an S3 delete**, asserted in tests), missing file →
  empty store, `ServiceResult` (never throws). `useSavedQueries.ts` wraps them (TanStack Query +
  `queryKeys.savedQueries`).
- `SaveQueryDialog.tsx` — name prompt (SPEC-026 pattern), pre-filled on re-save, with an inline
  **overwrite-confirm** step on a case-insensitive collision with a *different* saved query.
- `SavedQueriesPanel.tsx` — right drawer (mirrors the history drawer), most-recently-updated first,
  Open + Delete-with-confirm, empty/loading/error states. Presentational — the workspace owns the data.
- `useQueryTabs.ts` += `setActiveTabMeta` (link + relabel in one step) and `unlinkSavedQuery` (clear the
  link on every tab pointing at a deleted query).
- `QueryWorkspace.tsx` — **Save** button in the per-tab toolbar; owns `useSavedQueries`; derives the
  dirty-tab set; save links/relabels the active tab; Open routes through `openTab` (honoring the
  SPEC-041 cap dialog); delete unlinks open tabs; runs from a linked tab stamp `savedQueryName/Id` onto
  history. `QueryTabStrip.tsx` hosts the global **Saved queries** + **History** buttons and renders the
  dirty `•`. `QueryHistoryRow.tsx` shows a "Saved: {name}" badge when present.

## What changed from earlier specs?

- **SPEC-041 `useQueryTabs`** gained `setActiveTabMeta` / `unlinkSavedQuery` (additive). **SPEC-041
  `QueryTabStrip`** gained the global-bar buttons + `dirtyTabIds` prop. **SPEC-040 `QueryWorkspace`
  toolbar:** History **moved out** to the global bar and a **Save** button was added (per-tab controls
  are now Clear / Save / Stop / Run). **SPEC-036 `QueryHistoryRow`** shows the optional saved-query name.
- No IAM/infra change — the store reuses the SPEC-032/034 `athenaresults/` policy (PutObject allowed,
  delete denied). No data-layer change beyond the additive history-entry fields.
- Design pass already present in `design-system.md` §6 + `query-workspace.html` (authored with the spec).

## Verification

`npm run lint`, `npm run test` (467 pass — +31 across `savedQueries.service` (round-trip, missing-file
empty, remove-never-deletes, unknown-id no-op), `useSavedQueries`, `SaveQueryDialog` (new/re-save/
collision-overwrite/cancel), `SavedQueriesPanel` (list order, open, delete-confirm, empty/error), and
`QueryWorkspace` (save-links-relabels, dirty marker, history name, open-into-tab, delete, global-bar
hoist)), and `npm run build` all pass locally. Live browser checkpoint deferred to deploy — `/query`
needs an authenticated Cognito + Glue session not reproducible in local preview. No new dependency, no
IAM change.

> **For SPEC-044:** `openTab({label, sql})` is the entry point for table-action tabs (view data / view
> DDL); the cap dialog applies for free. `getSavedQueries`/`useSavedQueries` are exported from the barrel.
