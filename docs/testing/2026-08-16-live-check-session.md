# Live-check session — 2026-08-16 (Data Explorer §2 + copy/export, SPEC-179/183, partitioned refresh, saved queries)

Run against deployed prod (`d1kbh4bnvh1je8.cloudfront.net`, `main` at `94c892b`) as
`agriffith_three`, in **Chrome at 1512×786**. Safari waived for behavioural checks by the
2026-08-15 user decision at the head of `data-explorer-e2e.md`; the CSS list is untouched here.

**Nothing was found broken.** Every check below passed. The two findings at the foot are about the
*instrument*, not the app — and one of them would have let a future session record a pass it never
ran.

## The upload constraint is gone, and it is what unblocked most of this

`data-explorer-e2e.md` says *"Andrew has to do the upload"* because a laptop IAM user cannot write
`dat-prod-user-space`. That is still true of the CLI, but it is **not** a limit on a live-check
session: the Chrome extension's `file_upload` puts a local file straight into the portal's own
`<input type=file>`, so the upload goes through the **portal role** like any other. Everything
below that needed a fixture — the 150-row table, the partitioned table, the added-column file —
was uploaded that way.

## Data Explorer (`data-explorer-e2e.md`)

Fixture `agriffith_three.explorer150`, built from the committed
`docs/testing/fixtures/explorer-fixture-150.csv` in a new empty folder: 150 rows, `id/region/owner/qty`
all string, nine `O'Brien` rows, two empty `qty` cells. Executions were counted by patching
`window.fetch` and reading `x-amz-target`, as on 2026-08-15.

| Check | Executions | Result |
|---|---|---|
| **§2 paging produces NONE** — Next, Prev, Next | **0** `StartQueryExecution` | PASS — rows 1–100 → 101–150 → back → 101–150, one `GetQueryResults` for the uncached page, total held at **2.9 KB** |
| SPEC-179 step 3 — Query rail ⋮ → *Explore data* | — | PASS — lands on `/explore` with that table open |
| SPEC-179 step 4 — params carried then dropped | — | PASS — `push /explore?space&db&table`, then `replace /explore` with **no** params |
| SPEC-179 step 4 — reload | — | PASS — the 2 tabs I had, **not** a third copy of the linked table |
| SPEC-183 step 4 — save from the Query workspace | 1 PUT | PASS — `workspace-direction` saved to My files, reopened from **Saved queries** with its exact SQL |
| SPEC-183 step 4 — the Explorer offers no way back | — | PASS — the toolbar's 17 controls include *Save as query* and **no** load/open affordance |
| SPEC-183 step 5 — save into a **shared space** | 1 PUT (cross-bucket) | PASS — see below |

**SPEC-183 step 5 in full, because it took two attempts.** The first save (*Save as query* from the
`explorer150` tab, destination `livecheck_186`) wrote `explorer-shared-dest.sql` — a HEAD on the
exact key then one cross-bucket PUT, plus a HEAD+PUT that created `saved_queries/DO_NOT_DELETE.txt`
in that space, and the toast *Saved "explorer-shared-dest" to livecheck_186.* **But the exploration
was unfiltered**, and the step says *"repeat step 1"* — a filtered, ordered exploration. Its **45 B**
body is the tell. So it was repeated properly: *Filter by this value* on `region = west` (1
execution, rows 1–37, 2.9 KB), then *Save as query* → `livecheck_186`. The listing then held
`explorer-shared-dest.sql` **45 B** beside `explorer-shared-filtered.sql` **69 B** — the 24 bytes
being the `WHERE`, which is what "the rendered SQL, not a bare `SELECT *`" looks like from the
outside.

Two incidentals from that: the Save dialog **pre-fills the last name used** and the field is not
selected on focus, so a straight `type` appends (this produced
`explorer-shared-destexplorer-shared-filtered.sql`, renamed afterwards) — and the rename itself
confirms the SPEC-173 pairing, that a `.sql` file **inside** `saved_queries/` is ordinary while the
folder is not.

### SPEC-185 copy and export

Copy was read by patching `navigator.clipboard.writeText` and recording what the app wrote — the
payload itself, rather than a paste into a spreadsheet.

| Step | Result |
|---|---|
| 1. Rectangle, ⌘C | PASS — `1\tsouth\tJones` / `2\teast\tNakamura`, grid order |
| 1. NULL vs empty | PASS — `796\t796` then `\tNULL`: the empty cell copies empty, the NULL copies as `NULL` |
| 2. ⌘-click two non-adjacent cells | PASS — exactly the bounding rectangle: `1\t\t` / `\t\t` / `\t\tO'Brien` |
| 3. Column header | PASS — **100** rows (1…100), one column, **0** executions — the loaded page, not the table |
| 4. **Copy… → JSON** | PASS — `"qty": ""` beside `"qty_null": null`, distinguishable |
| 5. Export before anything has run | PASS — `aria-disabled="true"`, `disabled` **false**, `tabIndex 0`, reason *"Run a query first — export saves the results Athena returned."* |
| 6. Export → `explorer-export` → My files | PASS — one HEAD then one PUT, success toast, **0** executions |
| 7. **Row count in the exported CSV** | PASS — **151 lines** = header + all **150** rows, header `"id","region","owner","qty"`, last row `id 150`, while the page held 100 |
| 8. Zero executions across 1–7 | PASS — asserted per step; the running total never left 2.9 KB |
| 9. Export again, same name | PASS — *Overwrite "explorer-export.csv"?* before anything was replaced |
| 10. Export into a shared space | PASS — cross-bucket HEAD+PUT, and `explorer-export-shared.csv` (4.1 KB) is in `livecheck_186` |

**How step 7 read the file, since a laptop identity cannot.** `dat-prod-user-space` is closed to the
IAM user, so the object was opened the way a user would: Details → **Download** in the file browser,
with `window.open` and `HTMLAnchorElement.prototype.click` patched to capture the presigned URL, and
the fetch + line count done **inside the page** so the URL itself never left the browser.

**Step 4 needed a NULL and the CSV fixture has none** — the Table Builder makes CSV columns
all-string, so an empty cell is `''` and never SQL NULL. A view supplies one:

```sql
CREATE VIEW agriffith_three.explorer150_nulls AS
SELECT id, region, owner, qty, NULLIF(qty, '') AS qty_null FROM agriffith_three.explorer150
```

Row 7 then renders *(empty)* in `qty` and *NULL* in `qty_null` side by side, which is SPEC-180
FR-003 visible on screen and the pair steps 1 and 4 are actually about.

### SPEC-185 Help

PASS, all three steps. The **Data Explorer** section carries **five** guides. The filtering guide's
callout reads *"Careful. Every apply runs a real query against Athena and scans data, which is what
it costs."* Nothing in the section mentions a chart, a graph, cell editing, named filters or a
References panel, and the save guide states plainly that a saved exploration opens in the Query tab
as SQL rather than back in the Explorer.

## Table Builder — the partitioned refresh variant (`table-builder-e2e.md`)

The owed partitioned twin of the FR-010 add/remove sequence. Fixture `agriffith_three.partfix` over
`partfix/year=2025/part1.csv` + `partfix/year=2026/part2.csv`, declared partition key `year`
(string, values `2025, 2026`).

| Step | Result |
|---|---|
| Create — partition projection | PASS — `SELECT * … WHERE year = '2025' LIMIT 5` returned rows, 122 B, **no** load step |
| 1–2. Upload `year=2025/part0.csv` (`id,region,amount,channel`), Refresh | PASS — *Table "partfix" was refreshed in "agriffith_three": **1 column added**.*; rail reads `id, region, amount, channel` |
| **Partition key survives the refresh** | PASS — the same partition-filtered SELECT still returns rows, now with `channel` **and** `year` |
| 3. Delete `part0.csv`, refresh with **no** opt-in | PASS — *Couldn't refresh table "partfix": these columns are no longer in the data and would be removed: **channel**. Nothing was changed…* |
| 4. Follow the notification link | PASS — `/query?refreshTable=…&removed=channel`; the dialog opens **pre-armed** ("A previous refresh was stopped… channel"), opt-in **unchecked**, and *Refresh table* is `aria-disabled="true"` / `disabled` **false** / `tabIndex 0` with *"Tick "Allow columns to be removed" to refresh this table."* |
| 5. Tick the opt-in and submit | PASS — *1 column removed* |
| After the removal | PASS — partition filter still works, `year` still projected, `channel` gone |

`part0.csv` is the load-bearing name: it sorts first **within the first partition**, so it is the
first key in the whole listing and therefore the inference sample.

## Saved queries (`saved-queries-e2e.md`) — check 1, the owed SHARED half

PASS, byte-exact, with its control. In `livecheck_186` (whose `saved_queries/` folder the SPEC-183
step-5 save had just created):

- Delete — `aria-disabled="true"`, `disabled` **false**, `tabIndex 0`,
  `Saved queries live in this folder, so it can’t be deleted.`
- Move — same, `Saved queries live in this folder, so it can’t be moved or renamed.`
- Clicking Delete opened **zero** dialogs and **zero** alertdialogs, and — with `window.fetch`
  patched to record every request by method and path — issued **zero requests of any kind**. That
  is step 3's third clause, *"no request is sent"*, observed for the shared case directly rather
  than inherited from the 2026-08-14 trace (which watched the pre-FR-002 behaviour and does not
  carry).
- **Control:** an ordinary `marker_control` folder beside it showed both controls with no
  `aria-disabled` and no reason, its confirm opened (*"…and everything inside it? … This can't be
  undone."*), and it deleted cleanly.

The 2026-08-15 personal half stands; check 2 (the bucket-policy Deny, CLI-only) is still owed.

## Findings — both about the instrument

**1. A Chrome window that is hidden at the OS level pauses the polling, and it looks exactly like a
hung query.** Opening a table sat on **"Running…"** for 35 s having issued exactly **one**
`GetQueryExecution`, 254 ms after the start. `document.hasFocus()` was `true` while
`document.visibilityState` was **`hidden`**, and TanStack Query's focus manager suspends
`refetchInterval` on that. Overriding `visibilityState`/`hidden` to visible and dispatching
`visibilitychange` resumed the poll and the rows arrived in seconds. **This is not an app defect** —
a real user's tab fires `visibilitychange` on return and the poll resumes — but a session that does
not know it will file the app's own >5-minute "Running…" note as a live bug. Every check above was
run with that override in place.

**2. `resize_window` reports success, moves `outerWidth`, and does NOT change the viewport the page
sees.** Asked for 400×800 it answered *"Successfully resized window … to 400x800"* while
`innerWidth`, `documentElement.clientWidth` and every media query stayed at the 1512px desktop
values (`min-width:1300px` still matching). So the tool cannot stage a narrow pass at all — this is
stronger than 2026-08-15's "Chrome's minimum is 606px", because there the layout genuinely changed
and here **nothing does while the call reports success**. The 400px pass stays **owed in full** and
needs DevTools device emulation.

Also worth carrying: the refresh dialog is `role="alertdialog"`, not `dialog`, so a
`querySelector('[role="dialog"]')` finds nothing there — the mirror of the `Drawer` trap recorded
on 2026-08-15.

## Still owed after this session

- The **400px** pass and the **Safari** CSS list (`data-explorer-e2e.md`).
- SPEC-179's shared-space pass as a **non-owner member**, and SPEC-186 FR-008's
  add → acknowledge → roster re-run — both need a second account.
- `saved-queries-e2e.md` **check 2** (bucket-policy Deny, CLI + portal-role credentials).
- SPEC-157's refresh lock, SPEC-149's `Description`/comment preservation read-back (needs the
  verification role, deliberately not created), and `SaveQueryDialog`'s "nowhere to save" width.
- The whole **archive/restore** arc (`archive-restore-e2e.md`). Deliberately not attempted here:
  archiving removes files from a space and a restore is a 3–5 hour **billed, uncancellable**
  Glacier retrieval, which is not a call to make unattended.

## Fixtures created (deletable once the remaining checks are run)

`agriffith_three`: `explorer150/` + table `explorer150`, view `explorer150_nulls`, `partfix/`
(`year=2025/`, `year=2026/`) + table `partfix`, `explorer-export.csv`,
`saved_queries/workspace-direction.sql`.
`livecheck_186`: `explorer-export-shared.csv`, `saved_queries/explorer-shared-dest.sql` and
`saved_queries/explorer-shared-filtered.sql`.
