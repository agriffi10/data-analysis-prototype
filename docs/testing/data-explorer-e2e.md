# Data Explorer — live check

Manual verification for the Data Explorer arc (SPEC-176 → 185). One session; the sections are in
the order they are cheapest to run, and every one of them starts from a real table.

**Browser: Safari**, at desktop width and again at **400px**. This is not a formality — the arc was
built and tested against Chromium, so a Chromium pass corroborates and cannot discharge. Everything
below that says "observe in the network panel" means Safari's Web Inspector → Network.

> **AMENDED 2026-08-15 (user decision): the Safari requirement is WAIVED for the behavioural
> checks.** The rows marked DISCHARGED below were run in **Chrome** and are accepted as discharged.
> The waiver is deliberate and it is not blanket — it applies to assertions about *what the app
> does* (execution counts, SQL text, refusals), which are engine and app behaviour rather than
> rendering. It does **not** extend to the CSS list at the foot of this file: sticky pinned
> columns, menu clipping, sheet-vs-panel and toolbar wrap are exactly where Safari differs from
> Chromium, so those stay OWED in Safari specifically.

**The one thing that cannot be proved offline is the bill.** Ten specs' worth of unit tests assert
that a description renders to a statement; none of them can prove that applying a filter starts a
NEW execution against Athena and that paging starts none. That is what most of this file is.

| What | Where |
|---|---|
| Route | `/explore` (nav tab **Data Explorer**) |
| Flag | `dataExplorer` in `config/feature-flags.json` |
| Second entry point | **Query** → schema rail → table **⋮** → **Explore data** |
| Athena requests to watch | `StartQueryExecution`, `GetQueryExecution`, `GetQueryResults` |

## Fixture

You need **one table with more than one page of rows** and, for the quoting check, **a text
column holding a value with an apostrophe in it**. The Table Builder is the quickest way there:
upload a CSV to your own space and build a table from the folder.

> **A page is 100 rows, not 25 — so the fixture needs MORE THAN 100.** This file originally said
> ">25", and at 30 rows both pagers render **disabled**: `EXPLORATION_PAGE_SIZE` is `100`
> (`features/data-explorer/dataExplorer.constants.ts`), so §2 below is simply unrunnable on a
> 30-row table. Measured 2026-08-15. Size the fixture at **150 rows** and the other sections are
> unaffected — nothing else here depends on the row count.

**The fixture is committed: `docs/testing/fixtures/explorer-fixture-150.csv`.** 150 rows (so page 2
holds 50), nine `O'Brien` rows, two empty `qty` cells, LF line endings. Upload it into a **new empty
folder** — the Table Builder builds from a whole folder, and inference reads only the first key in
listing order, so a second CSV beside it changes what the table becomes.

> **Generate it with LF endings if you ever rebuild it.** Python's `csv.writer` defaults to CRLF,
> which puts a trailing `\r` on every `qty` value in the built table and quietly breaks the numeric
> filter checks. Pass `lineterminator="\n"`.

The shape, for reference — the first rows of that file:

```csv
id,region,owner,qty
1,north,O'Brien,10
2,south,Smith,20
3,north,O'Brien,
...
```

Leave at least one `qty` cell **empty** in the CSV. The Table Builder makes CSV columns all-string,
so that arrives as an empty string, not a NULL — which is the pair SPEC-180 FR-003 is about, and
worth seeing on screen once.

> **The upload goes through the portal, not the CLI** — a laptop IAM user cannot write
> `dat-prod-user-space` (the bucket policy allowlists the portal, deploy and execution roles only).
> It does **not** have to be done by hand: the Chrome extension's `file_upload` drops a local file
> straight into the portal's own `<input type=file>`, so the write is made by the portal role like
> any other. That is how this fixture, and the SPEC-186 FR-006 partitioned one, were loaded on
> 2026-08-16.

---

## SPEC-179 — the route, the picker and the deep link

1. Open **Data Explorer**. The picker lists **Space** and, under it, tables and views.
2. Pick your own space and the fixture table. A tab opens named for the table.
3. Go to **Query**, open the schema rail, and use a table's **⋮** → **Explore data**. It lands on
   `/explore` with that table open.
4. Note the URL while it does: it carries `?space=&db=&table=`, and after the tab opens the
   parameters are **dropped**. Reload the page — you get the tabs you had, **not** a second copy of
   the linked table.
5. Paste a link naming a shared space you are **not** a member of:
   `/explore?space=<some-other-space>&db=<x>&table=<y>`. Expect the refusal page ("You don't have
   access to that space") **and no Glue or Athena request at all** in the network panel. That
   negative is the check — SPEC-113's rule is that the page must not become an existence oracle.

**Shared-space pass.** Repeat steps 1–2 choosing a shared space you belong to, as a **non-owner
member**. The database is the space's own name; the rows come back. This is the half no unit test
reaches, because it runs against real Cognito tags and real Lake Formation.

---

## SPEC-178 / SPEC-181 — the bill, and the thing only Athena can settle

**This is the load-bearing section.** Keep the network panel open and filtered on `athena`
throughout, and count requests rather than trusting the grid.

### 1. An apply is a NEW execution, with a NEW bytes-scanned figure

1. With the table open, note the line at the bottom: `This query scanned N` and
   `M scanned by this exploration`.
2. Apply a filter that removes most rows — column **⌄** → **is** → a common value.
3. Expect in the panel: **one** `StartQueryExecution`, then `GetQueryExecution` polls, then
   `GetQueryResults`.
4. Expect the bottom line to show a **different** scanned figure.

**Record the two figures.** "The grid changed" is not the assertion — a client-side filter would
also change the grid. The assertions are the request and the changed number.

### 2. Paging produces NONE

1. Click **Next** on the pager, then **Prev**, then **Next** again.
2. Expect **zero** `StartQueryExecution`. `GetQueryResults` calls are expected and are free — the
   `NextToken` walk scans no additional bytes.
3. The bottom line's total must not move.

> **A query that outlives the poll guard now looks different, and neither shape self-heals.**
> Results are read only at `SUCCEEDED` (fixed 2026-08-15 — before that they were read against a
> QUEUED execution, which is a 400 the app showed as "Contact the Administrator"). `MAX_POLL_
> DURATION_MS` is **5 minutes** and `refetchOnWindowFocus` is off, so an execution still running
> after that renders an indefinite **"Running…"** with no banner and no re-attach affordance —
> where it previously produced a permanent, wrong error banner. If you can stage a >5-minute
> query, record what it looks like; the behaviour is not specified anywhere yet.

### 3. Changing a filter back is a CACHE HIT

1. Clear the filter you applied, then apply the **same** filter again.
2. Expect **no** new `StartQueryExecution` for the repeat, and the bottom line to read
   **"Loaded from an earlier run in this tab — nothing more scanned"**.
3. The running total must be **unchanged**.

This is SPEC-178's `staleTime`/`gcTime: Infinity` working. If a new execution appears, the cache
entry was collected and the decision's own reasoning has been broken.

### 4. A value containing a single quote filters CORRECTLY against the real engine

**No unit test can settle this**, and it is the one place a wrong escaper fails *silently*: the
TypeScript DML escaper doubles the quote (`O''Brien`), the DDL escaper backslashes it, and the wrong
one produces a predicate Athena accepts and that matches **nothing**.

1. Click a cell holding `O'Brien` and use **Filter by this value**.
2. Expect rows back — every `O'Brien` row, not an empty grid.
3. Open **Generated SQL** and confirm the predicate reads `WHERE "owner" = 'O''Brien'`.
4. An empty result here is a **FAILURE**, not an empty table. Cross-check by counting the
   `O'Brien` rows in the unfiltered grid first.

### 5. A failed apply keeps the rows and the toolbar

1. Type nonsense into **Filter expression** (e.g. `qty >>> 5`) and click **Apply expression**.
2. Expect an error banner, the **previous** rows still on screen beneath it, and the toolbar and
   expression bar still there to correct it with.
3. Step **back** with the history arrow. Expect the good rows, and **no** re-run of the failed
   statement. Then step forward onto the failed one: expect "This set of filters failed last time
   it ran. Nothing has been run." and a **Run it anyway** button — and confirm in the panel that
   arriving there started **no** execution.

> **The suspended state is PER-MOUNT, and that is accepted rather than a defect (decided
> 2026-08-15).** The set of known-failed statements is a `useRef` in `useExplorationQuery`, so it
> dies when the route unmounts. Leave `/explore` for another nav tab and come back, and the
> statement is submitted again and you get the error banner rather than "Nothing has been run".
> **Do not report this as a bug.** The promise is scoped to history navigation, which is what
> step 3 tests; the banner you get instead is truthful; and persisting the set would put a second
> writer on the tab's `sessionStorage` key that SPEC-181 deliberately kept to one. Option B
> (persist with the tab) was considered and declined.
>
> **On cost, precisely:** for the case step 1 stages — `qty >>> 5`, a parse error — Athena rejects
> the statement **at `StartQueryExecution`**, so no execution is created and nothing is billed. That
> is **not** true of every statement the set holds: `noteFailure` records any `exploration.error`,
> including a **FAILED or CANCELLED poll**, which did create an execution — and a CANCELLED query is
> billed for what it scanned. So the re-run is free for the syntax-error class and not in general.
>
> **You will see TWO `StartQueryExecution` calls for one failing apply, ~1.1 s apart. That is
> `retry: 1`** in `lib/queryClient.ts`, not a double-subscribe — verified by applying once with no
> navigation and watching it stop at exactly two. Count executions for the checks above on a
> statement that SUCCEEDS, or subtract the retry.

---

## SPEC-182 — grouping runs, Calc does not

1. Open **Grouping**, group by `region`, aggregate `COUNT(*)`, tick **Show percentage**, **Apply**.
2. Expect **one** `StartQueryExecution` and a changed scanned figure.
3. Open **Generated SQL**. Confirm it is a real `GROUP BY` over the source table and that
   **the percentage column is not in it** — it is computed in the browser, and its header says
   `(this page)`.
4. **Confirm the disclosed SQL is what Athena ran**: copy the statement out of the disclosure and
   compare it to the `QueryString` on the `StartQueryExecution` request in the network panel. They
   must be byte-identical. (SPEC-182 passes the executed string down rather than re-rendering, and
   this is the only check that proves the two have not drifted.)
5. Drag across a dozen cells in a numeric column and open **Calc**. Expect the aggregates, the line
   `N selected cells on this page`, and — the assertion — **zero** Athena requests while selecting,
   re-selecting and changing which functions are shown.
6. Leave grouping (clear it) and confirm any sort you had on `count_all` is dropped rather than
   carried onto the raw table.

---

## SPEC-183 / SPEC-185 — the round trip through `saved_queries/`

1. With a filtered, ordered exploration on screen, click **Save as query**, name it
   `explorer-roundtrip`, choose **My files**, save.
2. In **Files**, browse to `saved_queries/`. Expect `explorer-roundtrip.sql`, and expect the folder
   itself to refuse **Delete** and **Rename**.
3. Go to **Query** → **Saved queries** → open `explorer-roundtrip`. Expect the editor to hold the
   **rendered** statement — the filters and the ORDER BY, not a bare `SELECT *`. Run it; expect the
   same rows the Explorer showed.
4. **And the other direction**: save a query from the Query workspace into the same folder, then
   confirm it is loadable there. (It does **not** open in the Explorer — a saved exploration is its
   SQL, and loading a `.sql` file as an exploration source is descoped. Confirming the Explorer
   offers no such affordance IS the check.)
5. Repeat step 1 choosing a **shared space** as the destination. Expect the write to succeed
   cross-bucket and the file to appear in that space's `saved_queries/`.

---

## SPEC-185 — copy and export

1. Select a rectangle, press **⌘C**, paste into a spreadsheet. Expect the cells in grid order, and
   a `NULL` where the grid showed NULL.
2. **⌘-click** two non-adjacent cells, copy, paste. Expect the **bounding rectangle** with the cells
   in between blank — the behaviour the dialog states.
3. Click a **column header**, copy, paste. Expect the loaded page's rows only.
4. Open **Copy…**, choose **JSON**, copy, paste into a text editor. Expect `null` for the NULL and
   `""` for the empty cell — distinguishable, which is the point.
5. Click **Export** before anything has finished running: expect it refused, with the reason on
   hover **and reachable by keyboard** — it is `aria-disabled`, so Tab reaches it.

   > **No need to "be quick", and this file used to say so.** `exportRefusal` comes from
   > `exploration.outputLocation`, which `useExploration` populates **only at `SUCCEEDED`** — so
   > "nothing has run yet" and "still running" are one state. Opening any tab and reading the button
   > before the first result lands is enough; measured 2026-08-16, where it read
   > `aria-disabled="true"`, `disabled` **false**, `tabIndex 0`, *"Run a query first — export saves
   > the results Athena returned."*
6. Once rows are on screen, **Export** → name it `explorer-export` → **My files** → **Save here**.
   Expect a success toast and, in **Files**, `explorer-export.csv`.
7. **Open the exported CSV and count its rows.** It must hold the **whole** result — every row the
   filtered query returned, not the **100** on the page (`EXPLORATION_PAGE_SIZE`). That is what
   makes export the result-shaped tool and copy the selection-shaped one. A laptop identity cannot
   read the bucket, so open it through the portal: Details → Download.
8. Confirm in the network panel that steps 1–7 started **zero** `StartQueryExecution`.
9. Export again with the same name. Expect the **Overwrite** confirm before anything is replaced.
10. Export into a **shared space**. Expect the cross-bucket copy to succeed.

---

## SPEC-185 — Help

1. Open **Help & guides**. Expect a **Data Explorer** section with five guides.
2. Read the filtering guide's callout and confirm it says plainly that each apply runs against
   Athena and scans data. This is the one thing a user cannot infer from the UI.
3. Confirm nothing there promises a chart, cell editing, named filters, a References panel, or
   loading a `.sql` file back into the Explorer.

---

## The 400px and Safari pass (SPEC-185 FR-004, and every spec's CSS)

Run the whole of the above at **400px in Safari**. What only a real browser can show:

- The **sticky pinned column block** — pin a column, scroll right, confirm it stays put and that its
  background is opaque over the scrolling cells.
- The **header menu inside the grid's scroll container** — at desktop, open a column **⌄** near the
  right edge and confirm the menu is not clipped.
- **Below `tablet` the header menu is unreachable**, by design. **Order and filter** is the way in;
  confirm every sort and filter can be set from that dialog alone, and that it fits at 400px.
- The **Value panel** renders as a sheet rather than a side panel.
- **Calc and Grouping stack below the grid** rather than beside it.
- The **toolbar's controls** wrap rather than overflow. There are **17** of them as of 2026-08-16
  (Back, Forward, Order and filter, Remove all filters, Filter by this value, Grid, Record, Text,
  Columns, Colours, Transformers, Value, Calc, Grouping, Copy…, Export, Save as query) — this file
  said "fourteen", which predates SPEC-184 and SPEC-185. Count them rather than trusting either
  number.
- The **Colours** rules dialog's rows wrap, and a gradient's shades are readable against real
  rendered text (the contrast maths is asserted in tests; how it *looks* is not).
- A **band boundary** rule is visible where two striping groups meet.
- An **anchor in a truncating cell** (URL transformer) does not push the cell's layout around.
- The **header-drag-onto-the-Grouping-panel** gesture, which no test performs.
- **Record view is the default** on an unchosen tab at this width.

---

## Owed, and why

**Two sessions, and the rows below name which.** Rows dated **2026-08-15** were run in Chrome at
1400px against `agriffith_three.explorer_fixture` (30 rows) — evidence
`2026-08-15-data-explorer-live-check.md`. Rows dated **2026-08-16** were run in Chrome at 1512px
against `agriffith_three.explorer150` (the 150-row fixture) — evidence
`2026-08-16-live-check-session.md`. Undated rows are from the 2026-08-15 session.

Executions were counted by patching `window.fetch` and reading the `x-amz-target` header — the
network panel reports only URL and status, which cannot separate `StartQueryExecution` from a poll.
The 2026-08-16 session ran **three** instruments: that fetch patch (widened to record non-GET S3
requests by path), a `navigator.clipboard.writeText` patch to capture what a copy actually wrote,
and the `visibilityState` override described below — record any instrument you add, because each
one is a way the run differs from a user's.

> **A Chrome window hidden at the OS level pauses the polling, and it is indistinguishable from a
> hung query** (measured 2026-08-16). Opening a table sat on **"Running…"** for 35 s having issued
> exactly ONE `GetQueryExecution` 254 ms after the start: `document.hasFocus()` was `true` while
> `document.visibilityState` was **`hidden`**, and TanStack Query's focus manager suspends
> `refetchInterval` on that. Override `visibilityState`/`hidden` to visible, dispatch
> `visibilitychange`, and the poll resumes. **This is not the app defect the §2 note below invites
> you to record** — a real tab fires `visibilitychange` on return — but it wears the same face, so
> establish which one you are looking at before filing anything.

| Check | Status |
|---|---|
| SPEC-179 steps 1–2 (picker lists spaces, a tab opens) | **DISCHARGED** |
| SPEC-179 deep-link refusal + **zero Glue/Athena** | **DISCHARGED** |
| §1 An apply is a NEW execution with a NEW figure | **DISCHARGED** — 1 exec, 568 B → 1.1 KB |
| §3 Cache hit, both directions | **DISCHARGED** — 0 execs, total held |
| §4 The `sqlLiteral` path (`O''Brien`) | **DISCHARGED** — was PROXIED ONLY |
| §5 Failed apply, history back, suspended forward | **DISCHARGED** — 0 execs on both steps |
| SPEC-182 grouping, and the % absent from the SQL | **DISCHARGED** — 1 exec, counts verified |
| SPEC-182 step 4, disclosed SQL = `QueryString` | **DISCHARGED** — byte-identical; was PROXIED ONLY |
| SPEC-182 Calc issues nothing | **DISCHARGED** — 0 Athena requests |
| SPEC-182 step 5's wording (`N selected cells on this page`) | **DISCHARGED** — read as "4 selected cells on this page", then "3" |
| SPEC-182 step 6, the `count_all` sort is dropped | **DISCHARGED** |
| SPEC-183 save — exactly one `PutObject` | **DISCHARGED** — 1 PUT after a HEAD on the exact key |
| SPEC-183 round trip — reopens as RENDERED SQL | **DISCHARGED** |
| **§2 Paging produces NONE** | **DISCHARGED** (2026-08-16) — 0 execs over Next/Prev/Next, total held |
| SPEC-179 steps 3–4 (*Explore data*, params dropped, reload) | **DISCHARGED** (2026-08-16) — `push ?space&db&table` then `replace` with none; reload gave the same tabs |
| SPEC-179 shared-space pass as a **non-owner member** | **OWED** — needs a second account |
| SPEC-183 steps 4–5 (other direction, shared destination) | **DISCHARGED** (2026-08-16) — both directions, and the shared write is cross-bucket |
| SPEC-185 copy and export | **DISCHARGED** (2026-08-16) — all ten steps; the export held 150 rows to the page's 100 |
| SPEC-185 Help | **DISCHARGED** (2026-08-16) — five guides, the Athena callout, none of the three promises |
| The 400px pass | **OWED** — see below |
| SPEC-180 → 184 infra/IAM | **N/A** — those specs add no AWS call the app did not already make |
| FR-005 AC4's COPY assertion (SPEC-184) | **DISCHARGED offline** by `copyExport.test.tsx` — copy reads the raw row |

> **400px is not reachable by window resize on macOS.** Chrome's minimum window width is **606px**,
> and the Claude-in-Chrome extension refuses page-zoom shortcuts, so neither route gets there. Use
> DevTools device toolbar (⌘⇧M) at 400px — emulation changes the viewport the page actually sees.
>
> **And `resize_window` REPORTS SUCCESS while changing nothing the page can see** (measured
> 2026-08-16). Asked for 400×800 it answered *"Successfully resized window … to 400x800"*, moved
> `outerWidth`, and left `innerWidth`, `documentElement.clientWidth` and every media query at the
> 1512px desktop values — `min-width:1300px` still matched. That is worse than the 606px floor,
> where the layout at least genuinely changed: here a checker reading the tool's own success
> message would record a narrow pass that never happened. **Assert on `matchMedia`, never on the
> resize call.**
> **At 606px only two things were observed** — the below-`tablet` layout is genuinely active
> (hamburger nav, stacked file toolbar), and `CreateFolderDialog` renders 392px wide, centred, with
> no horizontal page scroll. **Nothing on the CSS list below was exercised at any narrow width**, so
> that list is owed in full. Details in `2026-08-15-data-explorer-live-check.md`.

Record outcomes in a dated session file under `docs/testing/`, as
`2026-08-14-live-check-session.md` does, and discharge only what was actually **run**.
