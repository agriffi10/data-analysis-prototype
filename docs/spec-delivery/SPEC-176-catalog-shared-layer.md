# Completed Spec — SPEC-176: Extracting `features/catalog/` — the Shared Catalog & Execution Layer

## What was completed?

A new `features/catalog/` owns everything the Query workspace and the coming Data Explorer both
need to read the Glue catalog and run Athena queries. It ships **no user-visible change** — the
AWS-calling modules are byte-identical outside their import lines, verified by diffing each against
its pre-move self.

- **Eight modules moved whole**, keeping their exported names: `query.service.ts` →
  `athena.service.ts` (the one rename — `query.service` inside `catalog/` would misdescribe a module
  that is entirely Athena's API), `glue.service.ts`, `useSchema.ts`, `useQuerySpaces.ts`,
  `useQueryExecution.ts`, `useQueryResults.ts`, `useResultRowCount.ts`, `useColumnWidths.ts`.
- **Four modules split** along the FR-002 table: `catalog.types.ts` / `catalog.constants.ts` /
  `catalog.format.ts` / `catalogKeys.ts` in the new feature, the query-only remainder left behind.
  The display page-size constants stayed — `MAX_RESULTS_PAGE_SIZE` is a SPEC-087 workspace
  preference, not a property of Athena.
- **`catalogKeys` is rooted at `['catalog']`**, not `['query']`.
- **`formatBytes` → `lib/format.ts`**; **`queryKeys.connections` → `features/connections/connectionKeys`**,
  closing one of the two residual layering inversions SPEC-155 recorded.
- **The ESLint layering rule gained a sibling clause** forbidding `features/query/` ↔
  `features/data-explorer/`, with no test exemption.

## The scope claim was wrong, and being wrong strengthened the premise

The spec said only one file outside the feature was affected (`routes/QueryPage.tsx`, which imports
`QueryWorkspace` and is indeed untouched). **Six were.** `features/table-builder/useTableRefresh.ts`
took `invalidateSchema` and `GlueTableSummary`, `tableRefresh.types.ts` took `GlueTableSummary`,
three tests took `queryKeys.schema` / `queryKeys.connections`, and
`features/feature-flags/gatedSurfaces.test.tsx` carried a `vi.mock` of `../query/glue.service`.

All six are one-line repoints, and none of them widened the work. What they show is that
`features/query/` was already a shared layer in fact: the table builder had been reaching into a
leaf feature for the Glue reader and the schema key for two arcs. The correction is recorded in the
spec's Scope section rather than left as a discrepancy between the spec and the diff.

## `DatabaseSchema` had to move, and the rule is what found it

`useSchema.ts` moved carrying an import of `DatabaseSchema` from `sqlCompletions.ts` — which stays
in `features/query/`. That is FR-001's "no module under `features/catalog/` imports from
`features/query/`" violated on the first file, by a type nobody thought of as domain: it is
`{database: string; tables: GlueTableSummary[]}`, declared next to the completion provider that
consumes it rather than the hook that produces it.

It now lives in `catalog.types.ts`, and `sqlCompletions.ts` imports it. Producer, not consumer,
decides where a type lives when the producer is the lower layer.

## The rule read correctly and caught nothing

The clause was written first with the same shape as the SPEC-155 rule — `**/features/query/**` and
friends. It resolved onto the right files (confirmed with `eslint --print-config`) and **passed a
deliberate violation in both directions**.

`no-restricted-imports` matches the literal import **source string**, not a resolved path. The
existing rule works because `components/` and `lib/` sit *above* `features/` and must name it:
`'../features/query/queryKeys'`. One sibling feature reaches another as `'../query/queryKeys'`,
which contains no `features/` segment at all. The relative forms — `'../query'`, `'../query/**'`,
`'../../query'`, `'../../query/**'`, and the same four for `data-explorer` — are the load-bearing
ones; the `**/features/…` globs are kept for any path written the long way.

FR-006 required verification by violation rather than by reading the config, and that is the only
reason this shipped working. A config that resolves onto the right files is not a config that fires.

## Verification

`npm run format:check`, `npm run lint`, `npm run build` and the full portal suite all green locally,
**by exit code**: vitest `0`, **2148 tests / 92 files**, and `npm run test:coverage` `0` at
**93.16 / 88.93 / 92.21 / 94.72** against the SPEC-150 floors of 91/86/89/93 — no floor lowered.

The layering rule was verified by committing a violation in each direction plus one from a **test
file** (to prove the deliberate absence of a test exemption), observing all three fail, and
reverting.

- **No test's assertions changed** — the moved suites are the same blocks under rewritten paths.
  `queryServices.test.ts` and `queryPure.test.ts` straddled the split and were carved:
  `catalog/catalogServices.test.ts`, `catalog/catalogPure.test.ts`, `catalog/useSchema.test.tsx` and
  `catalog/queryExecutionHooks.test.ts` on one side, the query-only blocks left behind.
- **One test was added**, FR-004's: the same byte count through `formatBytes` and the file browser's
  `formatSize`, both reading `3.0 TB`.
- **Nothing live is owed.** The spec makes no AWS call it did not already make, and every parameter
  is unchanged.

**User-facing docs sweep: nothing to do, recorded explicitly.** No file under
`features/help/` changed, no wording in `lib/errorMessages.ts` changed, and no onboarding copy
changed — there is no shipped behaviour to document, which is FR-007's point.

## Notes for the next spec

- **`lib/format.ts` did not already hold `formatSize`**, as FR-004's rationale stated — it lives in
  `features/file-browser/fileBrowser.format.ts` and stays there. The destination was still right
  (both features need `formatBytes`, so neither may own it) and every acceptance criterion holds;
  only the justifying sentence was wrong. The shared-ceiling test therefore sits in
  `lib/utils.test.ts` and imports across the boundary under the rule's existing test exemption.
- **`useAllSchemas` is exported from the catalog barrel** — it was reachable only by deep import
  before, and the Data Explorer needs it.
- **SPEC-177's saved-query extraction is unblocked and untouched**, as scoped.
