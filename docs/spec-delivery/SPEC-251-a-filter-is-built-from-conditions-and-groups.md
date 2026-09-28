# Completed Spec — SPEC-251: A Filter Is Built From Conditions and Groups, Not Typed as SQL

## What was completed?

- **Filter rows…** (`FilterBuilderDialog`, with its pure draft in `filterBuilderDraft.ts`) builds
  conditions and groups by pointing, staged, and applies them as one execution. The top level
  matches all of its items; a group matches **all** or **any of these** and may hold one more level
  of groups. A list row carries SPEC-249's typed field and **Pick values**, which mounts
  `FilterValuePicker` only when pressed, with no narrowing.
- `ExplorationQuery.filters` is `FilterItem[]` (`ColumnFilter | FilterGroup`, told apart by
  `isFilterGroup`). The renderer brackets every group and renders a flat list byte for byte as
  before. Both stored-document gates accept groups two deep and refuse deeper, empty, badly joined
  or extra-keyed ones. `sameQuery` ignores item order at every depth.
- **is like** / **is not like**: `%` and `_` are wildcards, capitals fold in Trino on both sides,
  there is no escape character, and a hint rides on the operator table (`hint`) to all three value
  inputs.
- The expression bar is gone (`ExpressionBar.tsx` deleted). The filter row is **Filter rows…** plus
  one chip per top-level item, a group worded in its brackets, and focus moves by position after a
  removal. A stored expression shows verbatim in `SqlConditionNotice`, with **Remove SQL condition**
  and, under `query`, **Open in Query**.
- The column menu, **Filter by value…** and Order and filter edit top-level conditions only
  (`setFilter`, `clearFilter`, `filterOf`, `topLevelConditionsOn`). The header mark follows
  `isFilteredAnywhere`, and Clear filter is refused with a reason when a column's conditions are all
  grouped. Order and filter shows "<n> conditions — change them in Filter rows" for a column with
  two or more, and re-sets only the columns it shows.
- Help's *Filter and sort* guide, a `help.test.tsx` guard that no guide names the retired box, the
  analytics register entry and its Fences clause, supersede markers in `analytics.md`,
  `browser.md` and `ARCS.md`, the inventory, and the live checks in `e2e.md` (§4.5, rows 8 and
  W–AA).

### Deliberate deviations

- The pattern hint is a column of the operator table rather than a literal at each surface, so a
  later operator that needs one reaches all three inputs at once.
- The notice is a named group ("Condition written in SQL") so its **Open in Query** can be told
  apart from the Options menu's control of the same name.

## What changed from earlier specs?

- SPEC-238: raw `LIKE` was rejected because the expression bar existed. That rejection is
  superseded in place; case-sensitive variants stay rejected.
- SPEC-243: the chips sit beside **Filter rows…** rather than under the box, are one per top-level
  item, and hand focus back by position.
- SPEC-178/181 (`ARCS.md`): the bar's pass-through and its ungated `query` exemption are marked
  superseded. There is no free-SQL input on the page any more.
- `setFilter`/`clearFilter`/`filterOf` changed meaning from "the column's filter" to "the column's
  top-level condition". SPEC-249's `narrowingFor` keeps groups whole.
- The too-long-statement message no longer tells people to shorten an expression.

## Verification

Local: format, ESLint, both suites (Vitest and pytest), mypy, ruff, `npm run build`, the bundle
check and every `ci.yml` validator, all green by exit code. Mutation-checked guards: the depth
bound both ways, the clean-row pass-through, the unlisted column's `valueKind`, Order and filter's
merge guard, the filter mark, the mount-on-press picker, and the Help guard for each phrase. The
live checks (§4.5 W–AA) run after deploy, from a signed-in session.
