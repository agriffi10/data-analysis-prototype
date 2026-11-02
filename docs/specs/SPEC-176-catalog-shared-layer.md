---
type: Spec
id: SPEC-176
title: "Extracting `features/catalog/` — the Shared Catalog & Execution Layer"
description: "Moves the Glue catalog reader, Athena execution layer, results pager and column-width code into a shared features/catalog/ for developers, with no user-visible change, ahead of the Data Explorer."
spec_status: Completed
depends_on: []
arc: data-explorer
arc_order: 1
---

**Dependency notes:** None (pure refactor of shipped code; first spec of the Data Explorer arc)
## Overview

The portal is about to gain a second feature that reads the Glue catalog and runs Athena
queries — the Data Explorer (SPEC-179 onward). Everything it needs to do that lives inside
`features/query/` today: the Glue schema reader, the space list, the Athena
start/poll/results/cancel layer, the results pager, the background row-count walk and the
column-width machinery. A `features/data-explorer/` that imported those from `features/query/`
would recreate exactly the undeclared shared layer SPEC-155 spent a whole spec dismantling,
and the ESLint rule that now guards `components/`, `lib/` and `hooks/` does not catch
feature-to-feature imports.

This spec moves that shared ground into a new `features/catalog/` before any Data Explorer
code exists, so the arc is never in a position where the cheap thing to do is the wrong thing.
It ships **no user-visible change whatsoever** — no new behaviour, no altered wording, no
changed network call. It leads the arc because it is the change most likely to go wrong and
the one everything else is built on.

## Scope

### In Scope

- A new `features/catalog/` owning the Glue reader, the space list, the Athena execution and
  results layer, and the column-width store.
- Splitting the four `query.*` modules whose contents are only partly shared:
  `query.types.ts`, `query.constants.ts`, `query.format.ts`, `queryKeys.ts`.
- A new `catalogKeys` TanStack key namespace for everything that moves, replacing the moved
  members of `queryKeys`.
- Moving `formatBytes` to `lib/format.ts`, beside the `formatSize` it already shares a
  ceiling with (SPEC-155 FR-007), so neither feature owns a formatter the other needs.
- Moving `queryKeys.connections` into `features/connections/`'s own key module — one of the
  two residual layering inversions SPEC-155 recorded, and in the blast radius of this spec's
  key split whether or not it is addressed.
- Extending the SPEC-155 ESLint layering rule to forbid `features/query/` and
  `features/data-explorer/` importing each other.
- Rewriting every internal import. **60 of the ~76 files under `features/query/` import at
  least one moving module** — `query.types.ts` and `query.constants.ts` are imported almost
  everywhere, which is what makes this a large mechanical diff rather than a small one.

  > **Corrected in build (2026-08-13).** This bullet originally claimed only one file outside
  > the feature was affected (`routes/QueryPage.tsx`, which imports `QueryWorkspace` and is
  > indeed untouched). **Six are**, and they repoint to `features/catalog/`:
  > `features/table-builder/useTableRefresh.ts` (`invalidateSchema`, `GlueTableSummary`),
  > `features/table-builder/tableRefresh.types.ts` (`GlueTableSummary`),
  > `features/table-builder/tableBuilderHooks.test.tsx` (`queryKeys.schema`),
  > `features/table-share/TableShareDialog.test.tsx` (`queryKeys.connections`),
  > `features/feature-flags/gatedSurfaces.test.tsx` (a `vi.mock` of `../query/glue.service`),
  > plus the two FR-005 already names. The correction **strengthens** the spec's premise
  > rather than widening its scope: `features/table-builder/` was already reaching into
  > `features/query/` for the Glue reader and the schema key, which is the undeclared shared
  > layer this spec exists to declare. Nothing about what gets built changes.

### Out of Scope

- **Any component move.** `SchemaBrowser`, `DatabaseNode`, `QueryResultsTable` and every
  dialog stay in `features/query/`. The Data Explorer's picker and grid are different
  components with different requirements (SPEC-179/180), and SPEC-155's precedent is to move
  the *domain*, not every consumer.
- **The saved-query store.** `savedQueries.service`, `useSavedQueries`, `useSavedQueriesPager`,
  `useSavedQuerySpace`, `savedQuerySpace.ts` and `SavedQuerySpaceSelect` are SPEC-177's
  extraction, deliberately separated so a difficult move there cannot block this one.
- **Query history, tabs, the editor layout, the mobile query surface, SQL parsing
  (`query.sql.ts`), completions and DDL helpers.** All query-workspace-specific; none move.
- **Renaming anything that moves.** A moved module keeps its filename and its exported names,
  so the diff is reviewable as a path change. The four splits are the only exception, and only
  because part of each stays behind.
- **Behaviour changes of any kind**, including cache-key semantics beyond the namespace
  prefix, error wording, and the `getTableDdl` / `runStatementToCompletion` call sites.
- The second residual inversion SPEC-155 recorded, if it is not `queryKeys.connections`.

---

## Functional Requirements

### FR-001: `features/catalog/` exists and owns the shared modules

#### Description:

A new feature directory holds every module both the Query workspace and the Data Explorer
need, with a barrel `index.ts` as its only public surface.

Modules that move **whole**, keeping their filenames and exported names:
`query.service.ts` → `athena.service.ts` (the one rename, because `query.service` inside
`catalog/` would misdescribe a module that is entirely Athena's API), `glue.service.ts`,
`useSchema.ts`, `useQuerySpaces.ts`, `useQueryExecution.ts`, `useQueryResults.ts`,
`useResultRowCount.ts`, `useColumnWidths.ts`.

#### Acceptance Criteria:

- [ ] `features/catalog/index.ts` exports every symbol previously exported from
      `features/query/index.ts` that originates in a moved module, under the same names.
- [ ] No module under `features/catalog/` imports from `features/query/`.
- [ ] `features/query/index.ts` no longer re-exports any moved symbol; consumers import from
      `features/catalog/` directly.
- [ ] `npm run build -w apps/portal` passes (the only typecheck).
- [ ] The full Vitest suite passes with a zero exit code, with no test's assertions changed
      to accommodate the move — import paths only.

### FR-002: The four partly-shared modules are split, not moved

#### Description:

`query.types.ts`, `query.constants.ts`, `query.format.ts` and `queryKeys.ts` each contain both
shared and query-only members. Each is split along that line, with the shared half landing in
`features/catalog/` and the remainder staying in `features/query/`.

The split lines:

| Module | Moves to `catalog/` | Stays in `query/` |
|---|---|---|
| `query.types.ts` | `QueryState`, `QueryStatus`, `QueryColumn`, `QueryResultPage`, `GlueColumn`, `GlueTableSummary`, `QuerySpace` | `QueryHistoryEntry`, `QueryHistory`, `ParsedStatement`, `RunScope`, `ResultTab`, `MobileQueryView`, `MobileHomeTab`, `QueryTab`, `QueryTabsState`, `SavedQuery`, `SavedQueryPage`, `SavedQueryLink` |
| `query.constants.ts` | `POLL_INTERVAL_MS`, `MAX_POLL_DURATION_MS`, `DEFAULT_MAX_ROWS`, `ROW_COUNT_PAGE_SIZE`, `DEFAULT_COLUMN_WIDTH`, `MIN_COLUMN_WIDTH`, `COLUMN_RESIZE_STEP_PX` | everything else, including the page-size, tabs, history, saved-query and editor-layout constants |
| `query.format.ts` | `normalizeColumnType` | `normalizeCsvName` |
| `queryKeys.ts` | `schema`, `execution`, `results`, `rowCount` (as `catalogKeys`) | `history`, `savedQueries` |

`formatBytes` goes to neither — see FR-004.

> **Corrected in build (2026-08-13): there is a fifth split.** `DatabaseSchema`
> (`{database, tables: GlueTableSummary[]}`) was declared in `query/sqlCompletions.ts`, which
> stays — but `useSchema.ts`'s `useAllSchemas` **produces** it and moves, so leaving it behind
> breaks FR-001 AC2 on the first file moved. It is in `catalog.types.ts`, imported by
> `sqlCompletions.ts`. Where a producer sits in the lower layer, the type goes with the
> producer.

#### Acceptance Criteria:

- [ ] Each of the four modules exists in both features, and no symbol is exported from both.
- [ ] `features/query/query.types.ts` imports the moved types from `features/catalog/` where
      it still references them (e.g. `SavedQueryLink` is unaffected, but any query-only type
      referencing `QuerySpace` re-imports it).
- [ ] The page-size constants stay in `features/query/` — `MAX_RESULTS_PAGE_SIZE` is a
      SPEC-087 workspace preference, not a property of Athena.
- [ ] `ROW_COUNT_PAGE_SIZE` moves, because `useResultRowCount` moves and is its only consumer.

### FR-003: `catalogKeys` replaces the moved `queryKeys` members

#### Description:

The moved hooks key their caches under a new `catalogKeys` namespace rooted at `['catalog']`,
mirroring the `queryKeys` / `dataQualityKeys` / `featureFlagKeys` house pattern. `queryKeys`
survives with only its query-only members.

A moved key must not keep the `['query', …]` prefix: a key namespace that names a feature the
module no longer belongs to is the same hidden coupling this spec exists to remove, and it
would make a future `invalidateQueries({queryKey: queryKeys.all})` silently reach into the
Data Explorer's caches.

#### Acceptance Criteria:

- [ ] `catalogKeys` exports `all`, `schema`, `execution`, `results` and `rowCount` with
      signatures identical to their `queryKeys` predecessors.
- [ ] `queryKeys` retains `all`, `history` and `savedQueries` and nothing else.
- [ ] `invalidateSchema` moves with the schema key and continues to invalidate exactly the
      same set of queries.
- [ ] No module hand-builds a key array for a moved query.
- [ ] Cache keys are in-memory and per session, so the prefix change requires no migration and
      the spec asserts none.

### FR-004: `formatBytes` moves to `lib/format.ts`

#### Description:

`formatBytes` renders a byte count for the query status bar; the Data Explorer needs the same
rendering for its per-execution bytes-scanned display. It is a pure formatter with no feature
domain, and `lib/format.ts` already holds `formatSize`, with which SPEC-155 FR-007
deliberately aligned its TB ceiling.

#### Acceptance Criteria:

- [ ] `formatBytes` is exported from `lib/format.ts` and from neither feature.
- [ ] Its `undefined` handling is unchanged — SPEC-155 kept the two formatters separate for
      exactly this, and merging them is out of scope.
- [ ] The shared TB ceiling still holds: a test renders the same byte count through
      `formatBytes` and `formatSize` and asserts both say `TB` above the threshold.

### FR-005: `queryKeys.connections` moves to `features/connections/`

#### Description:

`features/connections/useConnections.ts` imports `queryKeys` from `features/query/` — a shared
feature reaching into a leaf feature, which is the SPEC-155 inversion in miniature. The
connections key moves into a `connectionKeys` module owned by `features/connections/`.

#### Acceptance Criteria:

- [ ] `features/connections/` imports nothing from `features/query/`.
- [ ] `features/shared-spaces/useSpaceSuggestions.test.ts` seeds its cache through the new
      module.
- [ ] `queryKeys` no longer exports `connections`.

### FR-006: The layering rule is extended and enforced

#### Description:

The SPEC-155 ESLint rule that forbids `components/`, `lib/` and `hooks/` importing from
`features/` gains a companion clause: `features/query/` and `features/data-explorer/` may not
import from each other. The rule must fail on a deliberate violation, not merely be present.

`features/data-explorer/` does not exist yet. The rule names it anyway, so that the first file
created there in SPEC-179 lands under a guard that is already working rather than one added
after the fact.

#### Acceptance Criteria:

- [ ] `npm run lint -w apps/portal` fails when a file in `features/query/` imports from
      `features/data-explorer/`, and when the reverse is added — **verified by making both
      violations and observing the failures**, not by reading the config.
- [ ] The rule's existing exemptions (tests, and `Header` / `ProtectedLayout` by name) are
      unchanged.
- [ ] The rule does not forbid either feature importing from `features/catalog/`.

### FR-007: No user-visible change

#### Description:

The spec is complete only if nothing a user can observe has changed.

#### Acceptance Criteria:

- [ ] No file under `apps/portal/src/features/help/` changes — there is nothing to document,
      and the completion ritual's user-facing sweep records that explicitly.
- [ ] No wording in `lib/errorMessages.ts` changes.
- [ ] No AWS call's parameters change: the Athena `StartQueryExecution`, `GetQueryResults`
      (including the first-page `+1` header overfetch) and Glue calls are byte-identical.
- [ ] The coverage floors in the portal Vitest config (91/86/89/93, SPEC-150) still pass
      without being lowered.

---

## Data Model

No new types. The types below **move** from `features/query/query.types.ts` to
`features/catalog/catalog.types.ts` unchanged:

```ts
// apps/portal/src/features/catalog/catalog.types.ts

export type QueryState = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';

export type QueryStatus = {
  queryExecutionId: string;
  state: QueryState;
  stateChangeReason?: string;
  dataScannedBytes?: number;
  engineExecutionTimeMillis?: number;
  outputLocation?: string;
};

export type QueryColumn = {name: string; type: string};

export type QueryResultPage = {
  columns: QueryColumn[];
  rows: string[][];
  nextToken?: string;
};

export type GlueColumn = {name: string; type: string};

export type GlueTableSummary = {
  name: string;
  columns: GlueColumn[];
  tableType?: string;
  location?: string;
};

export type QuerySpace = {
  id: string;
  label: string;
  bucket: string;
  rootPrefix: string;
  rootLabel: string;
};
```

The one genuinely new module is the key namespace:

```ts
// apps/portal/src/features/catalog/catalogKeys.ts

export const catalogKeys = {
  all: ['catalog'] as const,
  schema: (db: string) => [...catalogKeys.all, 'schema', db] as const,
  execution: (id: string) => [...catalogKeys.all, 'execution', id] as const,
  results: (id: string, pageSize: number) => [...catalogKeys.all, 'results', id, pageSize] as const,
  rowCount: (id: string) => [...catalogKeys.all, 'rowCount', id] as const
};
```

---

## File & Folder Structure

```
apps/portal/src/
├── features/
│   ├── catalog/                     # NEW
│   │   ├── index.ts
│   │   ├── catalogKeys.ts
│   │   ├── catalog.types.ts
│   │   ├── catalog.constants.ts
│   │   ├── catalog.format.ts        # normalizeColumnType
│   │   ├── athena.service.ts        # was query.service.ts
│   │   ├── glue.service.ts
│   │   ├── useSchema.ts
│   │   ├── useQuerySpaces.ts
│   │   ├── useQueryExecution.ts
│   │   ├── useQueryResults.ts
│   │   ├── useResultRowCount.ts
│   │   ├── useColumnWidths.ts
│   │   └── *.test.ts                # the moved modules' existing tests, paths rewritten
│   ├── connections/
│   │   └── connectionKeys.ts        # NEW — was queryKeys.connections
│   └── query/                       # everything not listed above stays
└── lib/
    └── format.ts                    # gains formatBytes
```

---

## Implementation Phases

### Phase 1: The shared layer's data modules

- Create `features/catalog/` with the barrel.
- Move the eight whole modules and their co-located tests; rename `query.service.ts` to
  `athena.service.ts`.
- Split `query.types.ts` and `query.constants.ts` along the FR-002 table.

### Phase 2: Keys and formatters

- Introduce `catalogKeys`; strip the moved members from `queryKeys`.
- Create `features/connections/connectionKeys.ts` and repoint `useConnections` and the
  `shared-spaces` test.
- Split `query.format.ts`; move `formatBytes` to `lib/format.ts` and add the shared-ceiling
  test.

### Phase 3: Import rewrites across `features/query/`

- Repoint all 60 internal consumers; drop the moved re-exports from `features/query/index.ts`.
- Confirm `routes/QueryPage.tsx` — the one importer from outside the feature — is untouched.

### Phase 4: The layering rule and verification

- Extend the ESLint rule to cover `features/query/` ↔ `features/data-explorer/`.
- Verify it by committing a deliberate violation in each direction, observing the lint
  failure, and reverting.
- Run format, lint, the full suite (checking the exit code, not the pass count) and
  `npm run build`.
