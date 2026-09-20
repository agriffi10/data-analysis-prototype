# Spec: A Column Filter Can Match Part of a Value, a List of Values, or an Empty Cell

**ID:** SPEC-238
**Status:** Completed
**Last Updated:** 2026-09-20
**Depends On:** SPEC-178, SPEC-181, SPEC-184

## Overview

Four testers asked the Data Explorer's column menu for a way to find rows whose value contains some
text: "Filter: Contains Text", "LIKE %sample%", "LIKE and NOT LIKE". One asked for a filter that
keeps rows matching any of several values, such as two brand names at once. The same tester reported
that "is not null" does not work on their table while `<> ''` does, and another could not colour the
cells shown as "(empty)". Those two reports have one cause: a table built from CSV files stores a
blank field as an empty string, not as NULL, so the null tests never match it.

This spec adds eight filter operators to the column menu and to *Order and filter*: **contains**,
**does not contain**, **starts with**, **ends with**, **is one of**, **is not one of**, **is empty**
and **is not empty**. It adds **is empty** and **is not empty** to the Colors rules, and it refuses a
statement too long for Athena to run before one is started.

### What was checked, and how

Read from the code at `73c66eef`.

- **The operators are a closed union with one value.** `FilterOperator` in
  `features/data-explorer/dataExplorer.types.ts` has eight members (`=`, `<>`, `>`, `>=`, `<`, `<=`,
  `isNull`, `isNotNull`), and `ColumnFilter` carries one optional `value`. `setFilter` keeps one
  filter per column (`explorationQueryOps.ts`).
- **Four places list the operators.** The renderer's `OPERATOR_SQL` map (`renderExplorationSql.ts`),
  `FILTER_OPERATORS` and `FILTER_OPERATOR_LABELS` (`explorationQueryOps.ts`), which the column menu
  and *Order and filter*'s select both read, and a separate `FILTER_OPERATORS` set in
  `explorationTabs.ts` that decides whether a stored tab document restores. `canonical()` in
  `explorationQueryOps.ts` compares `value` to decide whether an apply changed anything.
- **Every value is escaped at render time.** A string goes through `sqlLiteral` (`lib/sql.ts`,
  quote doubling). A value for a numeric column is emitted bare only after `isBareNumeric` accepts
  it, and refused otherwise.
- **A blank CSV field is an empty string.** CSV tables are built all-string under OpenCSVSerde
  (`lambdas/table-builder-infer-schema/infer_schema.py` docstring, `cpcommon/ddl.py`
  `CSV_OPEN_SERDE`). The grid shows NULL as `NULL` and `''` as `(empty)` (`cellText.ts`,
  `CellValue.tsx`), so `IS NULL` and `IS NOT NULL` behave correctly and still surprise.
- **Colors cannot reach an empty cell by name.** `ColourOperator` already has `like`, `ilike` and
  `regex`. `compile()` in `formatting.ts` matches no NULL cell under any operator, and `=` compares
  literally, so typing `null` or `(empty)` as the value matches neither.
- **Vendor facts, read from the live docs on 2026-09-16.** Trino's `LIKE` is case-sensitive and
  takes `ESCAPE 'character'` (trino.io, Comparison functions). Athena's `StartQueryExecution`
  limits `QueryString` to a maximum length of 262,144 (Athena API reference). The API route passes
  `sql` to Athena with no length check (`lambdas/api/routes/athena.py`).

### The decisions, made while authoring

- **Contains, does not contain, starts with and ends with, ignoring case, with the typed text
  matched literally** (Andrew, 2026-09-16). Patterns with `%` and `_` stay in the filter expression,
  whose hint already says `LIKE` works there. Raw `LIKE` / `NOT LIKE` operators and case-sensitive
  variants were the rejected options.
- **Case is folded by Trino on both sides**: `lower(column) LIKE lower(pattern)`. Lowering the value
  in the browser would use JavaScript's case rules on one side and Trino's on the other, and the two
  disagree on some characters.
- **The escape character is the backslash.** Trino gives a backslash no meaning in a string literal
  (`lib/sql.ts`), so `'\'` is one character. The pattern is built by doubling every backslash, then
  prefixing `%` and `_` with one, then adding the wildcards the operator needs, and only then passing
  the whole pattern through `sqlLiteral`. `sqlLiteral` stays the last step, so a quote can never
  leave the literal.
- **Text and empty operators are offered only on text columns.** `LIKE` and `= ''` against a
  `bigint` or a `date` are type errors in Trino, not comparisons. A text column is one whose type,
  lowercased and trimmed, is `string`, `varchar`, `char`, or starts with `varchar(` or `char(`. Glue
  and Athena spell these differently, as `filterValueKind` already notes.
- **List operators are offered on text and numeric columns only.** `IN ('2026-01-01')` against a
  `date` is the same type error, since the model quotes every non-numeric value. Typed date,
  timestamp and boolean literals are a model change no tester asked for. A list uses the column's `valueKind` for each value, as the comparisons do.
- **A NULL cell matches none of the text or list operators, and is empty matches it.** So `does not contain 'x'` and `is not one of ('x')` exclude NULL rows.
  This is SQL's own behaviour and the app's existing rule, since `<>` excludes NULL rows today and a
  Colors rule matches no NULL cell. In a CSV table blank cells are `''`, which the negative forms do
  include. **Is empty** exists to find absent values, so it matches both NULL and `''`.
- **A list holds strings only.** `in` and `notIn` read `values: string[]`, which is exactly what
  one-per-line text can express: no NULL entry, no empty string and no line break (`\n` or `\r`). The
  stored-document check refuses a list holding any of the three, so an edit can always pre-fill it
  line for line. A list that should also keep NULL rows is written whole in the filter expression,
  as `"c" IN (…) OR "c" IS NULL` with no list filter on that column, because the expression and the
  column filters combine with `AND`.
- **A list is rendered in one canonical order**: strings sorted by UTF-16 code unit. Two
  lists holding the same values then render identical SQL, which is the execution cache key, and
  compare equal for the filter history.
- **A list holds at most `EXPLORER_FILTER_VALUES_MAX` = 1,000 values**, counted after duplicates
  collapse. It is an input bound, not the query's real limit. The real limit is Athena's statement
  length, which FR-005 measures directly, because 1,000 long values can exceed it where 1,000 short
  ones do not.
- **A statement over the limit is treated like one that could not render.** `useExploration.sql` is
  null for it, so *Generated SQL* shows its no-statement sentence and *Save as query* refuses with
  `NOTHING_TO_SAVE`. Saving a statement Athena will refuse would hand the user a broken file.
- **The length check counts UTF-8 bytes against 262,144.** The API reference does not say whether
  it counts characters or bytes. A string's UTF-8 byte count is never below its character count, so
  a statement the check admits is under the limit in either unit.

## Scope

### In Scope

- The model, the renderer and the pure edits for the eight operators (FR-001, FR-002, FR-003).
- The column menu, the value dialog and *Order and filter* (FR-004).
- A refusal for a rendered statement over Athena's length limit, before it starts (FR-005).
- Colors rules **is empty** and **is not empty** (FR-006).
- The stored-document checks in `explorationTabs.ts` for filters and for colour rules.
- The *Filter and sort* guide in `helpContent.ts`.

### Out of Scope

- **Reading blank CSV fields as NULL.** It would change what existing tables return, and nobody
  has checked OpenCSVSerde's support for it. The grid keeps showing `NULL` and `(empty)` as
  different things, because they are.
- **Relabelling `(empty)`.** The label is accurate. The guide explains it instead.
- **A filter-by-value list** of a column's distinct values. SPEC-241 would have built it, and was
  cancelled.
- **More than one filter on a column.** One filter per column stays. The expression bar covers
  anything else.
- **Case-sensitive or raw-pattern operators in the menu.** Those belong in the expression bar.
- **A length check in the Query workspace.** There the user writes the statement, and Athena's
  refusal is reported as it is today.
- **The cell action "Filter by this value"** stays an `=` filter.
- **A Help guide for Colors.** None exists today (`helpContent.ts` has no Colors guide), and this
  spec does not add one.

---

## Functional Requirements

### FR-001: Contains, does not contain, starts with and ends with

#### Description:

`FilterOperator` gains `contains`, `notContains`, `startsWith` and `endsWith`. The renderer builds a
pattern from the filter's `value`: every `\` becomes `\\`, then every `%` becomes `\%` and every `_`
becomes `\_`, then `%` is added before the value (contains, notContains, endsWith) and after it
(contains, notContains, startsWith). It renders `lower(<identifier>) LIKE lower(<sqlLiteral(pattern)>)
ESCAPE '\'`, with `NOT LIKE` for `notContains`. These operators always quote their value, whatever
the filter's `valueKind`. A missing or empty `value` is an `ExplorationRenderError`, since an empty
contains matches every non-NULL row and is never what the user meant.

#### Acceptance Criteria:

- [ ] `contains` on `name` with value `a%b_c\d` renders
  `lower("name") LIKE lower('%a\%b\_c\\d%') ESCAPE '\'`, asserted as the whole `WHERE` clause.
- [ ] `startsWith` with `O'Brien` renders `lower("name") LIKE lower('O''Brien%') ESCAPE '\'`, and
  `endsWith` with `x` renders `lower("name") LIKE lower('%x') ESCAPE '\'`.
- [ ] `notContains` with `' OR 1=1 --` renders `lower("name") NOT LIKE lower('%'' OR 1=1 --%') ESCAPE '\'`.
  The statement contains no single quote outside the literal.
- [ ] `contains` with `value: ''` and with no `value` each throw `ExplorationRenderError`.
- [ ] `contains` with `valueKind: 'number'` and value `5` renders the value quoted (`'%5%'`).
- [ ] A stored tab document carrying a `contains` filter restores with that filter in
  `query.filters`. One carrying `{operator: 'contains', value: 7}` is refused. That second half
  already holds for every operator today, and it guards against a regression.

### FR-002: Is one of and is not one of

#### Description:

`FilterOperator` gains `in` and `notIn`. They read `values: string[]` and ignore `value`.
`operatorTakesValue` stays true only for the six comparisons and the four text operators, and a new
`operatorTakesValues` is true for `in` and `notIn`. `setFilter` writes only the field the operator
reads, and *Order and filter* clears the other field when the operator moves between a single-value
and a list operator. Before rendering, the strings are de-duplicated and sorted by UTF-16 code unit. Each one goes through
`sqlLiteral`, or is emitted bare when `valueKind` is `'number'` and `isBareNumeric` accepts it.
`in` renders `"c" IN (<values>)`, and `notIn` renders `"c" NOT IN (<values>)`, which excludes NULL
rows.

An absent or empty `values`, more than `EXPLORER_FILTER_VALUES_MAX` entries, or a numeric-kind entry
that fails `isBareNumeric` is an `ExplorationRenderError`. The cap counts distinct entries.
`canonical()` compares `values` de-duplicated and in the same sorted form, and
ignores `value` for a list operator and `values` for any other, so two filters holding the same
values in different orders or with a stray field are the same query.

#### Acceptance Criteria:

- [ ] `in` on `brnd_name` with `['Abilify', 'Abacavir', 'Abilify']` renders
  `"brnd_name" IN ('Abacavir', 'Abilify')`.
- [ ] `notIn` on `c` with `['b', 'a']` renders `"c" NOT IN ('a', 'b')`.
- [ ] `in` with `valueKind: 'number'` and `['10', '2.5']` renders `"qty" IN (10, 2.5)`. With
  `['10', '0x1f']` it throws `ExplorationRenderError`.
- [ ] `in` with `values: []`, with no `values`, and with 1,001 distinct values each throw
  `ExplorationRenderError`. With exactly 1,000 it renders.
- [ ] `sameQuery` is true for two descriptions whose only difference is `['a','b']` against
  `['b','a','a']`, true when one of the two `in` filters also carries a stray `value: 'z'`, and false
  against `['a','c']`.
- [ ] A stored tab document carrying an `in` filter with `['a', 'b']` restores with those values. One whose `values`
  holds a number, a `null`, an empty string or a value containing `\n` or `\r`, or is a string rather
  than an array, is refused by the stored-document check.

### FR-003: Is empty and is not empty

#### Description:

`FilterOperator` gains `isEmpty` and `isNotEmpty`, which take no value. `isEmpty` renders
`("c" IS NULL OR "c" = '')` and `isNotEmpty` renders `("c" IS NOT NULL AND "c" <> '')`. The
parentheses are part of the rendering, so combining several filters with `AND` cannot capture the
`OR`. `operatorTakesValue` is false for both.

#### Acceptance Criteria:

- [ ] `isEmpty` on `last_name` alone renders `WHERE ("last_name" IS NULL OR "last_name" = '')`.
- [ ] The filters `[{column: 'a', operator: 'isEmpty'}, {column: 'b', operator: '=', value: 'x'}]`
  render `WHERE (("a" IS NULL OR "a" = '') AND "b" = 'x')`.
- [ ] `isNotEmpty` renders `("c" IS NOT NULL AND "c" <> '')`.
- [ ] `operatorTakesValue('isEmpty')` and `operatorTakesValue('isNotEmpty')` are false.

### FR-004: The column menu, the value dialog and Order and filter offer them by column type

#### Description:

`explorationQueryOps.ts` gains `isTextType(type)`, the text-column rule from *The decisions*, and
`operatorsFor(type)`. A numeric column is one where `filterValueKind(type)` is `'number'`. `operatorsFor` returns the operators a column of that type offers, in this order: the
six comparisons, then (text columns only) contains, does not contain, starts with, ends with, then
(text and numeric columns only) is one of, is not one of, then is null, is not null, then (text
columns only) is empty, is not empty.
The column menu and the *Order and filter* select both read `operatorsFor`, so neither lists
operators by hand. Labels come from `FILTER_OPERATOR_LABELS`: `contains`, `does not contain`,
`starts with`, `ends with`, `is one of`, `is not one of`, `is empty`, `is not empty`. Menu items keep
today's naming: an operator that opens a dialog is `Filter: <label>…`, and one that applies at once
is `Filter: <label>`.

- A text operator opens `FilterValueDialog` as today. Apply is refused with
  "Enter the text to match." when the value is empty.
- A list operator opens the dialog in list mode: a labelled multi-line field, one value per line.
  Lines are numbered as the field shows them, blank lines included. A line of length zero is
  ignored. On a text column every other line is a value, verbatim, spaces included. On a numeric
  column each line is trimmed, a line that is then empty is ignored, and the rest must pass
  `isBareNumeric`; otherwise Apply is refused with "Line <n> is not a number — this column holds
  numbers.". Duplicates collapse, keeping the first. Apply is refused with "Enter at least one
  value." when no line has a value, and with "Enter at most 1,000 values." when more than 1,000
  distinct values would be stored.
- List mode pre-fills from the column's existing `in` or `notIn` filter, one value per line in their
  stored order, including when the user moves from one of the two to the other. A single-value
  filter leaves list mode empty, and a list filter leaves the single-value field empty, as *Order
  and filter* clears the other field when the mode changes.
- Is empty and is not empty apply straight from the menu, as the null tests do.
- In *Order and filter*, choosing a list operator shows the multi-line field in place of the single
  value field. That dialog's Apply refuses, per column, every case the
  value dialog refuses: an empty text-operator value with "Enter the text to match.", and each list
  refusal above.

The *Filter and sort* guide's first step names the new operators. One added sentence says that
blank cells in a table built from CSV files are empty text shown as `(empty)`, which **is empty**
finds and **is null** does not.

#### Acceptance Criteria:

- [ ] On a `string` column the header menu's filter items are, in order: `Filter: equals…`,
  `Filter: does not equal…`, `Filter: greater than…`, `Filter: greater than or equal to…`,
  `Filter: less than…`, `Filter: less than or equal to…`, `Filter: contains…`,
  `Filter: does not contain…`, `Filter: starts with…`, `Filter: ends with…`, `Filter: is one of…`,
  `Filter: is not one of…`, `Filter: is null`, `Filter: is not null`, `Filter: is empty`,
  `Filter: is not empty`, then `Clear filter`. Asserted by accessible name in `filtering.test.tsx`.
- [ ] On a `bigint` column the menu offers no contains, does not contain, starts with, ends with,
  is empty or is not empty item, and does offer is one of.
- [ ] On a `date` column the menu offers the six comparisons and the two null tests, and no text,
  list or empty operator.
- [ ] `isTextType` is true for `string`, `varchar`, `VARCHAR(20)`, `char(3)` and `char`, and false
  for `bigint`, `date`, `decimal(10,2)` and `''`.
- [ ] Choosing contains, typing `abc` and applying produces exactly one execution, whose SQL
  contains `lower("name") LIKE lower('%abc%') ESCAPE '\'`.
- [ ] Choosing is one of on a numeric column and applying the lines `1`, `x`, `3` shows
  "Line 2 is not a number — this column holds numbers." and starts no execution.
- [ ] Applying the lines `NY`, a blank line, `NJ`, `NY` stores a filter whose `values` is
  `['NY', 'NJ']`.
- [ ] Editing a stored filter `in ['NY', 'NJ']` shows the lines `NY` and `NJ` in the field.
  Applying without a change stores values equal to the original under `sameQuery`, and pushes no
  history entry.
- [ ] In *Order and filter*, choosing contains on a column and pressing Apply without typing a
  value shows "Enter the text to match." on that column's row and starts no execution.
- [ ] Choosing is empty from the menu produces one execution without opening a dialog.
- [ ] In *Order and filter*, setting is one of on one column and contains on another, then Apply,
  produces exactly one execution carrying both.
- [ ] The guide's text names every new operator and carries the CSV blank-cell sentence. This is
  static copy, so the diff review checks it rather than a test.

### FR-005: A statement too long for Athena is refused before it starts

#### Description:

`renderExplorationSql.ts` exports `ATHENA_QUERY_STRING_MAX = 262_144` and
`exceedsAthenaQueryLimit(sql)`, which is true when `new TextEncoder().encode(sql).length` is greater
than the constant. `useExploration` asks it after rendering and before starting anything. When it is
true, no execution starts, `useExploration` returns `sql: null` as it does for a refused render, and
the exploration's error is a new `ExplorationStatementTooLong` error, which `lib/errorMessages.ts`
words as: "This query is too long to run. Use fewer or shorter filter values, or a shorter
expression." The previous rows stay on screen, as they do for a refused render today.

#### Acceptance Criteria:

- [ ] `exceedsAthenaQueryLimit` is false for a string of 262,144 ASCII characters, true for
  262,145, and true for 131,073 copies of `é` (262,146 bytes).
- [ ] An exploration whose rendered SQL exceeds the limit starts no execution (the start service
  mock is not called), shows the sentence above, and returns `sql: null`, so *Generated SQL* shows
  `NO_GENERATED_SQL`.
- [ ] The same exploration with the long filter removed starts one execution.

### FR-006: Colors rules can match an empty cell

#### Description:

`ColourOperator` gains `isEmpty` and `isNotEmpty`, labelled "is empty" and "is not empty". They take
no value: the rules dialog hides the value field for them, and a stored rule's `value` is ignored.
`isEmpty` matches a cell that is NULL or `''`, and `isNotEmpty` matches one that is neither.
`isEmpty` is the only Colors operator that can match a NULL cell, and the comment on `compile()` says
so.
The stored-document check's `COLOUR_OPERATORS` set in `explorationTabs.ts` gains both.

#### Acceptance Criteria:

- [ ] A rule `{column: 'last_name', operator: 'isEmpty', value: '', background: 'warning-soft'}`
  paints the cells whose value is `null` and the cells whose value is `''`, and no others, in
  `computePageFormatting`.
- [ ] `isNotEmpty` on the same page paints exactly the other cells in that column.
- [ ] An `isEmpty` rule whose stored `value` is `'x'` still matches the NULL and `''` cells.
- [ ] Choosing is empty in the rules dialog removes the value field from the accessible tree, and
  Apply succeeds with no value typed.
- [ ] A stored tab document carrying an `isEmpty` rule restores with that rule in
  `presentation.formatting.rules`. The formatting check swaps an invalid block for the empty state
  rather than refusing the tab, so asserting only that the tab restores would pass unbuilt.

---

## Data Model

```ts
// apps/portal/src/features/data-explorer/dataExplorer.types.ts

export type FilterOperator =
  | '=' | '<>' | '>' | '>=' | '<' | '<='
  | 'isNull' | 'isNotNull'
  | 'contains' | 'notContains' | 'startsWith' | 'endsWith'
  | 'in' | 'notIn'
  | 'isEmpty' | 'isNotEmpty';

export type ColumnFilter = {
  column: string;
  operator: FilterOperator;
  /** The comparisons and the four text operators. Absent otherwise. */
  value?: string;
  /** `in` and `notIn` only. */
  values?: string[];
  valueKind?: FilterValueKind;
};

export type ColourOperator =
  | '=' | '<>' | '>' | '>=' | '<' | '<=' | 'like' | 'ilike' | 'regex'
  | 'isEmpty' | 'isNotEmpty';
```

```ts
// apps/portal/src/features/data-explorer/dataExplorer.constants.ts
export const EXPLORER_FILTER_VALUES_MAX = 1000;
```

## API / Interface Contract

```ts
// explorationQueryOps.ts
export function isTextType(type: string): boolean;
export function operatorsFor(type: string): FilterOperator[];

// renderExplorationSql.ts
export const ATHENA_QUERY_STRING_MAX = 262_144;
export function exceedsAthenaQueryLimit(sql: string): boolean;
```

`FilterValueDialog` gains `mode: 'single' | 'list'`, derived by its host from the operator, and
`onApply` takes `{value: string} | {values: string[]}`, and the dialog takes the column's existing
filter, so list mode can pre-fill it.

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── dataExplorer.types.ts            (FR-001–003, FR-006)
├── dataExplorer.constants.ts        (FR-002: EXPLORER_FILTER_VALUES_MAX; COLOUR_OPERATORS, labels)
├── renderExplorationSql.ts          (FR-001–003, FR-005)
├── renderExplorationSql.test.ts
├── explorationQueryOps.ts           (FR-002 canonical, FR-004 isTextType/operatorsFor, labels)
├── explorationTabs.ts               (stored-document checks for filters and rules)
├── ColumnFilterMenu.tsx             (FR-004)
├── FilterValueDialog.tsx            (FR-004 list mode)
├── OrderFilterDialog.tsx            (FR-004)
├── ExplorationResultsRegion.tsx     (FR-004 wiring)
├── useExploration.ts                (FR-005)
├── formatting.ts                    (FR-006)
├── RowColoursDialog.tsx             (FR-006)
├── filtering.test.tsx, formatting.test.ts, formattingUi.test.tsx, useExploration.test.ts
apps/portal/src/lib/errorMessages.ts (FR-005)
apps/portal/src/features/help/helpContent.ts
apps/portal/info/component-inventory/data-explorer-feature.md (rows for isTextType, operatorsFor, exceedsAthenaQueryLimit)
```

## Implementation Phases

### Phase 1: The model and the renderer

- The union, `values`, the constant, and the renderer for all eight operators (FR-001–003).
- `canonical()` for `values`, and the stored-document checks for filters.
- `exceedsAthenaQueryLimit`, the `useExploration` refusal and its wording (FR-005).
- Renderer tests, written as whole-clause string assertions, including the injection case.

### Phase 2: The surfaces

- `isTextType`, `operatorsFor`, the column menu, the list mode of `FilterValueDialog`, and
  *Order and filter* (FR-004).

### Phase 3: Colors, Help and the live check

- The two Colors operators, the dialog's hidden value field, and the stored-rule check (FR-006).
- The *Filter and sort* guide.
- The live check, run from a signed-in session after deploy, on a CSV table with a blank
  `last_name` cell and a `brnd_name` column: **is empty** on `last_name` returns the blank row and
  **is null** returns none; **contains** `abil` on `brnd_name` returns `Abilify`; **is one of**
  `Abilify` and `Abacavir` returns both brands; a Colors **is empty** rule paints the blank cell.
  Fold it into `docs/testing/e2e.md` at completion.
