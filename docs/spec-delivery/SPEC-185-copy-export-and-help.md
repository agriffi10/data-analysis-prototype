# Completed Spec — SPEC-185: Copy, Export, Help and the Arc's Live Checks

## What was completed?

The two ways out of the Data Explorer, the Help content for the whole feature, and the arc's
live-check script — plus the completion ritual for SPEC-176 → 185.

- **`renderCopy.ts`** — a pure selection→text renderer over six formats (`tsv`, `csv`, `json`,
  `markdown`, `sql`, `xml`), with the raw-value rule, the NULL/empty-string rule and the
  bounding-rectangle rule. **`AdvancedCopyDialog`** stages the format and the three toggles;
  Ctrl/Cmd+C on the grid is the plain tab-delimited copy.
- **`ExportExplorationDialog`** — the Query workspace's own destination picker and overwrite
  confirm, over `useSaveResults`, copying the **execution's results object** so a filtered, ordered
  or grouped exploration exports every row with no second query.
- **`useSaveResults`, `SaveResultsDialog` and `normalizeCsvName` moved to `features/catalog/`**,
  bodies untouched; `features/query/query.format.ts` is gone (it held nothing else).
- **A `data-explorer` Help section** with five guides, a new `HelpSectionId` and a new
  `HelpIconName`, all six registered under `dataExplorer`.
- **The arc's live-check script**, Safari-named — folded into `docs/testing/e2e.md` §4.5 on
  2026-08-18.

No infra, no IAM, no new AWS call. Export's `CopyObject` is the one the Query workspace has issued
since SPEC-049.

## The decisions worth carrying

Full entries in `docs/decisions.md` → *Copy is the selection-shaped tool and export is the
result-shaped one (SPEC-185)*. The three that reach outside this spec:

### Reusing `useSaveResults` required moving it, and the move closed a live defect

The spec listed "any change to `useSaveResults` beyond its call site" as out of scope, on a reading
of *change* that a relocation does not meet — and reuse was **unreachable** without one, since the
hook sat in `features/query/` and this feature may not import it. It went down to
`features/catalog/`, which is the layer SPEC-176 and SPEC-177 exist to take modules through.

One field did change. The hook built its destination list from an **unfiltered** `useQuerySpaces()`
while every saved-query surface beside it used a view-gated one, so with `sharedWorkspaces` off the
Query workspace's Save-results dialog had been offering a colleague's space as a **write target** —
unregistered and unnoticed since SPEC-055. Destinations are now a parameter (SPEC-174's shape), both
views gate them, and both instances have a `GATED_SURFACES` row. Fixing it in this branch was the
user's call.

### The walking test's guide recipe worked by coincidence

Every guide row before this spec lived in `files`, the section the Help page opens on — so the
recipe queried a guide card **without selecting its section**, and a row anywhere else would have
returned `null` in *both* flag states and read as correctly hidden. It now selects the owning
section first, returning null only when the section itself is gated away. Two smaller harness fixes
fell out: the file's Query recipes were mounting real Monaco (the stale "mobile, so Monaco never
mounts" comment was wrong at jsdom's 1024px default) and only survived because none of them lived
long enough for the lazy chunk to resolve, and `getQueryResults` was mocked with **no columns**,
which hid the Save-results button behind `canSaveResults`.

### Copy and export divide on the arc's own line, and both say so

Copy takes the **selection**, which exists only in the browser; export takes the **execution's
results object**, which is the only thing holding every row. That is why exporting a *selection* is
out of scope rather than unbuilt — it would need a second query or a re-serialization of rows that
are not all loaded — and why the copy dialog states that only the loaded page travels and points at
Export for the rest.

## What review changed

A fresh-context review found nine things; six were fixed and three accepted with reasons.

- **The advanced-copy success toast could lie.** `useCopyToClipboard` swallows a refused write,
  which is safe for a caller whose confirmation is its `copied` flag and false for one that closes
  its dialog and announces success separately. `copy` now **returns the outcome**, and both copy
  paths report a refusal — the plain Ctrl/Cmd+C included, because the grid suppresses the browser's
  own copy and a silent failure leaves the previous clipboard contents in place.
- **`renderCopy` had a second identifier quoter** written out inline while importing `sqlLiteral`
  from the same module — the duplication SPEC-178's one-builder rule exists to prevent, agreeing
  byte-for-byte today. It uses `sqlIdentifier` now.
- **The XML JSDoc claimed something false**: `<cell/>` and `<cell></cell>` are the same element to
  every parser, so a hole is *not* distinguishable from an empty string there — the same ambiguity
  JSON has, and now stated as such. The test that pinned the serialization is replaced by one that
  parses the output and asserts what a consumer can observe (the NULL marker, which is what AC4
  actually asks for).
- **Markdown leaked the row-number header** with column names off, where every other format drops
  it.
- **The Ctrl/Cmd+C intercept was case-sensitive**, so Caps Lock fell through to the browser's own
  copy — the exact outcome the intercept exists to prevent. It folds case, as the sibling
  Ctrl/Cmd+A handler already did.
- **A range lying entirely off the loaded page stretched the rectangle** to meet it, padding the
  copy with blank rows nobody selected. It now contributes nothing on either axis.
- **The inert quoting checkbox used `disabled`**, against SPEC-172's fleet-wide rule — it is
  `aria-disabled` with `aria-describedby` now, so the control keeps its place in the tab order and
  the reason is announced with it. Both new dialogs gained axe assertions, driven into the open
  state.

Accepted rather than fixed: JSON's duplicate-column collapse (guarded upstream by
`groupingNameCollision`), `ExportExplorationDialog` inheriting the Query workspace's
`spaces.length > 0` guard (unreachable, and FR-002 AC2 asks for that path unchanged), and the five
guide rows not failing independently of their section row — the `files` precedent, recorded in the
registry's own comment.

**One acceptance criterion is unverifiable as written.** FR-003 AC3 says a gated guide "leaves both
the Help list and the search index"; there is no help search in the app, and `HELP_SECTIONS` has no
consumer beyond `HelpPage` and its tests. The list half is asserted.

## What is owed

**Everything the arc's live-check script listed**, and none of it had been run at the time of
writing. Most of it was discharged on 2026-08-15 and 2026-08-16 — see `docs/testing/owed.md`. The three
assertions nothing offline can make:

> **SUPERSEDED 2026-08-15.** Twelve rows are now discharged, including **all three** assertions
> below — an apply is a new execution while a cache hit issues zero, `O'Brien` filters correctly
> (`'O''Brien'`), and the disclosed SQL is byte-identical to the `QueryString` Athena received.
> **Paging was the exception and is now DISCHARGED (2026-08-16)** against a 150-row fixture, along
> with this spec's own copy/export (all ten steps — the exported CSV held 150 rows to the page's
> 100) and Help. `EXPLORATION_PAGE_SIZE` is 100, which is why the script's ">25 rows" fixture could
> never page. Safari is waived for the behavioural checks by user decision
> and **retained for the CSS list** — the sticky block, menu clipping, panel stacking, toolbar wrap
> and header-drag below are all still owed, and so is the 400px pass. See this script's own
> *Owed, and why* table, and the 2026-08-15 and 2026-08-16 sections of
> `docs/testing/sessions.md`.

1. **A filter apply is a new execution with a changed bytes-scanned figure, and paging is none** —
   observed in the network panel, never inferred from the grid.
2. **A value containing a single quote filters correctly against the real engine** — the
   `sqlLiteral` path. The wrong escaper fails *silently*, as a predicate that matches nothing.
3. **The disclosed SQL is byte-identical to the `QueryString` Athena received** — one call away in
   code, and believed until someone compares them.

Plus the **Safari pass at 400px and desktop**, which is the only thing that can see the sticky
pinned block, the header menu's clipping, the two panels stacking, the toolbar's fourteen controls
wrapping, and the header-drag-onto-the-Grouping-panel gesture no test performs.

FR-005 AC4's COPY assertion from SPEC-184 is **discharged offline** — `copyExport.test.tsx` proves
copy reads the raw row, using a hex transformer on SPEC-182's precedent because a URL transformer
keeps the raw value as its link text and the assertion could not have failed.

## Help & guides

Five guides added under a new **Data Explorer** section, documenting only shipped, wired behaviour.
They say plainly the one thing the UI cannot: **every filter and sort runs a real query against
Athena and scans data**, and the figures at the bottom are the cost signal. Nothing excluded from
the arc is documented — no chart, no editing, no named filters, no References panel — and the
save guide states that a saved exploration **reopens in the Query workspace as SQL**, not back here
as an exploration, because SPEC-183 descoped the loading half.
