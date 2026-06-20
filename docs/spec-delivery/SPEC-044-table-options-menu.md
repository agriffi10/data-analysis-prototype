# Completed Spec — SPEC-044: Schema Browser Table Options Menu

## What was completed?

- Each schema-browser table row gets a **⋮ options menu** (revealed on hover/focus, keyboard-reachable)
  with four actions: **View source files**, **View DDL**, **View data**, **Drop table**.
- `TableActionsMenu.tsx` — the app's first **reusable menu/popover primitive**: `aria-haspopup`/
  `expanded`, focus into the menu, Escape + outside-click close (focus returns to the trigger),
  arrow-key nav; clicks stop propagation so opening it never toggles the row.
- **View source files** — derives the table's in-space S3 key from `GlueTableSummary.location` and
  navigates to **`/files?prefix={key}`**; disabled when the location is missing or outside the user's
  prefix. The file browser now reads `?prefix=` on mount (`FilesPage`), honoured only when within the
  user's space (the navigation floor); absent/out-of-space → today's root behavior.
- **View DDL** — `getTableDdl(database, table, username)` runs `SHOW CREATE TABLE` via Athena (poll →
  results, joined with newlines), then `openTab({ label: 'DDL: {table}', sql })` **not auto-run**;
  no history entry for the fetch.
- **View data** — `openTab({ label: '{table}', sql: SELECT * … LIMIT TABLE_PREVIEW_ROW_LIMIT })` and
  **auto-runs** it (via `submit(sql, tabId)` into the just-opened tab — before `activeTabId` commits).
- **Drop table** — `DropTableDialog` confirm → background `DROP TABLE` (`runStatementToCompletion`) →
  appends a history entry, `invalidateSchema` on success, and a **toast** (new `Toast.tsx` primitive,
  success/danger auto-dismiss, `info` "working…" notice cleared by the caller).
- `query.constants.ts` += `TABLE_PREVIEW_ROW_LIMIT = 10`. `query.service.ts` += `getTableDdl` and the
  shared `runStatementToCompletion` (run + poll to terminal, used by DDL and Drop).
- All tab-opening actions route through SPEC-041 `openTab` and honor the FR-008 tab-limit dialog.

## What changed from earlier specs?

- **SPEC-035 `SchemaBrowser`** now requires an `actions` prop (the four callbacks + `canViewSourceFiles`)
  and hosts the kebab per row. **SPEC-013 file browser:** `FilesPage` reads `?prefix=` and seeds/keys
  the `FileBrowser` (the browser already accepted an initial `prefix`); internal folder navigation still
  doesn't touch the URL. **`QueryWorkspace` `submit`** gained an optional `tabId` (defaults to active).
- No IAM/infra change — DDL/preview/drop run through the existing shared role + Athena/Glue (SPEC-032/
  033/034); the deep-link is frontend-only (same bucket/prefix the user already browses).

## Verification

`npm run lint`, `npm run test` (486 pass — +39 across `TableActionsMenu` (open/close/Escape/outside-click/
arrow-nav), `SchemaBrowser` (menu fires actions without toggling expand, disabled out-of-space,
Escape-close), `query.service` (`getTableDdl` assembles DDL + issues SHOW CREATE TABLE + failure path,
`runStatementToCompletion`), `FilesPage` (`?prefix=` in-space/out-of-space/absent), and `QueryWorkspace`
(navigate, DDL→non-run tab, data→tab+auto-run, drop→confirm→history+success toast, drop-failure toast)),
and `npm run build` all pass locally. Live browser checkpoint deferred to deploy — `/query` needs an
authenticated Cognito + Glue session not reproducible in local preview. No new dependency, no IAM change.
