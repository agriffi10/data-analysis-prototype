# Completed Spec — SPEC-034: Query Engine Data Layer

## What was completed?

The data-layer foundation for the in-app Athena query workspace — no UI (SPEC-035/036
build that). New `src/features/query/` feature plus shared `src/lib/` clients/helpers.
Full public surface is in `apps/portal/info/component-inventory/INDEX.md` (Query feature + Foundations);
names only below.

- **Clients (FR-001):** `getAthenaClient`/`getGlueClient` (`lib/athenaClient.ts`,
  `lib/glueClient.ts`), built on `getSessionCredentials` (`lib/awsCredentials.ts`).
  Deps `@aws-sdk/client-athena` + `@aws-sdk/client-glue` (`^3.1071.0`) added; CLAUDE.md
  tech-stack row updated.
- **Shared retry (FR-001 open-question):** extracted `withCredentialRetry(getClient, op)`
  + `isExpiryError` into `lib/credentialRetry.ts`, now used by the S3, Athena, and Glue
  services.
- **Query service (FR-002/003/004/005):** `runQuery` (type-agnostic; per-user
  `athenaresults/` output), `getQueryStatus`, `getQueryResults` (first-page header-row
  strip + `nextToken` pagination; DDL → empty page), `getResultCsvUrl` (reuses SPEC-015
  `getDownloadUrl`), `stopQuery`, `isTerminalState`.
- **Glue schema (FR-006):** `getDatabase`, `listTables` (paginated; missing DB → clean
  `NotFound`/empty, never thrown).
- **Per-user history (FR-007):** `queryHistory.service.ts` — `getQueryHistory`
  (missing/corrupt file → empty), `appendQueryHistory` (prepend + cap at
  `QUERY_HISTORY_MAX`), `updateQueryHistoryEntry` (in-place). PutObject-only (overwrite,
  never delete); read-only to the user (no delete/clear in v1).
- **Hooks/keys/types/constants:** `useQueryExecution` (poll w/ max-duration guard),
  `useQueryResults` (`useInfiniteQuery`), `useSchema` + `invalidateSchema`,
  `useQueryHistory`; `queryKeys`, `query.types.ts`, `query.constants.ts`, barrel.

No deviations from spec. No infra changes (all IAM granted in SPEC-032). No new env vars
(results/history derived from `VITE_S3_USER_SPACE_BUCKET`; consumes `VITE_ATHENA_WORKGROUP`).

## What changed from earlier specs?

- **`fileBrowser.service.ts`** — its local `EXPIRY_ERROR_CODES`/`isExpiryError` and
  `withAuthenticatedClient` body were replaced by the shared `lib/credentialRetry` helper.
  Behavior is unchanged (all file-browser tests still pass); no signature changes.
- **`getDownloadUrl`** is now also consumed by `query.service` (`getResultCsvUrl`),
  imported from the service file directly (not the barrel) to keep UI out of the data layer.

## Verification

`npm run lint`, `npm run test` (310 pass, incl. the file-browser suite confirming the
retry-helper refactor is behavior-preserving), and `tsc -b && vite build` all green. New
tests: `athenaClient`, `glueClient`, `credentialRetry`, `query.service` (run/status/
results/csv-url/stop), `glue.service`, `queryHistory.service`.

**Deferred (deploy-gated, no local AWS):** the spec's dev-console live checkpoints —
`runQuery('SELECT 1')` → poll → results, a `CREATE TABLE` DDL refreshing `useSchema`, the
history JSON round-trip, and the cross-user denial — exercise these services end-to-end and
are naturally verified once the SPEC-035 UI drives them against the live (already-deployed)
Athena/Glue stack.
