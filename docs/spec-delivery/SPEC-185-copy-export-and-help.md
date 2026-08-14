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
- **`docs/testing/data-explorer-e2e.md`** — the arc's live-check script, Safari-named.

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

## What is owed

**Everything in `docs/testing/data-explorer-e2e.md`**, and none of it has been run. The three
assertions nothing offline can make:

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
