# Completed Spec — SPEC-086: Per-Database Schema Refresh (Look for New Tables/Views)

## What was completed?

Each expanded schema-rail `DatabaseNode` gained a **Refresh** control that re-reads **only that database's**
tables/views on demand — so tables created outside the session (Table Builder, another tab/device, a teammate)
appear without reloading the app. Presentation-only; no data-layer/service/IAM/infra change.

- **`DatabaseNode` header Refresh (FR-001):** an `IconButton` (`aria-label="Refresh tables in {label}"`, reusing the
  SPEC-046 spin affordance), shown only on **expanded** nodes (schema loads on expand, so there's nothing to refresh
  while collapsed — also naturally satisfies "no control on the `UnusableNode`"). Wired to
  `invalidateSchema(queryClient, connection.database)` — invalidates just `queryKeys.schema(database)`; the expanded
  node is an active observer so it refetches. It never toggles expansion or changes any active target (there is none
  post-SPEC-077).
- **In-flight + isolation (FR-002):** disabled + spinning driven by the node's own `useSchema` `isFetching` (blocks
  overlapping refetches for that node); other nodes have their own per-DB query + `isFetching`, so one refresh never
  spins/refetches/collapses another.
- **Error path (FR-003):** the node's existing error/"Setting up…" treatment is unchanged; a refetch that fails while
  the node already has data keeps the previously-loaded tables/views visible — TanStack retains `data` and `isError`
  stays false on a background refetch failure, so the refresh is non-destructive (no separate error+data view added).

## What changed from earlier specs?

`DatabaseNode` now consumes `useQueryClient`, so `DatabaseNode`/`SchemaBrowser` tests render inside a
`QueryClientProvider` (and mock `invalidateSchema`). No production signature changed. Also hardened the test harness'
`localStorage` polyfill (SPEC-085) to define-once + clear-per-test rather than redefining the global before every
test.

## Verification

`format:check`, `tsc`/`build`, ESLint, Vitest **926 passed** (default + forks pools). New `DatabaseNode` tests:
Refresh present when expanded / absent when collapsed, scoped `invalidateSchema` call, disabled+spinner while
`isFetching`, re-enabled after, and a freshly-read table appears / removed one drops on re-render. Live browser
deferred — `/query` is Cognito-gated and needs live Athena/Glue; behavior is covered by the component tests.
