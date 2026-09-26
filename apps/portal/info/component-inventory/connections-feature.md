# Connections feature (`apps/portal/src/features/connections/`)

Part of the component inventory (`INDEX.md`, beside this file, is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.

The databases a signed-in user can target — the personal DB plus every shared space — and the two
nav surfaces that list them. Extracted from `features/query/` and `features/shared-spaces/` by
SPEC-155 FR-005, so no feature is a de-facto shared layer.

| Symbol | File | Purpose |
|---|---|---|
| `useConnections(username)` | `useConnections.ts` | **The** source of databases the user can query (`Connection[]` + `refresh`/`isRefreshing`/`reconcile`, and `listReadsSettled` — a count of settled reads, failed ones included, that only grows — with `rereadList`, one more read unless one is running; a caller concluding a space is ABSENT waits for the count to pass where it stood when the question arose, since `isLoading` clears on any cached list and a list read before the question may predate the space): merges the personal DB with shared entries read from the per-user cache (personal first, shared A–Z); `refresh` forces a credential refresh then refetches; `reconcile` also opens a bounded 30s/4s polling window so a just-submitted action's pending → active transition is picked up without a manual Refresh; missing/corrupt cache → personal-only. One hook feeds the schema rail, Files list, and Shared spaces tab (SPEC-047/052). |
| `useSpaceLinkPending({username, space, missing, listReadsSettled, rereadList})` | `useSpaceLinkPending.ts` | True while the space a link names (`?space=`, `:space`) is `missing` from the list and no read of it has settled since the link was followed — each follow, the same link again included, a POP excepted — and asks for that read through `rereadList`. The one anchor for refusing a linked space on the list's word: Files, the Data Explorer and the Data Quality report all call it, each passing whether its own resolution found the space. |
| `Connection` / `ConnectionKind` / `isConnectionUsable` | `connection.types.ts` | `{id,label,database,kind:'personal'\|'shared',status?,role?,reason?,members?,createdAt?,owner?}` — a targetable database; `members?` is the owner-readable projection (SPEC-053/075); `isConnectionUsable` = personal or `active` shared (SPEC-047/052). |
| `connectionStatusLabel(status)` | `connectionStatus.ts` | Human label for a shared connection's lifecycle status (Provisioning…/Active/Failed/Leaving…/Deleting…); shared by the Connections badge, the `SpacesList` hint and the disabled schema-rail hint (SPEC-052; `deleting` added SPEC-054). |
| `Sidebar` | `Sidebar.tsx` | Left nav for the authenticated shell — composes `SpacesList` inside `CollapsibleRail` (SPEC-085). Rendered by `FilesPage` (SPEC-057). |
| `SpacesList` | `SpacesList.tsx` | The spaces list itself (`{connections, activeSpaceId, onSelectSpace}`; personal first, shared A–Z, pending/failed disabled). Decoupled from rail chrome so it renders both on-page (`Sidebar`) and in the mobile `AppNavDrawer` contextual slot via `useProvideNavRail` (SPEC-099). |

> The TanStack key stays `queryKeys.connections` in `features/query/queryKeys.ts` — the key
> namespace was not split, so invalidation sites keep one factory.
