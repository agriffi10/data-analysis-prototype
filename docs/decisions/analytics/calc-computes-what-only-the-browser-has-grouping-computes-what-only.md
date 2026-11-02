---
type: Decision
title: "Calc computes what only the browser has, grouping computes what only Athena can, and the percentage says which page it is of (SPEC-182)"
description: "Calc aggregates selected cells in the browser and issues zero executions, grouping runs in Athena with one execution per apply, and a grouped percentage is a share of the current page whose header says `(this page)`."
---

Two panels that look like siblings and are the opposite of one another. The split is not a
compromise between fidelity and cost — it falls out of what each panel *is*, and everything else in
the spec follows from getting that right.

**Calc is client-side because a selection is client state.** It aggregates the cells the user has
selected, and those exist nowhere but the browser, so a server-side Calc means a billed
`StartQueryExecution` **per selection change** — for a gesture as cheap as dragging across ten
cells. Grouping is the mirror image: aggregating in the browser would aggregate whichever rows
happened to have been fetched, which is the scale lie the whole feature was designed to avoid. So
Calc issues **zero** executions (asserted by count, FR-001 AC7) and grouping mints exactly one per
apply, however many columns and aggregates changed — which it gets for free by staging a draft and
going through SPEC-181's single `apply`.

Because Calc's numbers are true only of loaded, selected cells, the panel **says so every time it
says anything**: `calcScopeText` renders "N selected cells on this page", and none of those words
are droppable. With nothing selected it explains itself rather than showing zeroes — a column of
`0`s reads as a computed answer to a question nobody asked. The numeric predicate is the renderer's
own `isBareNumeric` rather than a second rule, so the panel and the filter cannot disagree about
which cells are numbers; a `count` of an empty set is `0` and an empty `sum` is `0` (both real
answers) while every other function shows a no-value marker, which is the guard that is easy to draw
one line too wide.

**The percentage is of the rows on the CURRENT PAGE, and its column header says so.** Only one page
of a result is in the browser — `useQueryResults` exposes exactly one — so a share computed here is
a share of those rows and nothing else. A column headed `% of count_all` beside a paged result would
be read as a share of the table, which is precisely the class of claim grouping exists to prevent,
so the header is `% of count_all (this page)`. The alternative, a windowed total in the SQL, is a
second scan of the same data for a column the user asked only to *see*; the flag renders no SQL at
all, and a test pins that. It rides on `Grouping` rather than on `ExplorationPresentation` even so:
it is meaningless apart from the grouping it describes, and a grouping restored from
`sessionStorage` has to restore whole.

**Grouping mode is exactly "at least one grouping column".** A grouping with aggregates and no
columns is legal SQL — a global aggregate — but FR-003 AC6 says removing every column leaves
grouping mode, and the alternative reading strands the user in a mode with nothing in it. So
`setGrouping` maps an empty-column grouping to `null`, and **leaving grouping mode drops any sort on
an aggregate's output column**: `count_all` exists only while the grouping does, so carrying that
`ORDER BY` onto the raw table is a query Athena rejects — and it would also miss the cached ungrouped
execution AC6 promises to return to. That is the half of AC6 the spec does not mention and the whole
of what makes it work.

**`groupingOrderingViolation` is exported for the same reason `isBareNumeric` was.** Trino rejects an
`ORDER BY` on a column that is neither grouped nor aggregated, and the renderer refuses it first —
but that refusal is an `ExplorationRenderError` naming a column and an operator, which SPEC-106
forbids showing a user. So the rule returns the offending **column** and the two callers word it
differently: operator text in the renderer, a sentence naming the sort to clear on the panel's Apply
(`Button.disabledReason` — `aria-disabled`, reachable rather than hover-only). A second rule at the
panel is a rule that can disagree, and the way it would disagree is a grouping the panel accepts and
the renderer throws on, which takes the whole exploration to an error banner. The refusal belongs on
Apply because that is where the conflict is *built* — sort a column, then group it away.

**But the panel's Apply is not the only guard the rule needs, and this spec falsified its own premise
in the same commit.** "While a grouping is in force the grid shows only the grouping columns and the
aggregates" stopped being true the moment the percentage column was appended: it is a real
`GridColumn`, so it gets a header menu, a row in the settings dialog (the header menu's stand-in in
Record or Text view, **both since removed** ([the table-only entry](the-explorer-shows-a-table-and-nothing-else-and-a-saved-view-still.md)) — **corrected 2026-09-22**: this said the only path below `tablet`, which the
build never matched, since Grid view keeps the header menu at every width, as Andrew confirmed is
intended) and the toolbar's *Filter by this value* — and it exists in no statement, so sorting it is
a description the renderer REFUSES and filtering it is a `COLUMN_NOT_FOUND`. `ColumnQueryActions`
therefore carries **`queryRefusalOf`**, asked by every per-column surface before it offers a filter
or a sort; the header menu opens and states the reason rather than offering controls that each fail,
while Show, Pin, width and order stay available, because geometry applies to a calculated column like
any other. The lesson generalises past this column: **appending anything to `columns` before
`useColumnGeometry` hands it every affordance a real column has**, and the grid has no other way to
tell the two apart.

The same reachability argument closed a second hole. `assertGroupingIsRenderable` compared aggregate
aliases with each other and not with the **grouping columns**, which are projected beside them under
their own names — so grouping by a column called `count_all` while `COUNT(*)` is present produced two
result columns of one name, sharing one geometry key and leaving `groupingOrderingViolation` to
answer for whichever the reader meant. Unreachable before this spec, because nothing let a user
choose what to group by. `groupingNameCollision` is now the renderer's rule, exported on the same
precedent, and the panel refuses at the gesture.

**Both panels are `<aside>`s, not `Drawer`s, and that is structural rather than stylistic.** A
`Drawer` traps focus. Calc has to recompute as the selection changes and grouping takes a column
**dragged from a grid header**, so a focus trap would put the grid out of reach of the panel that
needs it. The dragged column travels by an additive `onColumnDrag` callback rather than through
`dataTransfer`, for the reason the header's own reorder ref already exists: `DataTransfer` is not
implemented everywhere, and a drop handler that depends on it works in a browser and nowhere else.
The panel is also offered the **source's** columns while a grouping is active, not the result's —
the result's are the grouping columns and the aggregate aliases by then, and offering those would
let a user group by `count_all`, a column that exists only inside the query it would be added to.

**The disclosure shows the string the execution used, never a second rendering of it.**
`useExploration` renders once, runs that string and returns it; `GeneratedSqlDisclosure` shows that
value. Re-deriving it for display is one `renderExplorationSql` call away and would drift the moment
a caller passed a slightly different description — and a disclosure that is right most of the time
is worse than none, because it would be believed. It is available whether or not grouping is active:
the Explorer writes SQL the user did not, grouped or otherwise, and every statement it writes is an
invoice.

**Calc opens on MIXED aggregation, and that default is not cosmetic.** Numbers-only narrows every
function, so a numbers-only default answers `Count 0` over a selection of three text cells — printed
directly under "3 selected cells on this page", which is the one pair of numbers this panel must
never show together. The toggle still narrows everything when a user asks for it; what changed is
which reading is the default.

Two smaller things worth carrying. `canonical()` folds the grouping's two new flags **explicitly**
and `readExplorationTabsState` normalises them (absent ⇒ false) — needed together, because a
document written before this spec carries neither flag and an absent flag comparing unequal to
`false` would push a history entry for an apply that changed nothing; the validator accepts them
absent rather than requiring them, since requiring them would discard **every tab** in the document
over a field that did not exist when it was written. And `CalcPanelState` is region state, not tab
state: it describes a selection, and a selection does not survive a page change, let alone a session.

## History

### 2026-09-22

- **Changed:** Corrected the claim that the settings dialog was the only path below `tablet`: Grid view keeps the header menu at every width.

### 2026-08-13

- **Settled:** SPEC-182.
