# Spec: A Filter Is Built From Conditions and Groups, Not Typed as SQL

**ID:** SPEC-251
**Status:** In Progress
**Last Updated:** 2026-09-28
**Depends On:** SPEC-238, SPEC-243, SPEC-247, SPEC-249 (FR-003's list input), and the Help session's
`help-dbeaver-vocabulary` branch (FR-006), both merged before this spec's PR

## Overview

An outside review compared the Data Explorer with DBeaver, and Andrew approved its filtering changes
on 2026-09-28. The Explorer has two ways to filter today. The column menus build one condition per
column, and those conditions always combine with AND. For anything else there is a free-text
**Filter expression** box, where the user types raw SQL. Users do want OR, and several conditions on
one column, but typing SQL is the Query editor's job, not the Explorer's.

This spec removes the expression box and adds **Filter rows**, a point-and-click builder. It builds
conditions, several on one column if needed, and brackets them into groups that match **all** or
**any** of their conditions. It also adds **is like** and **is not like**, where `%` and `_` are
wildcards; **contains** and the other text tests stay literal searches. A tab, a history entry or a
saved view that still carries an expression keeps it. It still applies and is shown read-only, with a
way to remove it or open it in Query. None of it is ever dropped without the user asking.

### What was checked, and how

Read from the code at `8a628382`.

- **The model.** `ExplorationQuery` in `features/data-explorer/dataExplorer.types.ts` is
  `{filters: ColumnFilter[]; expression: string | null; ordering; grouping}`. `renderWhere` in
  `renderExplorationSql.ts` renders one filter bare, several as `(f1 AND f2 …)`, and the expression
  as `(expr)` after them, with a leading `WHERE` the user typed taken off.
- **One condition per column is a rule of the edits, not of the model.** `setFilter` in
  `explorationQueryOps.ts` replaces any filter on the same column, and its docstring says a second
  condition such as `x = 1 AND x = 2` is written out in the expression bar. `filterOf` returns the
  first filter on a column, and the header's filter mark, its padding and its accessible name all
  read it (`ColumnFilterMenu.tsx`, `ExplorationGridHeader.tsx`).
- **Order and filter re-sets every list filter on Apply.** Its submit loop re-parses each list
  filter's text and calls `setFilter` with it (`OrderFilterDialog.tsx`), and it seeds that text from
  every entry of `query.filters` at mount.
- **Where a description is stored.** A session's tabs, each tab's Back/Forward history, and a saved
  view's line all hold `ExplorationQuery`. `isValidQuery` in `explorationTabs.ts` gates the first two,
  and `readStrictQuery` gates saved views, refusing a key outside `QUERY_KEYS` / `FILTER_KEYS`.
  `readSavedView` also renders the view and refuses one Athena would reject for length.
- **The saved view's checksum covers the file's SQL text**, not a re-render (`lib/savedViewLine.ts`),
  so the renderer can change without marking old files as edited.
- **The literal text operators.** `likePattern` escapes `%`, `_` and `\` and the statement names
  `ESCAPE '\'`, so `AB_12` cannot match `ABX12`. Case is folded by Trino on both sides with
  `lower()` (the SPEC-238 register entry). The Colors rules offer a case-sensitive
  "matches (% and _)" and a separate "matches, ignoring case", both with no escape character
  (`formatting.ts`, `likeExpression`).
- **The surfaces that set filters.** The column menu (`ColumnFilterMenu.tsx`), its value dialog
  (`FilterValueDialog.tsx`), **Filter by this value**, **Order and filter** (`OrderFilterDialog.tsx`,
  one operator select per column), the chips (`ExplorationResultsRegion.tsx`), **Remove all filters
  and sorts** and Back/Forward (`useExplorationQuery.ts`, `FilterHistoryControls.tsx`).
- **What only the expression could say.** The Help guide on `main` sends three cases there: OR, a
  list that keeps its NULL rows, and a numeric comparison on a CSV text column with `TRY_CAST`. It
  also offered comparing two columns. The Help session's unmerged `help-dbeaver-vocabulary` branch
  adds a fourth pointer, for a LIKE pattern of the user's own, and a `help.test.tsx` check that the
  guide says LIKE, NOT LIKE, IN and NOT IN.
- **Nothing is cached across a reload.** The execution cache is TanStack's, in memory
  (`lib/queryClient.ts` has no persister), and the history's record of failed statements is a
  `useRef` that is never persisted. So a restored tab runs its statement once on load.

### The decisions, made while authoring

- **The top level always joins with AND, and OR lives in a group.** This is today's rule at the top
  level, so every stored filter list is already a valid filter and needs no migration. It also keeps
  the column menus predictable: a filter set from a menu always narrows the rows. With a top level
  that could be OR, a menu gesture would either widen the result or have to wrap the whole filter in
  a new group.
- **Groups nest two deep.** A group sits at the top level, and it may hold one more level of groups.
  That can say `(A or B) and (C or D)` and `(A and B) or (C and D)`, which covers what people ask
  for, without a builder that recurses without bound. The stored-document check holds the same
  bound, so a hostile saved view cannot nest deeper.
- **The column menus, Filter by this value and Order and filter edit only the top level.** A menu
  gesture replaces that column's top-level conditions and leaves every group alone, exactly as it
  replaces the column's one filter today. Reaching into an OR group would change what the group
  means in a way the menu cannot show. Order and filter keeps its one select per column while the
  column has at most one top-level condition, and shows a note for a column with more. Its Apply
  re-sets only the columns it shows a select for, so it never merges two conditions into one.
- **An edit keeps what it did not touch.** The builder and Order and filter hand back a condition
  the user did not change as the stored object itself, so a field neither surface shows is never
  lost on the way through. SPEC-249's `includesNull`, which lands before this spec, is the case
  in view.
- **A flat filter renders byte-identical SQL.** Nothing is cached across a deploy, so this is not
  about the cache. It is the proof that the change is additive: every filter a user can build today
  still means and says exactly what it did, which the unchanged expected strings of the existing
  renderer tests show. Only groups render anything new.
- **"is like" ignores capitals, like the four text tests beside it.** A user who changes "contains"
  to "is like" to add a wildcard should not lose rows because of capitals. The folding is Trino's,
  `lower()` on both sides, for the reason SPEC-238 gives. Case-sensitive variants stay rejected.
- **"is like" has no escape character.** `%` and `_` are always wildcards and every other character,
  a backslash included, is itself. That matches the Colors rules' "matches (% and _)", and it means
  no pattern can be one Athena refuses to parse. To find a `%` or `_` itself, the user picks
  **contains**, **starts with** or **ends with**, and the hint under the field says so.
- **A stored expression is kept, not converted.** Turning free SQL into conditions needs a SQL
  parser, and anything the parser did not cover would be lost without a word. So `expression` stays
  in the model as a read-only field. It still renders exactly as before, and the filter row shows it
  verbatim with **Remove SQL condition** and **Open in Query**. Nothing in the Explorer writes a new
  one. Keeping the field name means no document needs rewriting and the saved-view line stays at
  version 1.
- **The builder is a staged dialog.** Every apply is a query and a bill, so the builder edits a draft,
  and **Apply** makes the whole change one execution, as **Order and filter** does. It opens from a
  **Filter rows…** button that sits where the expression box was, whatever the results are doing, so
  there is always a way to correct a filter.
- **What moves to Query.** Comparing two columns, calling a function such as `TRY_CAST`, and a
  case-sensitive match are raw SQL, and the builder does not offer them. The guide sends people to
  **Open in Query** for them. This is the cost of decision 1 in Andrew's approval, and it is stated
  here so the Help pass does not promise otherwise.

## Scope

### In Scope

- The filter model gains groups, and every store reads and checks them (FR-001).
- **is like** and **is not like** (FR-002).
- The **Filter rows** builder, with SPEC-249's value picker as its list input (FR-003).
- Removing the expression box, the chips for groups, and the read-only stored expression (FR-004).
- The column menus, Filter by this value and Order and filter at the top level (FR-005).
- Help, the Key Decisions register, the inventory and the live checks (FR-006).

### Out of Scope

- **Converting a stored expression into conditions**, or any SQL parsing.
- **Comparing two columns, functions and casts** such as `TRY_CAST`, a case-sensitive match, and an
  escape character for **is like**. These are Query's.
- **A top level that joins with OR**, and groups more than two deep.
- **The value picker itself.** SPEC-249 builds it, and this spec only places it in the builder.
- **Editing a condition from its chip.** A chip removes, as SPEC-243 decided.
- **Reordering conditions by drag.** Order within a group does not change what it matches.
- **The Colors rules**, which keep their own operators.
- **The Options menu's layout**, which the Data Explorer papercut PR is regrouping.

---

## Functional Requirements

### FR-001: A filter holds conditions and groups, and every stored filter still reads the same

#### Description:

`ExplorationQuery.filters` becomes `FilterItem[]`, where an item is a `ColumnFilter` or a
`FilterGroup` (Data Model). The top level joins with AND. A group joins its items with its own `join`
and holds at least one item, and groups nest at most `FILTER_GROUP_DEPTH_MAX` (2) deep. A group is
told apart from a condition by `Object.hasOwn(item, 'items')`.

The renderer renders a condition exactly as today. It renders a group as its items joined with
` AND ` or ` OR `, always in parentheses. The top level keeps today's rule: one item bare, several
as `(i1 AND i2 …)`, then `AND (expression)` when there is one.

`isValidQuery` (the session store and history) and `readStrictQuery` (saved views) accept groups
and hold them to the same bound. `sameQuery` compares every container's items without regard to
their order, as it already does for the top level.

#### Acceptance Criteria:

- [ ] A description whose filters are all conditions renders the same SQL as before: no expected
      SQL string in the existing `renderExplorationSql.test.ts` cases changes in this spec's diff.
      The operator population count and the text-operator list there change for FR-002 only.
- [ ] `{join: 'or', items: [a = 1, b = 2]}` alone renders `WHERE ("a" = '1' OR "b" = '2')`. Beside a
      top-level `c = 3` it renders `WHERE ("c" = '3' AND ("a" = '1' OR "b" = '2'))`. A subgroup
      renders `("x" = '1' OR ("y" = '2' AND "z" = '3'))`.
- [ ] Two conditions on one column, `qty > 5` and `qty < 10`, applied from the builder both reach
      the statement, and both survive a reload of the session store.
- [ ] A stored session document written before this spec restores with its filters unchanged, and
      a document carrying groups restores whole, history included.
- [ ] The session store and `readStrictQuery` both refuse a group nested three deep, a group with no
      items, a `join` other than `and` or `or`, and a condition inside a group whose operator is
      `toString`. A saved view whose group carries a key other than `join` and `items` is refused.
      A test asserts each refusal separately, not one of them standing in for the rest.
- [ ] `sameQuery` is true for two descriptions that differ only in the order of the items in a
      group, and false for two that differ only in a group's `join`.
- [ ] A saved view carrying a group reopens with the group.

### FR-002: "is like" and "is not like" match a pattern the user writes

#### Description:

Two rows are added to `FILTER_OPERATOR_SPECS` after `endsWith`: `like` ("is like") and `notLike`
("is not like"). Each takes one value, is offered on text columns only, and quotes its value whatever
the column holds. They render
`lower("col") LIKE lower('<pattern>')` and `lower("col") NOT LIKE lower('<pattern>')`, where
`<pattern>` is the user's text through `sqlLiteral` alone, with nothing escaped and no `ESCAPE`
clause. An empty pattern is refused, as the four text tests refuse one.

Wherever a value is typed for either operator — the column menu's value dialog, **Order and
filter** and the builder — the field carries this hint beneath it, tied to it with
`aria-describedby`: "% matches any run of characters and _ matches any one character. Capitals are
ignored. To find a % or _ itself, use contains."

#### Acceptance Criteria:

- [ ] A text column's menu offers **Filter: is like…** and **Filter: is not like…** after
      **Filter: ends with…**. A number or date column's menu offers neither.
- [ ] `name is like A%B_c` renders `lower("name") LIKE lower('A%B_c')`. `is not like` renders
      `NOT LIKE`. A quote in the pattern is doubled, and a backslash passes through unchanged.
- [ ] `contains` still escapes its wildcards: the existing case
      `lower("name") LIKE lower('%a\%b\_c\\d%') ESCAPE '\'` in `renderExplorationSql.test.ts`
      keeps its expected string.
- [ ] Applying either operator with nothing typed shows "Enter the text to match." at the field and
      starts no execution, in the value dialog, in Order and filter and in the builder.
- [ ] The hint is shown, and named by the field's `aria-describedby`, for these two operators only.
- [ ] The chip reads `name is like “A%B”`.
- [ ] The stored-document test that restores a tab carrying every operator covers both new ones,
      with its asserted population size raised by two.

### FR-003: Filter rows builds conditions and groups, and applies them as one query

#### Description:

`FilterBuilderDialog` is a `FormDialog` titled **Filter rows**, opened from the **Filter rows…**
button (FR-004). It starts from the applied filters and edits a draft, so nothing runs until
**Apply**, and **Cancel** discards the draft. The legacy expression is neither shown nor changed here.

The dialog says the rows must match all of the top-level items. Each condition has a column select,
an operator select and a value input:

- The columns are the source's, by the rule the Grouping panel uses: `schemaColumns` while a grouping
  is in force, and every column otherwise, hidden ones included. The browser-calculated percentage
  column is not offered.
- The operators are `operatorsFor(type)`.
- The value input is a text field for an operator that takes one value, and nothing for the null and
  empty tests. For **is one of** and **is not one of** it is the one-per-line field that Order and
  filter uses, as SPEC-249 extends it, so a list holding `''` and SPEC-249's `includesNull` both
  round-trip through it. SPEC-249's **Pick values** control sits beside it. That control mounts
  `FilterValuePicker` only when pressed, with no narrowing (`{filters: [], expression: null}`),
  because inside an OR group, narrowing one condition's values by its neighbours would hide the
  values the OR exists to reach.

A new condition starts with no column chosen. Changing its operator keeps a single value across the
single-value operators and keeps a list across the two list operators, as Order and filter does. A
condition the user did not change is handed back as the stored object itself, every field included.

**Add condition** and **Add group** sit at the foot of the top level and of every group. A subgroup
offers no **Add group**. After **Add condition** focus goes to the new condition's column select, and
after **Add group** to the column select of the group's first condition. After a condition or group
is removed, focus goes to the first control of the item that took its place, else of the item before
it, else to its container's **Add condition**. A new group starts with one empty condition. It matches **any** at the top
level, and inside a group it takes the opposite of that group's match, which is the only reason to
nest. A group's select reads **all of these** or **any of these**. The word between items (*and* or
*or*) follows its container's join. Every condition and group has a **Remove** control.

**Apply** checks the draft with the predicates the other value inputs use, and runs nothing while
any check fails. The checks are: a condition with no column ("Choose a column."), an empty text or
pattern value ("Enter the text to match."), a non-number on a numeric comparison
(`NUMERIC_VALUE_REFUSAL`), the list reader's refusals (`parseFilterValues`), and a group with no
items ("Add a condition to this group, or remove the group.").

A condition naming a column the source no longer lists is shown under its own name and kept on
Apply, unless the user removes it.

#### Acceptance Criteria:

- [ ] Building `status equals open` and a group matching any of `region equals EU` and
      `region equals US`, then pressing **Apply**, starts exactly one execution and pushes one
      history entry. The statement is `… WHERE ("status" = 'open' AND ("region" = 'EU' OR "region" = 'US'))`.
- [ ] **Cancel** after changes starts nothing and leaves the applied filter unchanged.
- [ ] **Add condition** puts focus on the new condition's column select. Removing the last item of a
      group puts focus on that group's **Add condition**.
- [ ] **Add group** is present at the top level and in a top-level group, and absent in a subgroup.
      A top-level group starts as **any of these**, and its subgroup starts as **all of these**.
- [ ] Each refusal listed above is shown at its own condition or group and stops the apply. A test
      covers the empty group and the unchosen column, and one other refusal.
- [ ] Removing every condition and applying clears the filter in one execution. Applying a draft
      identical to the applied filter starts nothing.
- [ ] A stored condition on a column the source no longer lists appears under its name, and survives
      an Apply that changed a different condition.
- [ ] A stored `in` condition carrying `includesNull` is still the same object, `includesNull`
      included, after an Apply that changed a different condition.
- [ ] With a legacy expression applied, an Apply from the builder keeps the expression in the
      statement.
- [ ] Every control's accessible name says which condition or group it belongs to, and the open
      dialog passes the axe check on the container the test drove.
- [ ] Opening the builder over a filter with an **is one of** condition starts no execution.
      Pressing that row's **Pick values** mounts the picker with no narrowing.

### FR-004: The expression box leaves, and the filter row shows the whole filter

#### Description:

`ExpressionBar.tsx` is deleted, and its row becomes the filter row. The row always shows the
**Filter rows…** button, whether the results are loading, failed, empty, held or suspended. After
the button comes the `ChipList` (renamed **Filters**), with one chip per top-level item:

- A condition's chip reads as today.
- A group's chip reads its conditions in words, joined by *and* or *or*, in parentheses, with a
  subgroup in its own parentheses: `(region equals “EU” or region equals “US”)`.

Removing a chip removes that item, a whole group included, in one apply. Focus then goes to the next
chip's remove control, else the previous one's, else the **Filter rows…** button. The held tab's
**Run** also hands focus to that button.

When `query.expression` is not blank, a notice follows the chips. It says the rows are also filtered
by a condition written in SQL, which the Explorer no longer edits. It shows the text verbatim in
`<code>`, and offers **Remove SQL condition** (one apply, `expression: null`) and, while the `query`
flag is on, **Open in Query**, which opens the generated statement as the existing control does.
Nothing in the Explorer sets a non-null expression. **Remove all filters** clears conditions, groups
and the expression in one apply, as it does today.

#### Acceptance Criteria:

- [ ] No **Filter expression** field and no **Apply expression** button render anywhere in the
      Explorer, and no source file imports `ExpressionBar`.
- [ ] **Filter rows…** is present while the results are loading, after a failed apply, when the
      result is empty, and on a held tab.
- [ ] A group's chip reads `(region equals “EU” or region equals “US”)`, and its remove control is
      named `Remove filter: (region equals “EU” or region equals “US”)`. Removing it starts one
      execution whose statement no longer holds the group, and leaves the other chips.
- [ ] Removing the only chip puts focus on **Filter rows…**.
- [ ] A restored tab carrying `expression: "status <> 'void'"` beside one condition shows the notice
      with that text, and starts exactly one execution, whose `WHERE` reads
      `<condition> AND (status <> 'void')`.
- [ ] **Remove SQL condition** starts one execution without the expression, and the notice goes.
      Stepping **‹ Back** brings the expression and the notice back.
- [ ] **Open in Query** in the notice is absent with the `query` flag off, and with the flag on it
      hands the generated statement to Query, as the existing control does. The gated-surfaces
      registry already names **Open in Query** on `/explore` and finds it on a tab with no
      expression, through the *Generated SQL* control, so this criterion is the only test of the
      notice's copy.
- [ ] A saved view carrying an expression reopens with the notice, and saving it again keeps the
      expression in the file's view line.

### FR-005: The column menus, Filter by this value and Order and filter work at the top level

#### Description:

`setFilter` and `clearFilter` act on the top level only. They replace or remove that column's
top-level conditions and leave groups and other columns' items in place. `filterOf` returns a
column's top-level condition only when it is that column's only top-level condition.
`isFilteredAnywhere` says whether any condition at any depth names the column. `setFilter`'s
docstring stops pointing at the expression bar.

- **The column menu.** Every **Filter: …** gesture, its value dialog and **Filter by this value** go
  through `setFilter`. **Clear filter** is enabled when the column has a top-level condition. When
  its conditions are all inside groups, it is refused with the reason "This column’s conditions are
  inside a group — change them in Filter rows." The header's filter mark, its wider padding and the
  trigger's accessible name (*filtered*) all follow `isFilteredAnywhere`, so the mark and the name
  never disagree. `ColumnQueryActions` gains the readers this needs.
- **Order and filter.** A column with at most one top-level condition keeps its select and value
  input, as today. A column with two or more shows "<n> conditions — change them in Filter rows" in
  their place. The dialog seeds its list text from top-level conditions only, and its Apply re-sets
  only the columns that show a select, so it never reads an operator off a group and never merges
  two conditions into one. Apply leaves those conditions, every group and the expression unchanged.

#### Acceptance Criteria:

- [ ] With `qty > 5` at the top level and `qty = 1` inside a group, **Filter: equals… 7** from the
      `qty` menu leaves `qty = 7` at the top level and `qty = 1` in its group, with the group
      otherwise untouched.
- [ ] With the same filter, **Clear filter** removes only `qty > 5`. With only the grouped
      condition left, **Clear filter** is refused with the reason above, and the header still shows
      its filter mark and says *filtered*.
- [ ] **Filter by this value** on a cell of a column with two top-level conditions leaves one
      top-level condition on that column.
- [ ] With `qty is one of 1, 2` and `qty > 0` at the top level and a group elsewhere, Order and
      filter opens without error and shows "2 conditions — change them in Filter rows" for `qty`.
      Changing another column's sort there and applying starts one execution and keeps both `qty`
      conditions and the group.
- [ ] A filter with no groups and one condition per column behaves in the menus and in Order and
      filter exactly as before: the existing `filtering.test.tsx` and `ordering.test.tsx` scenarios
      pass unchanged, except the text-column menu's list of items, which gains FR-002's two.

### FR-006: Help, the register and the records say it

#### Description:

The **Filter and sort** guide (`explore-filter-sort` in `helpContent.ts`) describes **Filter rows…**,
**all of these** / **any of these**, several conditions on one column, **is like** with its wildcards
and its ignored capitals, the read-only SQL condition and its two controls, and **Open in Query** for
what the builder cannot say. This spec's PR is rebased onto the Help session's
`help-dbeaver-vocabulary` branch after it merges. The guide keeps the LIKE / NOT LIKE / IN / NOT IN
wording that branch's `help.test.tsx` check requires, and the step that branch adds, which sends a
pattern of the user's own to the expression box, names **is like** instead. No guide mentions
**Filter expression** or **Apply expression**, and a `help.test.tsx` assertion holds that for every
guide, so a later Help edit cannot bring the control back into the words.

In `docs/decisions/analytics.md`, the SPEC-238 entry's "Rejected: raw `LIKE` / `NOT LIKE`" line is
marked superseded in place. Every other register or arc line that describes the expression bar as
live is marked where it stands: the SPEC-243 entry, `analytics.md`'s note that the bar passes the
user's SQL through, the two `browser.md` lines listing it among the surfaces and the toolbar, and
`ARCS.md`'s line that raw LIKE patterns stay in the expression box. A new entry records this spec's
decisions, and a Fences clause records the trap: an item of
`query.filters` may be a group, so code that walks it must not assume a `ColumnFilter`, and a menu
edits the top level only. The too-long-statement message in `lib/errorMessages.ts` stops telling
people to shorten an expression.

#### Acceptance Criteria:

- [ ] Outside test files, `grep -rn "Filter expression\|Apply expression" apps/portal/src` finds
      nothing, and the new `help.test.tsx` assertion fails when either phrase is planted in a guide.
- [ ] Every hit of `grep -rn -i "expression bar\|expression box" docs/decisions docs/specs/ARCS.md`
      either carries a supersede marker or describes something other than the Data Explorer.
- [ ] The guide names **Filter rows…**, **any of these**, **is like**, **Remove SQL condition** and
      **Open in Query**, and `help.test.tsx` passes.
- [ ] The SPEC-238 register entry's raw-LIKE rejection carries a supersede marker naming this spec,
      and the new entry and the Fences clause exist. `validate_docs.py` passes.
- [ ] The inventory has no `ExpressionBar` row and has a `FilterBuilderDialog` row.
- [ ] `docs/testing/e2e.md`'s Data Explorer checks drive **Filter rows…** where they typed an
      expression.

---

## Data Model

```ts
// apps/portal/src/features/data-explorer/dataExplorer.types.ts

export type FilterOperator = /* today's sixteen */ | 'like' | 'notLike';

/** How a group's items combine. The top level always combines with AND. */
export type FilterJoin = 'and' | 'or';

/** Bracketed conditions that must all hold, or any one of which must. */
export type FilterGroup = {
  join: FilterJoin;
  /** At least one. A top-level group may hold groups; a group inside a group may not. */
  items: FilterItem[];
};

export type FilterItem = ColumnFilter | FilterGroup;

export type ExplorationQuery = {
  /** Every item must hold. */
  filters: FilterItem[];
  /**
   * A condition typed into the filter box the Explorer no longer has. Read-only: it still
   * renders, shows verbatim and can be removed, and nothing writes a new one.
   */
  expression: string | null;
  ordering: SortEntry[];
  grouping: Grouping | null;
};

// apps/portal/src/features/data-explorer/dataExplorer.constants.ts
/** How deep groups nest: a top-level group, and one level inside it. */
export const FILTER_GROUP_DEPTH_MAX = 2;
```

## API / Interface Contract

```ts
// apps/portal/src/features/data-explorer/explorationQueryOps.ts
export function isFilterGroup(item: FilterItem): item is FilterGroup;
/** Replaces the column's TOP-LEVEL conditions with this one; groups are untouched. */
export function setFilter(query: ExplorationQuery, filter: ColumnFilter): ExplorationQuery;
/** Removes the column's top-level conditions. */
export function clearFilter(query: ExplorationQuery, column: string): ExplorationQuery;
/** The column's top-level condition when it is the only one there, else null. */
export function filterOf(query: ExplorationQuery, column: string): ColumnFilter | null;
/** The column's top-level conditions, in order. */
export function topLevelConditionsOn(query: ExplorationQuery, column: string): ColumnFilter[];
/** Whether any condition, at any depth, names the column. */
export function isFilteredAnywhere(query: ExplorationQuery, column: string): boolean;
/** Removes one top-level item by position. */
export function removeFilterItem(query: ExplorationQuery, index: number): ExplorationQuery;
/** A top-level item in words, for its chip. */
export function filterItemLabel(item: FilterItem): string;

// apps/portal/src/features/data-explorer/FilterBuilderDialog.tsx
export type FilterBuilderDialogProps = {
  columns: QueryColumn[];
  queryRefusalOf: (column: string) => string | null;
  source: ExplorationSource;
  filters: FilterItem[];
  onApply: (filters: FilterItem[]) => void;
  onCancel: () => void;
};
```

## File & Folder Structure

```
apps/portal/src/features/data-explorer/
├── dataExplorer.types.ts, dataExplorer.constants.ts           (FR-001, FR-002)
├── renderExplorationSql.ts (+ test)                           (FR-001, FR-002)
├── explorationQueryOps.ts (+ test)                            (FR-001, FR-005)
├── explorationTabs.ts, savedView.ts (+ tests)                 (FR-001)
├── FilterBuilderDialog.tsx                                    (FR-003, new)
├── filterBuilder.test.tsx                                     (FR-003, new)
├── ExplorationResultsRegion.tsx, filterChips.test.tsx         (FR-004)
├── ExpressionBar.tsx, expressionBar.test.tsx                  (FR-004, deleted)
├── ColumnFilterMenu.tsx, ExplorationGridHeader.tsx            (FR-005: the mark and the readers)
├── FilterValueDialog.tsx, OrderFilterDialog.tsx               (FR-002, FR-005)
├── queryHistory.test.tsx, saveExploration.test.tsx            (FR-004: no bar to type into)
apps/portal/src/features/help/helpContent.ts, help.test.tsx    (FR-006)
apps/portal/src/lib/errorMessages.ts                           (FR-006)
apps/portal/info/component-inventory/data-explorer-feature.md  (FR-006)
docs/decisions/analytics.md, browser.md, docs/specs/ARCS.md    (FR-006)
docs/testing/e2e.md                                            (FR-006)
```

`queryHistory.test.tsx`, `saveExploration.test.tsx` and `expressionBar.test.tsx` type a bad
expression to make an apply fail, and it is how the suspended-history tests mint a failed statement.
With the bar gone they apply a column filter instead, and the mocked status call answers `FAILED` for
the statement that filter renders. `expressionBar.test.tsx`'s scenarios about the region itself —
a failure keeps the last good rows and the toolbar, a watch that outlives its ceiling does too, and
the filter row is there with the `query` flag off — move to a test driven that way, not away.

## Implementation Phases

### Phase 1: The model, the renderer and the two operators

- Types, the depth constant, group rendering, `sameQuery`, both stored-document gates, the top-level
  edits and the two operator rows (FR-001, FR-002's rendering, FR-005's edits).

### Phase 2: The builder

- `FilterBuilderDialog` with the typed list field (FR-003 except **Pick values**).

### Phase 3: The filter row and the existing surfaces

- Remove `ExpressionBar`, add the button, the group chips and the SQL condition notice. Make the
  menu, the value dialog and Order and filter's top-level changes, and add the **is like** hint at
  every value input (FR-002's hints, FR-004, FR-005).

### Phase 4: The picker in the builder

- Once SPEC-249 has merged: **Pick values** on the builder's list rows (FR-003's last criterion).

### Phase 5: Help and the records

- The guide, the register, the inventory, the error message and the live checks (FR-006). The live
  check, run from a signed-in session after deploy: build `status equals X` and an **any** group of
  two values on another column. One execution runs, the chips read as specified, and removing the
  group's chip widens the rows. Then **is like** `A%` on a text column matches values starting with
  a or A.
