# Completed Spec — SPEC-184: Presentation and Formatting

## What was completed?

Everything the Data Explorer needed to change how values *look* without changing what is
*fetched* — conditional colouring, colour-by-type, group row striping and per-column value
transformers, persisted with the tab.

- **`formatting.ts`** — the pure evaluator: nine operators, later-rule-wins **per property**,
  numeric gradients, banding over the current page, and the three transformer renderings.
- **`urlTransformer.ts`** — substitution, position-aware percent-encoding and the `https:`-only
  allowlist, judged on the **resolved** URL.
- **`RowColoursDialog`** (with `StripingControl` inside it) and **`TransformersDialog`** — two
  staged forms, two new toolbar controls, both free to open and free to apply.
- **`ExplorationPresentation.formatting`** — persisted per tab, validated and **discarded whole**
  if any part of it is wrong.
- **The two structural assertions**: a scripted UI sequence touching every rule and transformer
  leaves `runQuery` on the tab's opening execution, and a transitive import-closure walk from
  `renderExplorationSql.ts` proves no module this spec added is reachable from the renderer.

No infra, no IAM, no new AWS call — the same as every spec since SPEC-180.

## The decisions worth carrying

### The palette is a bounded token set, and `warning` was measured out of it

FR-002 AC8 asks that "every colour pairing meets contrast requirements". That is not a claim
anybody can make about a colour picker, so the rule model narrows the spec's `foreground?: string`
to a five-token union and its backgrounds to the four `*-soft` tints. The exclusion that fell out
of the measurement is the finding: **`warning` (#b45309) clears 4.5:1 on white at 5.02 and fails
on the soft backgrounds this spec introduces** — 4.49 on `accent-soft`, 4.39 on `danger-soft`. A
colour that is legible only sometimes is worse than one fewer colour, because nothing at the point
of choosing tells the user which case they are in.

The test recomputes the whole cross product, plus every shade the gradient can quantise to, plus
the mixed shades between two tints of different hues — where a "both ends are pale" argument
breaks. A second test pins `FORMATTING_TOKEN_HEX` against `src/index.css` itself, because the map
is a copy and it exists only because a gradient has to interpolate values and contrast has to be
computed from them.

**Axe cannot carry this criterion and saying it does would be false.** `color-contrast` is
disabled in `test/axe.ts` — jsdom has no layout engine to compute a rendered colour from — so the
axe pass proves the coloured grid's markup and the computation proves its contrast.

### The URL encoding is position-dependent, and both obvious rules are wrong

The first implementation percent-encoded the value unconditionally. That is right inside a path or
a query — a value must not be able to climb out of its segment, add a parameter or graft a
fragment on — and it is **wrong at the start of the template**, where `${value}` is the natural
template for a column that already holds links: encoding turns every legitimate `https://…` into
`https%3A%2F%2F…`, which is not a URL, so that column could never link at all. It also makes
FR-006 AC2's own worked example unreachable, since a `javascript:` value would fail as "not a URL"
rather than at the scheme check.

So the leading position substitutes **raw** and every later one is encoded, and the scheme
allowlist is what guards the leading case. Both refusals were driven through real cell values.

Two smaller things in the same module. The substitution is assembled part by part rather than with
`String.replace`, whose replacement string reads `$&`, `$'` and `` $` `` as patterns — a cell
holding one would be expanded into something other than itself before anything parsed it. And
`isSafeInAppPath` is **not** used, with the note at the call site: that rule governs in-app paths
and would reject every URL here by construction.

### `ColourRule` gained a `scope`, because one field could not carry two choices

The spec's model has only `column?`, read as "undefined applies across the row". That conflates
what a rule TESTS with what it PAINTS, and leaves the most ordinary rule of all inexpressible —
colour the whole row wherever `status` is `failed`. One optional `scope: 'cell' | 'row'` separates
them (SPEC-181's `valueKind` is the precedent), and an absent `column` keeps its own meaning: test
every cell in the row.

### The selection wins over a formatting background

A formatted cell is still selectable, and an inline background beats the class that paints a
selected one — so a coloured grid would be one a user cannot see their own selection in, which is
the selection SPEC-182's Calc panel aggregates. The cell drops its formatting fill while selected;
`aria-selected` says so either way, and the selection's own fill is one of the surfaces the
palette is measured against.

## What review found

Six defects, all fixed on the branch, all now covered by a test that was verified to fail without
the fix.

**A URL transformer broke the grid's single-tab-stop invariant, and nested an anchor inside a
button.** `role="grid"` promises one tab stop with the arrows moving within it — which is why every
cell but the cursor carries `tabIndex={-1}` — and a focusable anchor per row would have put a
hundred stops inside the grid, so Tab from the cursor walked the column instead of leaving. Worse,
the Record view puts every value inside a button, so a transformed cell there was **nested
interactive content**, the exact axe failure SPEC-179 had to correct once already. The anchor is
now `tabIndex={-1}`, the Record view renders the text without one, and **the Value panel carries a
focusable link** — which is what makes that decision cost a keyboard user nothing. The axe file had
no case that rendered a transformed cell at all; it now walks both views, and reverting the fix
reddens it with `nested-interactive`.

**A `LIKE` pattern could freeze the tab, and the app was manufacturing the pathology itself.**
Translating each `%` to its own `[\s\S]*` makes adjacent wildcards nested unbounded quantifiers:
`%%%%%%%%x` against a 60-character value measured at **31.7 s** here, inside a `useMemo` that runs
once per cell. `FORMATTING_PATTERN_MAX` bounds the input, not the runtime, and its docstring accepts
that residual risk for a user-authored *regex* — but `%%%` is something a user types believing it is
a wildcard. Runs of `%` now collapse to one: same matches, 0 ms.

**A gradient could not be given a negative or a decimal bound.** The inputs round-tripped through
`Number()`, so `-` became `NaN` and rendered as empty (the minus erased as you typed it) and `1.`
rendered as `1`. `-10..40` and `0..1.5` were unreachable — most of what a gradient is for. The
bounds are now held as typed, parsed alongside, and an emptied field is `NaN` rather than a silent
zero.

**A rule on a hidden column silently stopped working while the dialog called it applicable.**
Formatting was evaluated over the visible columns, so hiding `status` stopped a row rule reading
`status` — and `isRuleApplicable`, asked over all columns in the dialog, disagreed. Evaluation now
runs over every column: **a hidden column is still part of the row**. Same fix covers striping,
which silently turned off when every chosen column was hidden.

**Two smaller ones.** `encodeURIComponent` throws `URIError` on a lone surrogate, and the
substitution sat outside the `try` — a cell holding one would have thrown through the grid's render.
And a column named `__proto__` set an object's prototype instead of storing its format or its
transformer, which is not prototype pollution but does silently drop that column's formatting;
both writes now define the property.

**FR-007 AC2 had no test at all** — ~90 lines of validation whose stated job is the whole-block
discard and the palette check. It now has one, including the case that matters most: a stored
`warning` foreground, the token measured out of the palette, is refused.

## Deviations from the spec, taken in build

- **The Text view stays raw** — no colours, no transformers. It is the drag-select-and-copy
  surface, and FR-005 AC4 says the raw value drives copy. Colours and transformers apply to the
  grid and the Record view.
- **FR-005 AC4's copy assertion is owed to SPEC-185**, which builds copy. Filtering, colouring and
  Calc are each asserted here — the Calc one uses a **hex** transformer deliberately, because `10`
  renders as `3130`, which is itself a plain number, so a Calc reading the rendering would answer
  a wrong number rather than fail visibly.
- **The Value panel gained the column's type** (FR-003 AC3 requires the type to remain available
  there) as well as the transformed rendering beside the raw one.
- **No `GATED_SURFACES` rows.** Nothing here crosses a feature boundary the way SPEC-183's save
  did; `/explore` is gated whole, so a row would assert nothing. The registry's own lesson —
  a row that cannot fail is worse than no row.
- **No Help content.** The arc assigns every guide, including the `dataExplorer` row, to SPEC-185.

## Small things that moved

- **`SELECT_CLASS` was hoisted** into `dataExplorer.constants.ts`; `OrderFilterDialog` and
  `GroupingPanel` each had their own copy, and this spec would have added two more. One string
  until a `Select` primitive exists in `components/` to replace it.
- **`src/test/node-fs.d.ts`** declares the single `readFileSync` overload the palette-drift test
  needs. `tsconfig.app.json` deliberately lists only `vite/client` and `vitest/globals`, and
  adding `"node"` would hand every module in `src/` the whole Node surface to keep a guarantee for
  one test. Vitest resolves a stylesheet `?raw` import — and a raw `import.meta.glob` — to an
  **empty string** (measured), which would have made that test pass by finding nothing.

## What is owed live

**Nothing new.** This spec makes no AWS call and provisions nothing. What a test cannot see is CSS
and gesture, and it all folds into SPEC-185's Safari pass: the two new toolbar controls on an
already-crowded toolbar at 400px, the rules dialog's wrapping rows at both widths, a gradient's
shades against real rendered text, the band boundary rule, and an anchor in a truncating cell.
