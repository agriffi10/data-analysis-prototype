# Completed Spec — SPEC-238: A Column Filter Can Match Part of a Value, a List of Values, or an Empty Cell

## What was completed?

- **Eight filter operators** in the column menu and *Order and filter*: `contains`, `notContains`,
  `startsWith`, `endsWith`, `in`, `notIn`, `isEmpty`, `isNotEmpty`. The text operators render
  `lower(col) LIKE lower(pattern) ESCAPE '\'`; the list operators render `IN` / `NOT IN` over a
  de-duplicated, code-unit-sorted list; the empty tests render their own parentheses so an `AND`
  join cannot capture the `OR`.
- **One descriptor table**, `FILTER_OPERATOR_SPECS` in `dataExplorer.constants.ts`. The offer order,
  the labels, which field an operator reads, which column types offer it and whether the column's
  `valueKind` decides how its value is rendered all derive from it — as does the stored-document
  gate, which used to hold its own `Set<string>`. The renderer's `RENDER_FILTER` is a second
  `Record` over the whole union. Both make a missing operator a compile error.
- **New pure edits** in `explorationQueryOps.ts`: `isTextType`, `operatorsFor`, `isFilterOperator`
  (`Object.hasOwn`, never `in`), `operatorTakesValues`, `operatorUsesValueKind`, and
  `parseFilterValues` — the one reading of the multi-line field, shared by both surfaces so they
  cannot refuse different lists. `setFilter` now writes only the field the operator reads.
- **A length refusal before anything starts:** `ATHENA_QUERY_STRING_MAX` and
  `exceedsAthenaQueryLimit` (UTF-8 bytes), with `ExplorationStatementTooLong` worded in
  `lib/errorMessages.ts`. `useExploration` returns `sql: null` for it, exactly as for a refused
  render, so *Generated SQL* and *Save as query* both behave as they already did.
- **Colors** gains `isEmpty` / `isNotEmpty` — the only operator that reaches a NULL cell — with
  `compile()` rewritten as an exhaustive `Record<ColourOperator, …>` and the value field removed
  from the accessible tree for a valueless operator.
- **A shared `FilterValuesField`**, the one-value-per-line textarea both list surfaces use.
- The *Filter and sort* guide names the new operators and explains `(empty)` versus `NULL`.

### Deliberate deviations

- **The descriptor table lives in `dataExplorer.constants.ts`, not `explorationQueryOps.ts`** as the
  spec's File & Folder Structure implies. The renderer must read the same `valueKindApplies` flag
  the value inputs read, and `explorationQueryOps` already imports the renderer — so the table had
  to sit where both can reach it. The exports the spec names (`FILTER_OPERATORS`,
  `FILTER_OPERATOR_LABELS`, `isTextType`, `operatorsFor`) are still `explorationQueryOps`'s.
- **`FilterValueDialog` takes `existing: ColumnFilter | null`** rather than the spec's separate
  `mode` prop: the mode is a function of the operator it already receives, and a second input that
  can disagree with the first is a second thing to keep in step.
- **The guide's step 5 was reworded**, which the spec does not ask for. It taught the expression bar
  as the workaround for `LIKE '%sample%'` and `IN ('NY','NJ')` — the two things this spec puts in
  the menus — so it would have shipped as stale advice. It now points at conditions the menus still
  cannot express.
- **`ruleRefusal` no longer applies the pattern-length check to a valueless colour operator.** Found
  while re-deriving the operator population: a rule switched to *is empty* while carrying a long
  value was refused for the length of a string the evaluator never reads, and vanished with nothing
  on screen to explain it.
- **In *Order and filter*, a list the user typed survives an operator round trip.** The staged raw
  text outlives the staged query's `values`, so `is one of` → `equals` → `is one of` brings the
  typed lines back rather than an empty field. The spec's sentence describes the other surface,
  where a switch does clear. The parse at Apply is authoritative either way, and restoring what
  someone typed thirty seconds ago is the kinder of the two readings.

## What changed from earlier specs?

- `ColumnQueryActions.filter` (SPEC-181) takes `{value} | {values}` instead of `value?: string`, and
  gains `operatorsOf(column)`. The column menu no longer lists any operator by hand.
- `OPERATOR_SQL` (SPEC-178) is gone, replaced by `RENDER_FILTER`. `ExplorationRenderError` gains
  three cases: an empty text value, an absent or over-cap list, and a non-numeric list entry.
- `compile()` and `ruleRefusal` (SPEC-184) changed as above. `COLOUR_OPERATORS` and
  `COLOUR_OPERATOR_LABELS` are now derived from `COLOUR_OPERATOR_SPECS`.
- `canonical()` (SPEC-181) compares `values` de-duplicated and sorted, and ignores whichever of
  `value` / `values` the operator does not read — so a stray field on an older document is not a
  different query.

## Verification

Local, by exit code — a runner can print a passing summary and still exit non-zero: Prettier
`format:check`, ESLint, `tsc -b`, `npm run build`, `check:bundle`, the portal suite, `pytest
lambdas/` (over its 85% coverage floor), `mypy`, `validate_docs.py` and its corpus, the feature-flag
and app-managed-path validators and their corpora, the API-contract regeneration diff, and
`pre_push_test.py`. Two fresh-context diff reviews, in different frames, before the push.

The two guards added for the *Order and filter* pre-fill and the list-mode focus were each
**mutation-tested**: removing the mount-time seeding, and pointing the dialog's autofocus ref at
the single-value input, each reddened exactly one test, and the suite was green either side of
the pair.

Deferred to a signed-in session after deploy: the live check in
[`docs/testing/e2e.md` §4.5](../testing/e2e.md), rows 16–20. It runs against the **committed**
`explorer150` fixture and its `explorer150_nulls` view rather than a new table — that fixture
already carries 2 empty `qty` cells and 9 `O'Brien` rows, and the view supplies the real NULLs
beside them, which is what makes "is empty finds them, is null does not" a comparison rather than
an assertion. jsdom cannot tell `''` from NULL in an Athena result, which is the whole subject.
It is **not** an `owed.md` row: every step runs from one signed-in session.
