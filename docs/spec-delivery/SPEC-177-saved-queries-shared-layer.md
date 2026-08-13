# Completed Spec — SPEC-177: Extracting `features/saved-queries/` — the Shared `.sql` Store

## What was completed?

A new `features/saved-queries/` owns the `.sql` store — the service, the space memory, the pager,
the save flow and the two controls that surface it. Like SPEC-176 it ships **no user-visible
change** and nothing live is owed: no S3 call parameter moved, no help content changed, no wording
in `lib/errorMessages.ts` changed.

- **Twelve modules moved whole**, keeping their filenames and exported names:
  `savedQueries.service.ts`, `savedQuerySpace.ts`, `useSavedQueries.ts`, `useSavedQueriesPager.ts`,
  `useSavedQuerySpace.ts`, `useSaveQuery.ts`, `SaveQueryDialog.tsx`, `SavedQuerySpaceSelect.tsx` and
  their four co-located suites.
- **Two modules split**: `savedQueries.types.ts` (`SavedQuery`, `SavedQueryPage`, `SavedQueryLink`)
  and `savedQueries.constants.ts` (`SAVED_QUERIES_PAGE_SIZE`,
  `QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX`), with the query-only remainder left behind.
  `query.types.ts` now imports `SavedQueryLink` for `QueryTab.savedQuery` — the open direction.
- **`useSaveQuery` takes `{sql, link}`** instead of a `QueryTab` (FR-002).
- **`savedQueryKeys` is rooted at `['saved-queries']`**; `queryKeys` keeps only `all` and `history`.
- **The ESLint layering rule gained `features/saved-queries/`**, and its message was rewritten to
  name the lower layers it now governs.

## The consumer sweep found nothing, and that is a result rather than an assumption

FR-001 AC5 required the sweep be run rather than trusted, because SPEC-176 made exactly this claim,
shipped, and found six external files — including a `features/table-builder/` that had been reaching
into a leaf feature for two arcs.

It was run, over every moving module specifier and every moving type, constant and key name.
**Every importer of every moving module was inside `features/query/`.** Repo-wide, the only external
references to `features/query/` at all are `routes/QueryPage.tsx` (`QueryWorkspace`),
`routes/routes.test.tsx` (a `vi.mock` of `SqlEditor`) and `features/feature-flags/gatedSurfaces.test.tsx`
(`DatabaseNode` / `QueryToolbar` / `QueryWorkspace`) — none of which touches the store.

The difference from SPEC-176 is worth naming: the catalog layer had leaked because *other features*
wanted Glue and Athena. The `.sql` store had exactly one consumer because saving a query was, until
this arc, something only the Query workspace did.

## The generalized signature is the point, and one field of it was deliberately not narrowed

`useSaveQuery` read `activeTab: QueryTab` for two things: the SQL to write and the link identifying
what a re-save replaces. It now takes `payload: {sql, link?}` and `QueryWorkspace` passes
`{sql: activeTab.sql, link: activeTab.savedQuery}`. Nothing else about the hook changed — the
validation, the folder marker on the *chosen* space, the `Collision` round-trip that survives a
cancelled Replace, the inline failure that leaves the dialog open with the destination intact.

**`onSaved` keeps its second argument, against the spec's own Data Model.** The spec sketched
`(link: SavedQueryLink) => void`; it ships as `(query: SavedQuery, sql: string) => void`, because
`QueryWorkspace` clears its dirty marker with `rememberSavedSql(query.key, sql)` — against the bytes
that were **written**, not against whatever the buffer holds by the time the async write returns.
Narrowing it would have changed workspace behaviour, which FR-002 AC2 forbids. Recorded in the
spec's Scope section rather than left as a discrepancy between the spec and the diff.

## One constant moved and must never be renamed

`QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX` is `s3portal.query.savedQuerySpace.` — a live
`sessionStorage` key. Its `query.` segment describes where the module used to live, which is exactly
the sort of thing a move invites tidying, and tidying it silently discards every user's remembered
space on the deploy that ships it. The name and the string are both untouched and the docstring now
says why.

## One a11y test had to split rather than move

`saveQuery.a11y.test.tsx`'s fourth case drives the Replace confirm through `QueryDialogs` — a Query
workspace component that stays. Moving the file whole would have made the new feature's own suite the
FR-004 rule's first violation, which is the rule working. The three dialog passes moved with the
dialog; the confirm pass is now `features/query/queryDialogs.a11y.test.tsx`.

The same shape applied one level up: the `SaveQueryDialog` describe block inside
`features/query/queryUi.test.tsx` moved verbatim into `features/saved-queries/savedQueriesUi.test.tsx`.

## Verification

`npm run format:check`, `npm run lint`, `npm run build` and the full portal suite all green locally,
**by exit code**: vitest `0`, **2148 tests / 94 files**, and `npx vitest run --coverage` `0` at
**93.16 / 88.93 / 92.21 / 94.72** against the SPEC-150 floors of 91/86/89/93 — no floor lowered.
Both figures are identical to SPEC-176's; the file count is 92 → 94 from the two splits above.

**No test's assertions changed.** Verified by counting `it(`/`test(` call sites across every suite
on both sides: **1981 on `origin/main`, 1981 on the branch.** The moved blocks are the same blocks
under rewritten paths; `useSaveQuery.test.ts`'s `tab()` fixture helper became `saving()` returning a
payload, which is the fixture shape, not an assertion.

**The layering rule was verified by violation in four directions**, each mutation reverted:

| Direction | Written as | Required | Observed |
|---|---|---|---|
| `saved-queries` → `query` | `'../query/useQueryTabs'` | refuse | refused |
| `saved-queries` → `data-explorer` | `'../data-explorer/_probe'` | refuse | refused |
| `saved-queries` → `catalog` | `'../catalog/catalog.types'` | permit | permitted |
| `query` → `saved-queries` | `'../saved-queries/savedQueryKeys'` | permit | permitted |

The relative form is load-bearing: `no-restricted-imports` matches the literal import source, and a
sibling is reached as `'../query/…'`, which contains no `features/` segment. Reading the config
proves nothing — SPEC-176's first version resolved onto the right files and caught nothing.

**Nothing live is owed.** The spec makes no AWS call it did not already make, and every parameter is
unchanged.

**User-facing docs sweep: nothing to do, recorded explicitly.** No file under `features/help/`
changed, no wording in `lib/errorMessages.ts` changed, and no onboarding copy changed — there is no
shipped behaviour to document, which is FR-005's point.

## Notes for the next spec

- **`SaveQueryDialog`'s copy still says "the file this tab was opened from"** (`SaveQueryDialog.tsx`,
  the FR-004 sentence). It is correct for its only current caller and FR-005 forbade touching it
  here. SPEC-183 mounts this dialog from a surface with no tabs and will have to decide whether that
  sentence is still true — it is a wording decision, not a mechanical one.
- **`isLinkedSavedQuery` is now on the barrel**, which it was not on `features/query/`'s. It is the
  single predicate behind the dialog's promise, the host's `overwrite` and whether a Replace confirm
  is raised at all (SPEC-175 FR-004), so a second consumer must reach the same one.
- **`SavedQueriesPanel` stayed**, as scoped — it is the Query workspace's rail panel, with
  tab-opening affordances and a mobile home tab. The Data Explorer's load surface is SPEC-183's.
