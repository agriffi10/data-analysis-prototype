---
type: Spec
id: SPEC-034
title: "Query Engine Data Layer — Athena/Glue Services + Per-User History"
description: "Gives developers the query data layer with no UI: services to run, poll, page through, and cancel Athena queries, list the user's Glue database, tables and columns, and keep a private per-user history in S3."
spec_status: Completed
depends_on: [SPEC-011, SPEC-013, SPEC-015, SPEC-032, SPEC-033]
arc: analytics
arc_order: 3
---

**Dependency notes:** SPEC-011 (`getS3Client()` + scoped credentials), SPEC-013 (user-space prefix derivation), SPEC-015 (TanStack Query foundation, `ServiceResult`, presigned-URL pattern), SPEC-032 (workgroup, results bucket, IAM), SPEC-033 (per-user Glue database)
## Overview

This is the data-layer foundation of the query feature — the engine the SPEC-035 query workspace UI and the SPEC-036 history panel consume, with **no UI of its own** (mirroring how SPEC-015 laid the file-operations data foundation before the file UI specs). It adds a new `src/features/query/` feature folder with: service functions that run an Athena query (with a per-user results location), poll it to completion, fetch paginated results, and cancel it; Glue service functions that list the user's own database and its tables/columns for the schema browser; and a per-user **query history** store kept as a JSON file in the user's own S3 prefix — the only way to give each user a private history given the shared Athena workgroup exposes everyone's executions.

It introduces the AWS SDK v3 Athena and Glue clients (instantiated in `src/lib/`, never in components, per conventions) built on the same `fetchAuthSession()` scoped credentials the S3 client uses.

## Scope

### In Scope

- New SDK deps `@aws-sdk/client-athena` and `@aws-sdk/client-glue` (recorded in the CLAUDE.md tech-stack table); Athena/Glue clients in `src/lib/` built on `getS3Client()`-style scoped credentials
- `src/features/query/` feature folder: `query.service.ts`, `glue.service.ts`, `queryHistory.service.ts`, hooks, `queryKeys.ts`, `query.types.ts`, co-located tests
- **Run query:** `StartQueryExecution` against the SPEC-032 workgroup with `OutputLocation = s3://<user-space-bucket>/{username}/athenaresults/` (the user's own protected results folder; the isolation boundary is IAM, SPEC-032 FR-006)
- **Poll:** `GetQueryExecution` until terminal state, surfaced as a polling hook
- **Results:** `GetQueryResults` with pagination (`NextToken`), normalized into typed rows + columns; plus a presigned-URL CSV download of the raw result object from `athenaresults/` (reuse SPEC-015's presigner pattern)
- **Cancel:** `StopQueryExecution`
- **Schema browser data:** `glue.service.ts` lists the user's own database (named = username) and its tables + columns via Glue `GetTables`/`GetTable`
- **Per-user history:** read/append/update `{username}/athenaresults/query-history.json` in the user-space bucket; capped, newest-first; survives reloads. Writes are `PutObject` overwrites (allowed under the SPEC-032 `athenaresults/` policy, which denies only delete). The JSON preserves each query's SQL + stats **indefinitely** (Athena only retains execution metadata ~45 days, so the JSON is what keeps older queries re-openable). Read-only to the user — only the app's run flow writes it
- TanStack Query hooks with a `queryKeys` factory and invalidation, consistent with `fileBrowserKeys`

### Out of Scope

- All UI: the SQL editor, tabbed shell, schema-browser rendering, results table rendering (SPEC-035); the history panel UI (SPEC-036)
- Saving queries as Glue/Athena **named queries** (history is app-side JSON, not Athena saved queries)
- Surfacing raw workgroup-wide history (`ListQueryExecutions`) to the user — it leaks other users' queries and isn't granted; history is exclusively the per-user JSON store
- Any IAM / infra change (all granted in SPEC-032)
- Query result charting/visualization (future)
- Auto-refreshing schema via crawlers (users define tables via DDL — SPEC-035 runs the DDL through the same `runQuery` path)

---

## Functional Requirements

### FR-001: Athena & Glue Clients

#### Description:

Scoped-credential clients for Athena and Glue, instantiated in `src/lib/`, reusing the SPEC-011 session-credential + refresh pattern.

#### Acceptance Criteria:

- [ ] `@aws-sdk/client-athena` and `@aws-sdk/client-glue` added to `apps/portal/package.json` and recorded in the CLAUDE.md tech-stack table
- [ ] `getAthenaClient(forceRefresh?)` and `getGlueClient(forceRefresh?)` in `src/lib/` return `ServiceResult<AthenaClient>` / `ServiceResult<GlueClient>`, built from `fetchAuthSession()` credentials exactly like `getS3Client()` (region from `VITE_AWS_REGION`); credentials-absent → descriptive error, never throw
- [ ] The expired-credentials → one transparent retry with `(true)` pattern (SPEC-011) is reused — factor the shared logic if clean, otherwise mirror it
- [ ] Unit tests cover credentials-absent and client construction for both

### FR-002: Run Query

#### Description:

Start an Athena query for the signed-in user, always writing results to the user's own results prefix.

#### Acceptance Criteria:

- [ ] `runQuery({ sql, database, username })` issues `StartQueryExecution` with `WorkGroup = VITE_ATHENA_WORKGROUP`, `QueryExecutionContext.Database = database` (the user's database, named = username), and `ResultConfiguration.OutputLocation = s3://${VITE_S3_USER_SPACE_BUCKET}/${username}/athenaresults/`; returns `ServiceResult<{ queryExecutionId: string }>`
- [ ] The function does **not** assume query type — the same path runs `SELECT` and DDL (`CREATE TABLE`, `DROP TABLE`, etc.), per the user-run-DDL decision
- [ ] The output location is always the caller's own `{username}/athenaresults/` prefix; a comment notes IAM (SPEC-032 FR-006) restricts writes to that prefix (and denies delete there), so this is defense-checked server-side
- [ ] No-credentials / start failure returns a `ServiceResult` error (never throws); unit tests cover the params (workgroup, database, per-user output location) and the error path

### FR-003: Poll Query Status

#### Description:

Track a running query to a terminal state.

#### Acceptance Criteria:

- [ ] `getQueryStatus(queryExecutionId)` issues `GetQueryExecution` and returns `ServiceResult<QueryStatus>` with `state` (`QUEUED|RUNNING|SUCCEEDED|FAILED|CANCELLED`), `stateChangeReason`, `dataScannedBytes`, `engineExecutionTimeMillis`, and (on success) the result `outputLocation`
- [ ] A `useQueryExecution(queryExecutionId | null)` hook polls via TanStack Query `refetchInterval` while non-terminal, stops polling at a terminal state, and is disabled when the id is null
- [ ] Polling interval and a max-poll-duration guard are defined as named constants with comments; a `FAILED` state surfaces `stateChangeReason` for the UI
- [ ] Unit tests cover the state mapping and the terminal-state stop condition

### FR-004: Fetch Results (Paginated)

#### Description:

Read a succeeded query's results into typed columns + rows, paginating large result sets.

#### Acceptance Criteria:

- [ ] `getQueryResults({ queryExecutionId, nextToken?, maxRows? })` issues `GetQueryResults` and returns `ServiceResult<QueryResultPage>` with `columns: QueryColumn[]` (name + type from `ResultSetMetadata`), `rows: string[][]`, and `nextToken?`
- [ ] The first page's header row (Athena returns column names as row 0 for `SELECT`) is handled correctly — column metadata comes from `ResultSetMetadata`, and the duplicate header data row is dropped, documented with a comment (this is a well-known Athena foot-gun)
- [ ] A `useQueryResults` hook on `useInfiniteQuery` exposes paginated fetching; the page size and the Prev/Next pager UX are specified by **SPEC-038** (20 rows/page). This FR provides the service + hook; SPEC-038 sets the page size and pager
- [ ] DDL/`CREATE TABLE` queries that return no result set yield an empty `rows`/`columns` result, not an error
- [ ] `getResultCsvUrl({ queryExecutionId, outputLocation })` returns a presigned `GetObject` URL (reuse SPEC-015 `getDownloadUrl`/presigner) for downloading the raw `.csv` result object from the user's `{username}/athenaresults/` prefix; default 15-min expiry capped to credential TTL
- [ ] Unit tests cover header-row handling, pagination token threading, the empty-result (DDL) case, and the presigned-URL params

### FR-005: Cancel Query

#### Acceptance Criteria:

- [ ] `stopQuery(queryExecutionId)` issues `StopQueryExecution`, returns `ServiceResult<void>`, never throws
- [ ] A hook/mutation exposes cancel; cancelling transitions polling (FR-003) to `CANCELLED`
- [ ] Unit test covers the call + error path

### FR-006: Glue Schema Listing

#### Description:

List the signed-in user's own database and its tables/columns for the schema browser (SPEC-035). The app only ever requests the user's own derived database by name; LF + IAM (SPEC-032) deny anything else.

#### Acceptance Criteria:

- [ ] `getDatabase(databaseName)` (`glue:GetDatabase`) → `ServiceResult<{ name: string }>`; used to confirm the user's DB exists (drives the SPEC-033 backfill open question / empty-state)
- [ ] `listTables(databaseName)` (`glue:GetTables`, paginated) → `ServiceResult<GlueTableSummary[]>` (name, columns with name+type, table type, location). A 401/`AccessDenied`/`EntityNotFound` is mapped to a clean error/empty state, never thrown
- [ ] `useSchema(databaseName)` hook exposes the database + tables via TanStack Query, keyed by database, with an exported invalidation helper (so a DDL `CREATE TABLE` run through `runQuery` can refresh the schema)
- [ ] Unit tests cover the table/column normalization and the not-found/denied mapping

### FR-007: Per-User Query History Store

#### Description:

A private, per-user history of queries the user has run, stored as JSON alongside their results — the backend-free way to give each user a private history, since the shared workgroup's `ListQueryExecutions` exposes all users' executions (and is not even granted to the role — SPEC-032 FR-006). The JSON also preserves SQL + stats **indefinitely**, beyond Athena's ~45-day execution-metadata retention. Mirrors the architecture's `connections.json` pattern.

#### Acceptance Criteria:

- [ ] S3 key `{username}/athenaresults/query-history.json` (lives in the protected results folder); schema is the `QueryHistory` type below (`version: 1`). A comment notes that the SPEC-032 `athenaresults/` policy allows `PutObject` (overwrite) but denies delete — `get/append/update` only ever overwrite, never delete, so the file is writable but tamper-resistant
- [ ] `getQueryHistory(username)` reads + parses the file (missing file → empty `{ version: 1, entries: [] }`, not an error — same forgiving handling as `connections.json`)
- [ ] `appendQueryHistory(username, entry)` reads, prepends the new entry (newest-first), caps the list at `QUERY_HISTORY_MAX` (named constant, e.g. 100) dropping the oldest, and writes back via `putObject` (`application/json`) — an overwrite, not a delete
- [ ] `updateQueryHistoryEntry(username, queryExecutionId, patch)` updates an existing entry in place (e.g. to record terminal `status`, `dataScannedBytes`, `durationMs` after polling completes) and writes back
- [ ] **History is read-only to the user (v1, user decision):** there is no delete/clear function — entries are only added (`appendQueryHistory`) and status-updated (`updateQueryHistoryEntry`). SPEC-036 presents history as view/re-open/re-run only
- [ ] A `useQueryHistory(username)` hook exposes the list + append/update mutations via TanStack Query with invalidation; concurrent-write risk is documented (last-writer-wins on a single user's own file is acceptable — a comment notes it)
- [ ] The history entry stores the SQL text, database, `queryExecutionId`, `submittedAt`, and (once known) `status` + stats — enough for SPEC-036 to list, re-open, and re-run without re-reading from Athena
- [ ] Unit tests cover missing-file empty state, append + cap, and in-place update

---

## Data Model

```ts
// src/features/query/query.types.ts

export type QueryState = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';

export type QueryStatus = {
  queryExecutionId: string;
  state: QueryState;
  stateChangeReason?: string;
  dataScannedBytes?: number;
  engineExecutionTimeMillis?: number;
  outputLocation?: string;       // s3://.../{username}/<id>.csv, present on SUCCEEDED
};

export type QueryColumn = { name: string; type: string };

export type QueryResultPage = {
  columns: QueryColumn[];
  rows: string[][];              // each row aligned to columns; header row already stripped
  nextToken?: string;
};

export type GlueColumn = { name: string; type: string };
export type GlueTableSummary = {
  name: string;
  columns: GlueColumn[];
  tableType?: string;            // e.g. EXTERNAL_TABLE
  location?: string;             // s3 location backing the table
};

export type QueryHistoryEntry = {
  queryExecutionId: string;
  sql: string;
  database: string;
  submittedAt: string;           // ISO
  status?: QueryState;           // filled in once terminal
  dataScannedBytes?: number;
  durationMs?: number;
};

export type QueryHistory = {
  version: 1;
  entries: QueryHistoryEntry[];  // newest-first, capped at QUERY_HISTORY_MAX
};
```

## API / Interface Contract

```ts
// src/features/query/query.service.ts
runQuery(p: { sql: string; database: string; username: string }): Promise<ServiceResult<{ queryExecutionId: string }>>;
getQueryStatus(queryExecutionId: string): Promise<ServiceResult<QueryStatus>>;
getQueryResults(p: { queryExecutionId: string; nextToken?: string; maxRows?: number }): Promise<ServiceResult<QueryResultPage>>;
getResultCsvUrl(p: { queryExecutionId: string; outputLocation: string }): Promise<ServiceResult<{ url: string; expiresAt: string }>>;
stopQuery(queryExecutionId: string): Promise<ServiceResult<void>>;

// src/features/query/glue.service.ts
getDatabase(databaseName: string): Promise<ServiceResult<{ name: string }>>;
listTables(databaseName: string): Promise<ServiceResult<GlueTableSummary[]>>;

// src/features/query/queryHistory.service.ts
getQueryHistory(username: string): Promise<ServiceResult<QueryHistory>>;
appendQueryHistory(username: string, entry: QueryHistoryEntry): Promise<ServiceResult<QueryHistory>>;
updateQueryHistoryEntry(username: string, id: string, patch: Partial<QueryHistoryEntry>): Promise<ServiceResult<QueryHistory>>;
// History is read-only to the user (SPEC-036): no delete/clear functions in v1.

// src/features/query/queryKeys.ts
export const queryKeys = {
  all: ['query'] as const,
  schema: (db: string) => [...queryKeys.all, 'schema', db] as const,
  execution: (id: string) => [...queryKeys.all, 'execution', id] as const,
  results: (id: string) => [...queryKeys.all, 'results', id] as const,
  history: (username: string) => [...queryKeys.all, 'history', username] as const,
};
```

## Environment Variables

Consumes `VITE_ATHENA_WORKGROUP` (SPEC-032 FR-008). Results + history live in the user-space bucket, so the location is derived from `VITE_S3_USER_SPACE_BUCKET` + `{username}/athenaresults/` — **no results-bucket var**. Reuses `VITE_AWS_REGION`. No new vars.

## File & Folder Structure

```
apps/portal/src/
├── lib/
│   ├── athenaClient.ts            ← NEW: getAthenaClient(forceRefresh?)
│   ├── athenaClient.test.ts
│   ├── glueClient.ts              ← NEW: getGlueClient(forceRefresh?)
│   └── glueClient.test.ts
└── features/query/
    ├── index.ts                   ← barrel (services/hooks/types for SPEC-035/036)
    ├── query.service.ts           ← run / status / results / csv-url / stop
    ├── query.service.test.ts
    ├── glue.service.ts            ← database + tables
    ├── glue.service.test.ts
    ├── queryHistory.service.ts    ← per-user JSON history
    ├── queryHistory.service.test.ts
    ├── useQueryExecution.ts       ← run + poll
    ├── useQueryResults.ts         ← paginated results
    ├── useSchema.ts               ← database + tables
    ├── useQueryHistory.ts         ← history list + mutations
    ├── queryKeys.ts
    ├── query.constants.ts         ← poll interval, max poll, QUERY_HISTORY_MAX, default maxRows
    └── query.types.ts
```

## Implementation Phases

### Phase 1: Clients + run/poll/cancel

- SDK deps + `getAthenaClient`/`getGlueClient` (FR-001)
- `runQuery`, `getQueryStatus`, `stopQuery` + `useQueryExecution` (FR-002, FR-003, FR-005)

#### Checkpoint

`npm run test` + `npm run lint` pass. In a dev console wired to a signed-in session, `runQuery({ sql: 'SELECT 1', database: username, username })` returns an id; `getQueryStatus` polls to `SUCCEEDED`; a long query can be `stopQuery`'d to `CANCELLED`. Results write to `s3://<user-space-bucket>/<username>/athenaresults/`. A `runQuery` pointed at another user's database / output prefix is denied (IAM Glue ARN scoping / S3) and surfaces a clean error.

### Phase 2: Results, schema, history

- `getQueryResults` + CSV URL + `useQueryResults` (FR-004)
- `glue.service` + `useSchema` (FR-006)
- `queryHistory.service` + `useQueryHistory` (FR-007)

#### Checkpoint

`npm run test` + `npm run lint` pass with the new unit tests. Dev console: a `SELECT` returns typed columns + rows with the header-row stripped and pagination working; a `CREATE TABLE` DDL runs and `useSchema` then shows the new table; `appendQueryHistory` writes `{username}/athenaresults/query-history.json` and `getQueryHistory` reads it back (and returns empty, not error, when the file is absent).

## Open Questions

- [x] **Resolved (2026-06-17):** **append-at-submit** — `appendQueryHistory` is called when the query is submitted (so an interrupted/closed tab still records the attempt), and `updateQueryHistoryEntry` fills in the terminal `status` + stats once polling completes.
- [x] **Resolved (2026-06-17):** v1 keeps `rows: string[][]` (Athena returns all cells as strings); the UI renders strings. Per-column typed coercion is deferred. The column `type` is still surfaced for display (type pill) per SPEC-035.
- [x] **Resolved (2026-06-17):** **extract** the SPEC-011 "expired creds → one retry" logic into a shared `withCredentialRetry` helper in `src/lib/`, used by the S3/Athena/Glue clients; add it to `apps/portal/info/component-inventory/INDEX.md`.
- [x] **Resolved:** per-user history is an **app-side JSON file** at `{username}/athenaresults/query-history.json` (forced by the shared-workgroup decision; `ListQueryExecutions` is workgroup-scoped, leaks all users, and isn't granted) — not Athena named/saved queries.
- [x] **Resolved (2026-06-17):** results + history live in `{username}/athenaresults/` in the **user-space bucket** (delete-denied, UI-locked), set by the client per query; IAM (SPEC-032) is the enforcement boundary. No dedicated results bucket.
