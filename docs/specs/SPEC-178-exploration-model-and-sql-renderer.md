# Spec: The Exploration Model, the SQL Renderer and the Execution Cache

**ID:** SPEC-178
**Status:** Completed
**Last Updated:** 2026-08-13
**Depends On:** SPEC-176, SPEC-177

## Overview

The Data Explorer's whole behaviour reduces to one idea: a user's grid gestures are a
*description of a query*, and the app renders that description into SQL and runs it. This spec
builds that engine and nothing else — no route, no grid, no visible surface. It exists ahead of
every UI spec because it settles the two things that would be expensive to get wrong later: the
shape of an exploration (including the union that lets a saved `.sql` file be a source), and the
first place in this codebase where the browser interpolates user-supplied **values** into SQL.

Everything the portal builds today is either typed by a user into Monaco or assembled from
identifiers already validated against `CATALOG_IDENTIFIER_RE`. A filter value is neither, and
there is no TypeScript literal escaper in the repo. This spec adds one, and it must be the
Trino/DML rule — double the single quote — not the Hive/DDL backslash rule the Python side also
carries for a different dialect.

## Scope

### In Scope

- `features/data-explorer/` with the `Exploration` model and its types.
- `ExplorationSource` as a **union from the start**: a `table` arm and a `sql` arm, with only
  the `table` arm reachable until SPEC-183.
- `renderExplorationSql()` — the single SQL builder for the whole feature.
- `sqlLiteral()` and `sqlIdentifier()` in `lib/` — the escapers, with the DML/DDL distinction
  documented at the definition.
- The execution cache: one Athena execution per distinct rendered SQL, reusing SPEC-176's
  `athena.service`, `useQueryExecution` and `useQueryResults`.
- Per-execution and cumulative-per-tab cost accounting (bytes scanned, engine time).
- Exploration tab **state** (`useExplorationTabs`) with `sessionStorage` persistence and a cap.

### Out of Scope

- **Every visible surface.** No route, no page, no tab strip component, no grid, no filter UI.
  SPEC-179 mounts the first of them. This spec's tests drive the model directly.
- **The feature flag.** `dataExplorer` arrives in SPEC-179; nothing here is gated because
  nothing here renders.
- **Presentation state** — column visibility, order, pinning, widths, colours, transformers.
  Defined in SPEC-180 and SPEC-184. This spec establishes only that the renderer cannot see it.
- **The `sql` arm's UI and its refusals.** The union exists; loading a file into it is
  SPEC-183, which also owns the multi-statement and non-`SELECT` refusals.
- **Grouping's UI.** The `Grouping` type and its rendering are here; the panel is SPEC-182.
- Any change to the Query workspace.

### Corrections made during the build

- **`ColumnFilter` gains an optional `valueKind: 'string' | 'number'`, and FR-004 AC2 is
  narrowed to match.** As specified — every filter value through `sqlLiteral` — a filter on
  any non-string column renders `WHERE "qty" > '5'`, which Athena rejects: Trino does not
  coerce varchar to bigint. It is a *query-time* error, so nothing offline catches it, and it
  stays invisible on CSV-derived tables (the Table Builder makes those all-string) until the
  first Parquet table. The repo's own Trino renderer already emits numeric values bare for
  this reason (`dqcommon/sql.py`). A `'number'` value carries no injection surface: the
  renderer admits only a bounded charset that `Number.isFinite` then accepts, and refuses
  anything else rather than falling back to quoting — falling back would restore the very
  type error the kind exists to prevent. Everything else still goes through `sqlLiteral`.
- **The one-builder sweep (FR-002 AC6) is scoped to `features/data-explorer/`, not the repo.**
  A literal repo-wide sweep is not achievable and never was: `useTableActions.tsx`,
  `useRunDdl.ts` and `CreateViewDialog.tsx` build real DDL for the Query workspace, and
  `query.constants.ts`'s `DEFAULT_SQL` is `SELECT 1;`. A sweep exempting three legitimate
  builders would prove nothing about the fourth. SPEC-165's precedent is one-builder within
  the package that owns the concept, which is what shipped.
- **`renderExplorationSql` rejects by throwing** (`ExplorationRenderError`). The interface
  contract returns `string`, so there is no result type to carry a refusal, and every case is
  a caller bug the panels refuse before reaching here.
- **Two modules beyond the File & Folder sketch**: `exploration.ts` (the model constructors,
  so "empty" has one definition) and `explorationTabs.ts` (the persistence half of the tab
  state, mirroring `features/query/queryTabs.ts`, which is the precedent the whole model
  follows).

---

## Functional Requirements

### FR-001: The exploration model

#### Description:

An exploration is a **source** plus a **query description** plus **presentation state**. The
first two determine the SQL; the third never does. `ExplorationSource` is a discriminated union
from the outset so that SPEC-183 adds a UI, not a model change.

#### Acceptance Criteria:

- [ ] `ExplorationSource` has exactly two arms, `table` and `sql`, discriminated on `kind`.
- [ ] `Exploration` composes `source`, `query` and `presentation` as three separate fields —
      never a flattened bag, so the renderer's parameter list can exclude one of them.
- [ ] A `table` source carries the space id, database and table; it does **not** carry the
      bucket or the S3 location, which are the file browser's concern.
- [ ] Constructing an exploration from a `table` source yields an empty query description: no
      filters, no expression, no ordering, no grouping.

### FR-002: `renderExplorationSql` is the only SQL builder

#### Description:

One pure function renders an exploration's SQL. It takes the source and the query description
**and nothing else** — the central rule of the feature is enforced by the signature rather than
by discipline, because a function that cannot reach presentation state cannot be made to depend
on it by a later edit.

The two source arms differ only in what goes in the `FROM`:

- `table` → `FROM "db"."table"`
- `sql` → `FROM (<body>) AS <alias>`

Filters, the expression, ordering and grouping compose identically over either arm.

#### Acceptance Criteria:

- [ ] `renderExplorationSql(source, query)` takes exactly two parameters and its type signature
      admits no presentation value.
- [ ] A test constructs two explorations differing **only** in presentation and asserts the
      rendered SQL is byte-identical.
- [ ] Both source arms render, and a test asserts the composed clauses are identical between
      them for the same query description.
- [ ] The projection is always `SELECT *` when grouping is absent — column visibility never
      narrows it (see FR-003).
- [ ] With grouping present, the projection is the grouping columns followed by the
      aggregates, and an `ORDER BY` referencing a non-grouped, non-aggregated column is
      rejected before rendering rather than sent to Athena.
- [ ] An AST-style sweep fails if any module outside this one builds a `SELECT`, `FROM`,
      `WHERE`, `ORDER BY` or `GROUP BY` fragment — following SPEC-165's one-destination-builder
      precedent, exempting docstrings and this module's own declaration by node identity.
- [ ] The rendered SQL carries no trailing semicolon.

### FR-003: `SELECT *` always, and the rejected optimization is recorded

#### Description:

The renderer never narrows the projection to the visible columns, even though on Parquet that
would cut bytes scanned substantially.

Narrowing would make un-hiding a column a billed, several-second re-run, and would make cost
depend on a gesture users read as cosmetic. Predictable cost wins.

#### Acceptance Criteria:

- [ ] Hiding, reordering, pinning or resizing a column produces no new execution — asserted by
      counting `StartQueryExecution` calls across a presentation change.
- [ ] The decision and its rejected alternative are recorded in the delivery doc, so a future
      reader finds the reasoning rather than re-deriving it from an apparent inefficiency.

### FR-004: `sqlLiteral` and `sqlIdentifier`

#### Description:

Two escapers, in `lib/` because they are language rules and not feature domain.

`sqlLiteral(value)` renders a Trino/DML string literal by **doubling** embedded single quotes.
It is not the Hive/DDL escaper, which backslash-escapes; the repo already records these as "two
escapers, never confused" for the Python side, and this is the TypeScript half of that pair.

`sqlIdentifier(name)` renders a double-quoted identifier with embedded double quotes doubled.
Column names must go through it and must **not** be validated against `CATALOG_IDENTIFIER_RE` —
column names are not catalog-safe, a fact SPEC-144 already had to record for a different reason.

#### Acceptance Criteria:

- [ ] `sqlLiteral("O'Brien")` returns `'O''Brien'` — quoted, doubled, and not backslashed.
- [ ] `sqlLiteral` is applied to every filter value the renderer emits; a test filters on a
      value containing a single quote and asserts the rendered SQL is well-formed.
- [ ] `sqlIdentifier('a"b')` returns `"a""b"`.
- [ ] Database and table names go through `sqlIdentifier` as well — `catalogIdentifier`
      validates a name, it does not quote one, and the two jobs are not interchangeable.
- [ ] A test asserts `sqlLiteral` and the Python `ddl.literal` rule produce **different** output
      for a backslash-containing value, pinning that the two escapers were not conflated.
- [ ] Neither escaper is exported from a feature; both live in `lib/` with the distinction
      documented at the definition.

### FR-005: The raw expression passes through verbatim

#### Description:

The exploration's `expression` field is a user-authored `WHERE` fragment. It is composed into
the rendered SQL **unescaped**, exactly as Monaco's buffer is, because it is the user's own SQL
and not a value the app is quoting on their behalf.

The distinction is the one thing a reader of this feature must not get backwards: the expression
is authored *as SQL*; a filter value arrives *from data* and is quoted.

#### Acceptance Criteria:

- [ ] `expression` is concatenated into the `WHERE` without passing through `sqlLiteral`.
- [ ] When both an expression and column filters are present, they are combined with `AND` and
      each side is parenthesized, so an expression containing `OR` cannot capture a filter.
- [ ] An empty or whitespace-only expression contributes no clause and no stray `AND`.
- [ ] A test documents the asymmetry: the same string produces different SQL as an expression
      than as a filter value.

### FR-006: One execution per distinct rendered SQL

#### Description:

The rendered SQL is the cache key. Two explorations that render identically share one Athena
execution; changing a filter and changing it back is a cache hit, not a second bill. Paging
within an execution uses `GetQueryResults`' `NextToken` and scans no extra bytes.

#### Acceptance Criteria:

- [ ] The TanStack key derives from the rendered SQL, under an `explorerKeys` namespace rooted
      at `['data-explorer']`.
- [ ] Applying a sort, then removing it, issues exactly one `StartQueryExecution` — asserted by
      call count.
- [ ] Paging forward and back issues no `StartQueryExecution` at all.
- [ ] A failed execution is not cached as a success; re-applying the same description retries.
- [ ] The results pager is SPEC-176's `useQueryResults`, unmodified — this spec adds no second
      pager.

### FR-007: Cost accounting

#### Description:

Every execution reports what it scanned, and a tab accumulates the total across its lifetime.
Athena offers no pre-flight estimate, so this is the only cost signal the feature can give.

#### Acceptance Criteria:

- [ ] Each execution's `dataScannedBytes` and `engineExecutionTimeMillis` are exposed from the
      exploration hook, sourced from `getQueryStatus` (SPEC-176's `athena.service`).
- [ ] A tab exposes a cumulative bytes-scanned total across every execution it has run.
- [ ] A cache hit adds **nothing** to the cumulative total — it ran no query.
- [ ] An execution that fails before reporting statistics contributes zero, not `NaN`.
- [ ] Rendering goes through `formatBytes` from `lib/format.ts` (moved there by SPEC-176).

### FR-008: Exploration tab state

#### Description:

`useExplorationTabs` mirrors the Query workspace's tab model: an ordered list, one active tab, a
soft cap enforced by refusal, and `sessionStorage` persistence keyed by username. Each tab owns
one exploration.

#### Acceptance Criteria:

- [ ] `openTab` returns `null` at the cap rather than throwing or silently dropping, so the
      caller can raise the cap dialog (SPEC-179 renders it).
- [ ] State persists to `sessionStorage` under a prefix + username key and survives a reload.
- [ ] A malformed or wrong-version stored document is discarded and replaced with a fresh
      state, never partially applied.
- [ ] Closing the last tab leaves a valid state — `activeTabId` always references an existing
      tab, matching `QueryTabsState`'s invariant.
- [ ] No component is delivered in this spec; the hook is tested directly.

---

## Data Model

```ts
// apps/portal/src/features/data-explorer/dataExplorer.types.ts

export type ExplorationSource =
  | {kind: 'table'; spaceId: string; database: string; table: string}
  | {kind: 'sql'; body: string; label: string};

export type FilterOperator = '=' | '<>' | '>' | '>=' | '<' | '<=' | 'isNull' | 'isNotNull';

export type ColumnFilter = {
  column: string;
  operator: FilterOperator;
  /** Absent for `isNull` / `isNotNull`; a raw cell value otherwise, quoted at render time. */
  value?: string;
};

export type SortEntry = {
  column: string;
  direction: 'asc' | 'desc';
  /** 0-based; lower sorts first. */
  priority: number;
};

export type AggregateFunction = 'COUNT' | 'SUM' | 'AVG' | 'MIN' | 'MAX';

export type GroupingAggregate = {
  fn: AggregateFunction;
  /** `'*'` is legal for COUNT alone. */
  column: string | '*';
};

export type Grouping = {
  columns: string[];
  aggregates: GroupingAggregate[];
};

/** Everything that renders SQL. Nothing else may. */
export type ExplorationQuery = {
  filters: ColumnFilter[];
  /** User-authored WHERE fragment, passed through verbatim (FR-005). */
  expression: string | null;
  ordering: SortEntry[];
  grouping: Grouping | null;
};

/** Everything that renders nothing. Extended by SPEC-180 and SPEC-184. */
export type ExplorationPresentation = {
  hiddenColumns: string[];
  columnOrder: string[];
  pinnedColumns: string[];
  columnWidths: Record<string, number>;
};

export type Exploration = {
  id: string;
  source: ExplorationSource;
  query: ExplorationQuery;
  presentation: ExplorationPresentation;
};

export type ExecutionCost = {
  bytesScanned: number;
  engineMillis: number;
};
```

---

## API / Interface Contract

```ts
// The one builder. Note the parameter list: presentation is not reachable.
export function renderExplorationSql(source: ExplorationSource, query: ExplorationQuery): string;

// lib/sql.ts — the escapers
/** Trino/DML string literal: doubles embedded single quotes. NOT the Hive/DDL backslash rule. */
export function sqlLiteral(value: string): string;
/** Double-quoted identifier with embedded double quotes doubled. */
export function sqlIdentifier(name: string): string;

// The execution hook
export function useExploration(exploration: Exploration | null): {
  sql: string | null;
  queryExecutionId: string | null;
  state: QueryState | null;
  cost: ExecutionCost | null;
  isPending: boolean;
  error: unknown;
};
```

---

## File & Folder Structure

```
apps/portal/src/
├── features/data-explorer/          # NEW
│   ├── index.ts
│   ├── explorerKeys.ts
│   ├── dataExplorer.types.ts
│   ├── dataExplorer.constants.ts
│   ├── renderExplorationSql.ts
│   ├── renderExplorationSql.test.ts
│   ├── useExploration.ts
│   ├── useExploration.test.ts
│   ├── useExplorationTabs.ts
│   ├── useExplorationTabs.test.ts
│   └── sqlBuilderSweep.test.ts      # the one-builder AST sweep
└── lib/
    ├── sql.ts                       # NEW — sqlLiteral, sqlIdentifier
    └── sql.test.ts
```

---

## Implementation Phases

### Phase 1: Escapers and types

- `lib/sql.ts` with both escapers and the DML/DDL distinction documented and tested.
- The exploration types, including the source union with both arms.

### Phase 2: The renderer

- `renderExplorationSql` over both source arms and all four query dimensions.
- The presentation-invariance test and the one-builder AST sweep.

### Phase 3: Execution and cost

- `useExploration` over SPEC-176's Athena layer, keyed by rendered SQL.
- Cost accounting, including the cache-hit-adds-nothing case.

### Phase 4: Tab state

- `useExplorationTabs` with the cap, persistence and the malformed-document path.
