# Completed Spec — SPEC-041: Multi-Tab Query Editor

## What was completed?

- The query editor is now **multi-tab**: each tab is an independent query window with its own SQL +
  run state. Switching tabs swaps the editor and that tab's status/results without losing any tab's
  text. The full tab set (text, order, active tab, next number) persists per-user to `sessionStorage`
  across Files↔Query remounts and reloads. **Run / Clear / Stop / status / results / CSV all act on the
  active tab.**
- `query.types.ts` — `QueryTab` (`id`/`label`/`sql`/`savedQueryId?`), `QueryTabsState`
  (`version`/`tabs`/`activeTabId`/`nextQueryNumber`).
- `query.constants.ts` — `QUERY_TABS_STORAGE_PREFIX` (`s3portal.query.tabs.{username}`),
  `QUERY_TABS_MAX = 10`, and `DEFAULT_SQL` (moved here from `QueryWorkspace`, now shared).
- `queryTabs.ts` — `readTabsState` (structural validation; corrupt/foreign blob → null),
  `writeTabsState` (error-swallowing, empty-username no-op), `initialTabsState` (single `Query 1`,
  `nextQueryNumber=2`), `migrateDraftToTabs` (one-time SPEC-040 seed: draft → tab 1's sql, then removes
  the old key).
- `useQueryTabs.ts` — owns the state + persistence; `openTab({label?,sql?,savedQueryId?})` (returns the
  new id or **null at cap** for the caller's FR-008 dialog; named tabs don't consume a `Query N`),
  monotonic `Query N` labelling, `closeTab` (≥1-tab invariant + adjacent-activate, prefer left),
  `setActiveSql`/`setActiveTab`/`setActiveSavedQueryId`/`clearActive`.
- `QueryTabStrip.tsx` — the card-tab strip (active = surface+border+leading accent dot; per-tab `×`
  hidden when solo; always-enabled `+`), built to design-system §6.
- `TabLimitDialog.tsx` (FR-008 informational alert) + `CloseTabDialog.tsx` (FR-005 warn-and-confirm for
  non-empty tabs); both reuse the SPEC-026 pattern.
- `QueryWorkspace.tsx` — renders the strip + dialogs; holds per-tab in-memory run state (`runs`/
  `statuses`/`runErrors`/`dismissed` maps keyed by tab id); a headless `TabExecutionPoller` per running
  tab gives **concurrent background polling** (a backgrounded query finalizes history/schema without
  waiting for the user to return — FR-004).

## What changed from earlier specs?

- **Supersedes SPEC-040:** `queryDraft.ts` + `queryDraft.test.ts` were **removed**; the single-draft
  store is folded into the tabs model. `QUERY_DRAFT_STORAGE_PREFIX` is retained only for the one-time
  migration. `ClearQueryDialog` (SPEC-040) is reused as-is, now scoped to the active tab.
- **SPEC-035 `QueryWorkspace`** was substantially reworked: editor text + Run/Clear/Stop/status/results
  are now per active tab (was a single `useState`); history Re-open/Re-run target the active tab. No
  change to the SPEC-034 data layer, services, or IAM. The SPEC-043 hoist of History/Saved-queries onto
  the tab-strip row is **not** part of this spec — History remains in the editor toolbar for now.
- Phase 1 (design pass) was already present in `query-workspace.html` + `design-system.md` §6 (authored
  with the spec); no design change was needed.

## Verification

`npm run lint`, `npm run test` (428 pass — +25 across `queryTabs` round-trip/validation/migration,
`useQueryTabs` monotonic-numbering/cap/close-activate/isolation/persist, `QueryTabStrip`, and
`QueryWorkspace` restore/migrate/new-tab-isolation/close-confirm/tab-limit/Clear/**concurrent-finalize**),
and `npm run build` all pass locally. Live browser checkpoint deferred to deploy — `/query` needs an
authenticated Cognito + Glue session not reproducible in local preview. No new dependency, no IAM change.

> **For SPEC-043/044:** `openTab({label, sql, savedQueryId?})`, `useQueryTabs`, `QueryTab`,
> `QUERY_TABS_MAX` are exported from the feature barrel. All tab-open paths already route through the
> `openTab` cap guard, so the FR-008 dialog applies to saved-query / table-action opens for free.
