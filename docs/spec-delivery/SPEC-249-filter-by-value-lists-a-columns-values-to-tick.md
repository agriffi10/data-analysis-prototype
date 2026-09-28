# Completed Spec — SPEC-249: Filter by Value Lists a Column's Values to Tick

## What was completed?

- **Filter by value…** in the Data Explorer: from **Options** (replacing *Filter by this value*,
  seeded with the cursor's cell) and first among the filters in a text or number column's header
  menu. `FilterByValueDialog` lists the column's values most common first with their row counts,
  under every other filter and the expression, and applies the ticked ones as **is one of** or
  **is not one of**. Ticking every value of a whole list clears the filter instead.
- **The listing** is `renderColumnValuesSql` (the renderer's own `renderFrom`/`renderWhere`, a
  `COUNT(*) OVER ()` total, `LIMIT 1000`), started by `useColumnValues` through a
  `ColumnValuesProvider` mounted around the whole workspace. The registry, its actions and the
  page reader `readValuesPages` are `columnValuesStore.ts`. A listing is cached under
  `explorerKeys.execution`, never observed, billed to the tab that asked through the ledger, and
  not stopped when the dialog closes. Every requester waits on the one `runQuery` call, kept in an
  in-flight map per query client, so an eviction mid-start, a second tab joining or a remount of the
  Explorer cannot strand a request or pay for a start twice.
- **`FilterValuePicker`** is the inline, connected picker the AND/OR builder embeds;
  `FilterValueList` is its presentational half. `columnValues.ts` holds which values can be ticked
  (`refusalOf`), when two values are the same (`sameValue`, by number on a numeric column) and the
  sentences.
- **A list can hold `''` and name NULL.** `FilterOperatorSpec.listsNull` (true for `in` only) and
  `ColumnFilter.includesNull`, read by `setFilter`, `canonical`, the renderer, the stored-document
  check and `FILTER_KEYS`. The typed field (`FilterValuesField`) gains **(empty)** and **NULL**
  boxes, read by `readListField` and pre-filled by `listFieldOf`, so the header's typed dialog and
  *Order and filter* round-trip any list the picker writes.
- Help: *Filter and sort* rewritten for the picker, the boxes and NULL; a new Query-section guide,
  *Filter by value* (`query-filter-by-value`), registered under `dataExplorer`.

### Deliberate deviations

- **The Query-section Help pointer was added mid-build** at Andrew's request, relayed by the
  supervisor; FR-006 records it.
- **The listing's error arm carries `tryAgain: (() => void) | null`**, and the spec was amended to
  match: a statement too long to run would fail the same way again, so it shows no *Try again*; and
  the first name, `retry`, is what the API contract guard reads as a transport retry policy.
- **A status read that fails ends the watch** as an error with *Try again*, which watches again
  (the plan review asked for the choice to be made).
- **A second tab asking for a listing that already settled is billed for it** at that moment, as an
  exploration shown in two tabs is (plan review).
- **The start was rebuilt after the diff review.** The first build waited on `fetchQuery`'s promise
  and did its bookkeeping in the query function; an eviction that cancelled the start and then a
  failed start left the dialog counting for ever, and a second tab that joined was never billed.
- **`UNFILTERABLE_VALUE` moved** from `ExplorationResultsRegion` to `columnValues.ts` and now says
  "This value…", because it labels a listed value, not the cursor's cell.

## What changed from earlier specs?

- **SPEC-238's list model**: `values` may hold `''`; `in` may carry `includesNull`; a list operator
  requires `values`, which may be empty only with `includesNull`. `parseFilterValues` no longer
  refuses an empty field — `readListField` does, counting the boxes. `filterValuesText` leaves `''`
  out. SPEC-238's rule that `notIn` excludes NULL rows is unchanged.
- **SPEC-181's filter-by-cell** action (`filterByCell`, `onFilterByCell`) is gone; the Options item
  opens the picker.
- **SPEC-241** (cancelled 2026-09-16) is superseded: this is that feature, approved on 2026-09-28.

## Verification

Formatter, both linters, both suites, mypy, `npm run build` and the doc validator green locally.
Mutation-tested the guards whose failure would be silent: `canonical` and `FILTER_KEYS` on
`includesNull`, the ledger reads and the post-FAILED eviction in the store, the held-first refusal,
the clear-all rule's truncation test and the aggregate exclusion; after the diff review, billing
every tab that asked, the id check before dropping a failed start, the still-running watch, a
joining tab's bookkeeping, the NULL-cell seed and Enter in the search field. The live check in
`docs/testing/e2e.md` ran on the deployed image on 2026-09-28 (`docs/testing/sessions.md`); two
parts of it were not run and are named there.
