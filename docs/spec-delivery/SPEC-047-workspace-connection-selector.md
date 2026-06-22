# Completed Spec — SPEC-047: Workspace Database Switcher

## What was completed?

- **`useConnections(username)`** (`useConnections.ts`) — the single source of databases the user can
  target. Returns exactly one entry today: `{ id:'personal', label:'My workspace', database:username,
  kind:'personal' }` (empty list when no username). This is the documented extension point the
  shared-spaces arc (SPEC-052) feeds `kind:'shared'` entries into without changing consumers.
- **`useActiveDatabase(username, connections)`** (`useActiveDatabase.ts`) — the **workspace-global**
  active database, persisted per-user in `sessionStorage`
  (`s3portal.query.activeDatabase.{username}`), default = personal. Reconciliation is **pure render**
  (no Effect): a stored database no longer in `connections` resolves to personal with a dismissible
  `fellBack` notice, and re-applies if that DB reappears (sticky preference). New constant
  `QUERY_ACTIVE_DB_STORAGE_PREFIX`; new types `Connection` / `ConnectionKind`.
- **`QueryWorkspace`** no longer hard-codes `const database = username` — it derives `database` from
  `activeDatabase`, so the schema query (`useSchema`), the Run target (`runQuery({ database })`), and
  schema-changing-SQL invalidation all follow the active database for **all tabs** (not per-tab). A
  non-blocking info `Banner` surfaces the fall-back. Results still route to `{username}/athenaresults/`
  (the run passes `username` unchanged).
- **`SchemaBrowser`** Database section is now a switchable list (`useConnections` entries): each a
  keyboard-operable button, the active one marked with **`aria-current`** + an sr-only "(current
  database)" label (state, not color-only); a single database shows one current item and implies no
  switching. New optional props `connections` / `onSelectDatabase` (the `database` prop still drives the
  schema query). The editor toolbar's `db-chip` already reflects the active database **read-only** (no
  dropdown — switching is the rail's job).

## What changed from earlier specs?

- **SPEC-035 `SchemaBrowser`** gained `connections` / `onSelectDatabase` (optional, back-compatible).
  **SPEC-041:** the active database is **workspace-global**, which **supersedes** the earlier per-tab
  `QueryTab.database` idea (tabs never carried a database). **SPEC-043 `SavedQuery.database`** is now
  the active database at save time (was always `username`).
- No IAM/infra change — the only reachable database today is the user's own; the seam is forward-only.

## Verification

`npm run lint`, `npm run build`, and `npm run test` (**572 pass**, +15: `useConnections` personal-only/
empty/stable-ref; `useActiveDatabase` default/persist/set/fallback+dismiss/reappear/no-username;
`SchemaBrowser` keys schema off active DB, lists DBs with aria-current, select fires callback,
single-DB; `QueryWorkspace` chip reflects active DB, switching retargets Run for the active tab +
persists + still routes to `{username}/athenaresults/`) all green locally. Live `/query` checkpoint
deferred to deploy (authenticated Cognito + Glue session). No new dependency, no IAM change.
