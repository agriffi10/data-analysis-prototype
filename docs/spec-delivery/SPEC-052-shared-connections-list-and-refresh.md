# Completed Spec — SPEC-052: Connections Tab, Connection Lists & Refresh

The read/display + navigation layer of the shared-connections arc: shared connections now appear everywhere they're used, fed by **one** hook, with a home to manage them. No state mutation (create = SPEC-051; manage/leave/delete = SPEC-053/054). Delivered in one app PR.

## What was completed?

- **`useConnections` merges personal + shared (FR-001):** now a TanStack Query hook that reads the per-user cache via the new `readSharedConnectionsCache` (`GetObject` of `{username}/user_settings/shared-connections.json`; forgiving parse → empty on missing/corrupt, drops malformed entries; `ServiceResult`, never throws) and returns the personal DB **+** one `Connection` per shared entry (personal first, shared A–Z) carrying `status`/`role`/`reason`. `Connection` enriched with those optional fields + an `isConnectionUsable` helper (personal or `active` shared). The hook also exposes `refresh` + `isRefreshing`.
- **Connections tab content (FR-002, FR-005):** the rich view moved to `features/shared-spaces/ConnectionsPage.tsx` (`routes/ConnectionsPage.tsx` is now a thin title wrapper, matching `QueryPage`). Lists shared connections — mono name, role pill, status badge (text + icon, never color-only) — merging the cache list with the local optimistic pending entries (cache wins on dupes). Friendly empty state, `Banner` on read error, failed-entry `reason` + **Dismiss** (hide) / **Retry** (re-enqueue create).
- **Refresh connections (FR-003):** `RefreshConnectionsButton` (SPEC-046 pattern) → `useConnections().refresh`, which calls `getSessionCredentials(forceRefresh:true)` (stamps newly-granted `shared_space_k` tags on the next vend) **then** invalidates/refetches the cache. In-flight disables + spins; a failed refresh is non-destructive.
- **Feeding the Query schema rail (FR-004):** `SchemaBrowser`'s database list disables `provisioning`/`failed`/`leaving` shared connections with their status shown; `useActiveDatabase` now derives selectable targets from **usable** connections, so a targeted shared DB that's revoked (flips off `active`) falls back to personal with the existing `fellBack` notice — not only when it disappears from the cache entirely.

Scope note: the per-row **Manage/Leave/Delete** entry points were intentionally **omitted** (in-session user decision) — they land with their targets (the SPEC-053 member drawer / SPEC-054 dialogs) so no dead UI ships on main.

## What changed from earlier specs?

- **SPEC-047 `useConnections`/`useActiveDatabase`/`Connection`:** the seam is now realized — async cache read + merge, `status`/`role`/`reason` fields, usable-only active-target reconciliation. **SPEC-051 `ConnectionsPage` shell:** replaced by the full view (the route file is now a wrapper). **SPEC-035 `PrimaryNav`:** the Connections tab (added in 051) is now covered by a test. No IAM/infra change (this spec only **reads** the per-user cache).

## Verification

`npm run lint` / `build` (tsc + vite) / `test` green — **639 tests** (new: `useConnections` merge + personal-only + refresh; `readSharedConnectionsCache` missing/corrupt/malformed/error; `ConnectionsPage` empty/list/role+status/read-error Banner/refresh-picks-up-active/failed Dismiss+Retry/create; `PrimaryNav` 3 tabs + routes; `SchemaBrowser` disabled provisioning entry; `useActiveDatabase` revoked-DB fallback). A fresh-context review flagged the FR-004 active-target fallback gap (fixed + tested) and found no blockers. Frontend-only; nothing to deploy beyond the app bundle.
