# Completed Spec — SPEC-048: Create View from Query + Views in the Schema Browser

## What was completed?

- **Create view** button in the editor toolbar (Run/Save group), disabled when the active tab's SQL is
  empty/whitespace. Opens **`CreateViewDialog`** — a name-prompt modal (SPEC-026 `Modal`) validating the
  name against the shared **catalog-safe identifier rule** `CATALOG_IDENTIFIER_RE`
  (`^[a-z][a-z0-9_]{2,62}$`, new in `query.constants.ts`, the SPEC-033 rule de-duplicated), with an
  inline error and Create disabled until valid.
- On confirm it composes `CREATE OR REPLACE VIEW {activeDatabase}.{name} AS {sql}` (trailing
  `;`/whitespace stripped via the new `stripTrailingSemicolons`, `query.sql.ts`) against the **active
  workspace database** (SPEC-047) and runs it **in the background** (`runStatementToCompletion`) — the
  editor keeps showing the user's SELECT. Success → `invalidateSchema` + "Created view {name}" toast;
  failure → error toast with the Athena reason. The run **appends one history entry**.
- **Schema browser is view-aware:** `tableType === 'VIRTUAL_VIEW'` rows show a **View** badge and expand
  to columns like tables. The per-table options menu (SPEC-044) branches on `tableType`:
  **View DDL** → `getTableDdl({…, isView})` runs **`SHOW CREATE VIEW`**; **Drop** → label "Drop view",
  `DropTableDialog isView`, and the run issues **`DROP VIEW`**; **View source files** is disabled (a view
  has no `location` → `canViewSourceFiles` already false); **View data** previews rows unchanged.

## What changed from earlier specs?

- **SPEC-044 `getTableDdl`** gained an `isView?` param (`SHOW CREATE VIEW` vs `SHOW CREATE TABLE`);
  `DropTableDialog` gained an `isView?` prop (view copy/labels); `QueryWorkspace.handleDropConfirm`
  issues `DROP VIEW` for a view. **SPEC-035 `SchemaBrowser`** renders the view badge + view-aware menu
  labels. All reuse the existing SPEC-044 plumbing (tab-cap dialog, Toast, schema refresh).
- No IAM/infra change — create/drop a view in the user's own DB uses the existing SPEC-033 grants
  (`CREATE_TABLE`/`ALTER`/`DROP`). `CREATE OR REPLACE VIEW` is the idempotent edit path (no exists
  pre-check); a name colliding with a real table surfaces as the Athena error toast.

## Verification

`npm run lint`, `npm run build`, and `npm run test` (**586 pass**, +14: `CreateViewDialog` validation/
confirm/cancel/busy; `query.service` `SHOW CREATE VIEW`; `SchemaBrowser` view badge + "Drop view" +
disabled source-files; `QueryWorkspace` create-view compose/background/history/toast, error toast,
view-DDL `isView`, `DROP VIEW`, source-files-disabled-for-view) all green locally. Live `/query`
checkpoint deferred to deploy. No new dependency, no IAM change.
