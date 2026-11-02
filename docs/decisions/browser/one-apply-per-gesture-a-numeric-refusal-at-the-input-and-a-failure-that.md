---
type: Decision
title: "One `apply` per gesture, a numeric refusal at the INPUT, and a failure that keeps the rows (SPEC-181)"
description: "Every description change goes through one `apply`, so one gesture is at most one execution; a bad numeric value is refused at the input, and a failed query keeps the last good rows."
---

This is the spec the Data Explorer exists for, and the only place in it where a user gesture spends
money. Four decisions are worth keeping.

**Every description change goes through ONE `apply`, and that is what makes "one gesture is one
execution" structural.** Four surfaces edit the query — the header menu, filter-by-cell, the
expression bar, the settings dialog — and each of them hands a `Partial<ExplorationQuery>` to
`useExplorationQuery.apply`, which writes the tab's description once; `useExploration` then renders
one statement and the execution cache decides whether it costs anything. Nothing else may write a
description. An apply that changes nothing is a **no-op**, compared with `sameQuery` on a canonical
form rather than field by field, because `filters` and `ordering` are arrays whose order carries no
meaning (priority does) — without that, applying the same filter twice would fill Back with
duplicates of one description. *(Superseded in part by SPEC-251: the expression bar is gone, and
the filter builder is the surface in its place; every surface still goes through the one `apply` —
[the SPEC-251 entry](../analytics/a-filter-is-conditions-and-groups-built-by-pointing-and-the-expression.md).)* `clearAll` deliberately **preserves `grouping`**: that is SPEC-182's,
and un-grouping a view from a control labelled "Remove all filters" is a change nobody asked for.

> **SUPERSEDED by SPEC-182 (FR-006 AC3): `clearAll` clears the grouping too, and the control's LABEL
> changes with it** — `Remove all filters` becomes `Remove all filters and grouping` while a grouping
> is in force. The concern above was never the clearing, it was the silence; naming the action is the
> other way to keep the same promise. `isEmptyQuery` counts grouping from the same spec, so its
> refusal wording changed with it. The UI copy audit later named sorts in both labels —
> `Remove all filters and sorts`, `Remove all filters, sorts and grouping` — because the clear had
> always removed them too, and a label naming only filters was the same silence.

**The hook takes the tabs result rather than reading its own** — a deviation from the spec's
`useExplorationQuery(tabId)`. The history lives with the tab in `sessionStorage` (FR-006 AC3) and
`useExplorationTabs` owns that document, so a second instance would be a second writer to one key,
diverging on the first edit. The tab id still names which tab, because a description and the history
entry it pushes have to be written in **one** update — `updateTab(id, fn)` exists for that; written
through two calls, a tab switch between them files the entry against the wrong tab. For the same
reason there is **no `stage`**: the spec's staging channel is query-only while FR-005 AC3 requires
Cancel to discard the **presentation** changes too, so the settings dialog holds one draft object
containing both halves and `apply` takes the whole staged description. Split in two, half a draft
could survive a Cancel.

**A numeric value is refused at the INPUT, with the renderer's own predicate.** SPEC-178 emits a
numeric filter's value **bare** (Trino does not coerce) and throws `ExplorationRenderError` for a
value that is not a number — and that message names a column and an operator, which SPEC-106 forbids
rendering to anyone. So `isBareNumeric` is exported and both value inputs refuse with it, rather
than each growing a numeric rule of its own that can disagree with the renderer. The same predicate
drives a `Button.disabledReason` on *Filter by this value*, so a numeric column whose cell holds
something unfilterable refuses at the gesture instead of seconds later as a generic failure. The
value itself never reaches SQL unescaped either way: it rides on a `ColumnFilter` and is quoted by
`sqlLiteral` at render time, which is why the whole hazard — a cell containing `O'Brien` filtered by
`=` — is one test and not one code path per surface. Column names are **quoted, never validated**:
`CATALOG_IDENTIFIER_RE` describes names this app CREATES, and a column named `total amount` is
ordinary.

> **Superseded (SPEC-249, 2026-09-28) — the gesture refusal ONLY.** *Filter by this value* is now
> **Filter by value…**, which opens a list of the column's values; a numeric value `isBareNumeric`
> rejects is a disabled checkbox with its reason there, and the menu item no longer refuses for it.
> The full entry is [*A column's values are a list you tick*](../analytics/a-columns-values-are-a-list-you-tick-and-a-list-may-hold-empty-and-null.md). Everything else above is
> unchanged and still live.

**A failure keeps the last good rows, and Athena's refusal had to be made into an error first.** A
query Athena rejects is not an error anywhere in the plumbing — `getQueryStatus` **resolves**, and
the reason arrives as `stateChangeReason` on a successful poll — so `useExploration` now surfaces a
`FAILED`/`CANCELLED` execution as `{code, message}`, the shape `toUserMessage` maps engine text
from; without it a syntax error surfaced one layer later as "couldn't read the results", a true
sentence about the wrong thing. And `ExplorationResultsRegion` was restructured so the query toolbar
and the expression bar render whatever the results are doing, with `useQueryResults` pointed at the
**last execution whose rows actually arrived** while the current one is failed. A failed apply has
to leave the user somewhere they can correct it, and a toolbar that disappears with the rows takes
the correction with it. *(Superseded in part by SPEC-251: the filter row, with **Filter rows…**,
holds the expression bar's place and renders whatever the results are doing, for the same reason.)* The test for this is only meaningful because the failed execution's results
also fail — mocked to succeed, it passed with the fallback deleted.

**FR-006 AC4 needed a mechanism the spec did not name.** "Navigating history never re-runs a query
that failed" cannot come from the cache: SPEC-178 deliberately **evicts** a failed execution on the
way out, so restoring its description would start a fresh one. The tab keeps an in-memory set of
statements seen to fail this session, and a history step onto one **suspends** — `useExploration` is
handed nothing to run and a *Run it anyway* control is the retry. An `apply` always clears the
suspension, because an apply IS the user asking again. The set is not persisted: a failure from a
previous session should not stop this one from trying.

**Cost can only ever be reported, never predicted.** Athena will not say what a query will scan
before running it — no dry run, no `EXPLAIN` byte estimate, and the per-query statistics exist only
once the execution has finished — so a pre-flight "this looks expensive" confirm is **not
buildable**, and the guards are the workgroup's per-query cutoff plus this reporting. A cache hit
**says so** rather than repeating the figure the execution originally scanned, which is true about
the execution and false about the gesture; it is decided by reading the tab's ledger **during
render, before `recordScan` writes to it**, since after that write every execution looks known and
every apply would report itself free.

**A cost is only reportable once the execution is TERMINAL, and the fixtures hid the opposite.** A
`QUEUED`/`RUNNING` poll carries no `Statistics`, so `useExploration` reported a perfectly confident
0 B — and because the per-apply figure is captured once per execution (it must be, to read the ledger
before `recordScan` writes to it), that zero stuck for the life of the query while the running total
beside it said something else. Every test fixture in the feature returned `SUCCEEDED` on the first
call, so the AC's own test passed over a surface that was wrong for every real query. `cost` is now
null until the state is terminal.

Three implementation traps worth naming, because each looked correct and was silent.
`moveSortPriority` stamps priorities from the **array position** after the swap — re-stamping
through the shared "sort by priority, then number them" helper put the two entries straight back,
so the ↑/↓ controls were a no-op the dialog rendered as a success. **State that belongs to a tab
must be keyed by the tab**, and two pieces of it were not: `suspended` froze *every* tab, and the
last-good-execution fallback drew one tab's rows under another's error banner (visible only when the
failing tab had never succeeded — a tab with a good execution of its own falls back correctly either
way, which is why the first version of that test could not fail). And a `Modal` **does not portal**:
`FilterValueDialog` rendered inside a `<th>` would have been confined to that cell's stacking
context and painted under the sticky headers, which nothing in jsdom can see — the region raises it
and the header menu asks.

## History

### 2026-09-28

- **Changed:** *Filter by this value* became *Filter by value…*: a rejected numeric value is now a disabled checkbox in the list, and the menu item no longer refuses for it.

### 2026-08-13

- **Settled:** SPEC-181.
