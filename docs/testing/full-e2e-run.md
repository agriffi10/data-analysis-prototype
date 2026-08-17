# The full end-to-end run — my own operating guide

**Audience: me, driving deployed prod through the Chrome extension.** The per-arc scripts in this
directory are the authority on *what* each check asserts; this file is the authority on *how to run
them all in one controlled pass* — the order, the instruments, the things that read as bugs and
are not, and the honest boundary of what a single signed-in session can settle.

Not a QA checklist. Everything here assumes I can patch page JS, count requests, upload fixtures
and read the repo.

---

## 0. Gates, before anything

1. **`main` is green and I know the deployed sha.** `gh run list --branch main --limit 5`, then
   `git rev-parse HEAD`. A red Deploy App means I am testing something that is not there.
2. **I am signed in as a real user** in the extension's Chrome, and I know which one — every
   result below is meaningless without the username it was observed under.
3. **Approval gates. Ask Andrew before running any of these, every session:**
   - **Archive** — removes his files from a space, and the only way back is a billed retrieval.
   - **Restore** — **3–5 hours, billed on request, uncancellable.**
   - **Deleting a shared space** — tears down its Glue database with it.
   - Anything touching data he did not tell me is disposable.

   Everything else in this guide is safe to run unattended. When an approval is missing, run the
   rest and record the gated part as **not attempted**, never as owed-because-broken.
4. **Only ever archive fixtures I created in this session.** Never a folder that was already there.

---

## 1. Instruments

Install after **every full page load**. Client-side nav (nav-tab clicks) preserves them; `navigate`
does not.

```js
// 1. THE ONE THAT MATTERS MOST — see the trap below.
Object.defineProperty(document,'visibilityState',{get:()=>'visible',configurable:true});
Object.defineProperty(document,'hidden',{get:()=>false,configurable:true});
document.dispatchEvent(new Event('visibilitychange'));
window.dispatchEvent(new Event('focus'));

// 2. Count Athena calls by target, and S3 writes by path.
window.__ath=[];const of=window.fetch;
window.fetch=async function(...a){
  try{
    const r=a[0] instanceof Request?a[0]:new Request(a[0],a[1]);
    const t=r.headers.get('x-amz-target')||'', m=(r.method||'GET').toUpperCase();
    if(t){let b='';try{b=await r.clone().text()}catch(e){} window.__ath.push({t,body:b,ts:Date.now()})}
    else if(m!=='GET'){window.__ath.push({t:'S3:'+m,u:new URL(r.url).pathname,ts:Date.now()})}
  }catch(e){}
  return of.apply(this,a);
};
window.__clr=()=>{window.__ath.length=0};

// 3. Capture what a copy actually wrote.
window.__clip=[];const ow=navigator.clipboard.writeText.bind(navigator.clipboard);
navigator.clipboard.writeText=async t=>{window.__clip.push(t);return ow(t)};

// 4. Capture a download URL without ever returning it to my context.
window.__dl=null;const owin=window.open;
window.open=function(u){window.__dl=String(u);return {focus(){},close(){}}};
const oc=HTMLAnchorElement.prototype.click;
HTMLAnchorElement.prototype.click=function(){if(this.href&&/\.(csv|txt|sql|json)/.test(this.href)){window.__dl=this.href;return}return oc.apply(this,arguments)};
```

Then read a file back **inside the page** — never pull the presigned URL into my context:

```js
const t = await fetch(window.__dl).then(r=>r.text());
JSON.stringify({lines:t.trim().split('\n').length, head:t.split('\n')[0], last:t.trim().split('\n').pop()})
```

### Traps, all measured

| Trap | What it looks like | What to do |
|---|---|---|
| **Hidden Chrome window pauses polling** | One `GetQueryExecution`, then "Running…" forever. `hasFocus()` true, `visibilityState` `hidden`. | Instrument 1. Without it I will file a hung-query bug that does not exist. |
| **`resize_window` reports success and changes nothing** | "Successfully resized to 400x800" while `innerWidth` stays 1512 and every media query still matches desktop. | Never trust the call. Assert on `matchMedia`. **The 400px pass is not runnable this way at all.** |
| **`role="alertdialog"` ≠ `role="dialog"`** | `querySelector('[role="dialog"]')` returns null on the refresh and delete confirms. | Query both. `Drawer` also carries `role="dialog"`, so select modals by title. |
| **Page scroll desyncs click coordinates** | A click lands on a grid cell instead of the nav tab. | Derive coordinates from `getBoundingClientRect()` immediately before clicking, or use `find` → ref. |
| **Prefilled inputs are not selected on focus** | Typing appends: `explorer-shared-destexplorer-shared-filtered`. | `cmd+a` first, or set the value and dispatch `input`. |
| **Monaco needs a click into the text layer** | `type` silently does nothing; the editor keeps its old content. | Click the code line itself, confirm `document.activeElement.className` is `native-edit-context`, then `cmd+a` and type. Press Escape to dismiss autocomplete before running. |
| **Extension blocks returning query strings** | `[BLOCKED: Cookie/query string data]` from `javascript_tool`. | Return derived values — param *names*, booleans, counts — never the URL. |
| **`retry: 1` doubles a failing call** | Two `StartQueryExecution` ~1.1 s apart for one failed apply. | Count executions on statements that **succeed**. |

---

## 2. Fixtures — build once, up front

I can upload: the extension's `file_upload` writes into the portal's own `<input type=file>`, so the
write is made by the portal role. Click **Upload**, then `find` the file input by ref — never click
the input itself (that opens a native picker I cannot see).

```bash
cd "$SCRATCH" && python3 - <<'PY'
import csv, random
random.seed(7)
regions = ["north","south","east","west"]
owners  = ["Smith","Jones","O'Brien","Nakamura","Okafor"]
def w(name, header, rows):
    with open(name,"w",newline="") as f:
        wr = csv.writer(f, lineterminator="\n")   # LF, NOT csv's default CRLF
        wr.writerow(header); wr.writerows(rows)

# 150 rows: pages (page size is 100), 9 O'Brien rows, 2 empty qty cells
rows = [[i, regions[i%4], owners[i%5], "" if i in (7,93) else random.randint(1,999)]
        for i in range(1,151)]
w("explorer-fixture-150.csv", ["id","region","owner","qty"], rows)

# partitioned: part0 sorts first INSIDE THE FIRST PARTITION and carries the extra column
w("part1.csv", ["id","region","amount"], [[i,regions[i%4],i*7] for i in range(1,11)])
w("part2.csv", ["id","region","amount"], [[i,regions[i%4],i*7] for i in range(11,21)])
w("part0.csv", ["id","region","amount","channel"],
  [[i,regions[i%4],i*7,"web" if i%2 else "store"] for i in range(21,31)])

# data quality: agreeing pair, and one that disagrees on columns
w("dq_a.csv", ["id","region","amount"], [[i,regions[i%4],i*3] for i in range(1,21)])
w("dq_b.csv", ["id","region","amount"], [[i,regions[i%4],i*3] for i in range(21,41)])
w("dq_bad.csv", ["id","zone","amount"],  [[i,regions[i%4],i*3] for i in range(41,61)])
PY
```

Upload into **new, empty** folders — the table builder reads a whole folder:

| Folder | Holds | Feeds |
|---|---|---|
| `explorer150/` | `explorer-fixture-150.csv` | Data Explorer, copy/export, saved queries |
| `partfix/year=2025/` | `part1.csv` | partitioned table + refresh |
| `partfix/year=2026/` | `part2.csv` | " |
| `dq_agree/` | `dq_a.csv`, `dq_b.csv` | data-quality clean control |
| `dq_disagree/` | `dq_a.csv`, `dq_bad.csv` | cross-file finding |
| `archive_fixture/` | copies of `dq_a.csv`, `dq_b.csv` | **the only thing I archive** |

Then build tables: `explorer150` (flat) and `partfix` (partition key `year`, string, `2025, 2026`).
Each is a background build — wait for the notification, not a spinner.

**The NULL fixture is a view, not a CSV.** CSV columns are all-string, so an empty cell is `''` and
never SQL NULL; several checks need both side by side:

```sql
CREATE VIEW {db}.explorer150_nulls AS
SELECT id, region, owner, qty, NULLIF(qty, '') AS qty_null FROM {db}.explorer150
```

---

## 3. Run order, and why

The restore is the long pole and everything else fits inside its wait. **Do not run this guide
top-to-bottom.**

```
Phase A  gates, instruments, fixtures, tables                        ~20 min
Phase B  ARCHIVE the fixture folder, then REQUEST THE RESTORE        ~15 min   [approval gate]
Phase C  everything else, while the retrieval runs                   3-5 h
Phase D  the restore completes — the assertions that need it         ~20 min
Phase E  cleanup + write-up
```

If the archive gate is not granted, Phase B and D drop out and Phase C is the whole session.

Within Phase C, cheapest and most reversible first: read-only surfaces → writes → refusals →
destructive. Deleting a shared space goes last because it takes its database with it.

---

## 4. Phase B — archive and restore

This is the part with real consequences, so it gets the most exact treatment. Full assertions:
`archive-restore-e2e.md`. What follows is the sequence I can drive from the browser, plus the
boundary of what I can actually observe.

### B1. Archive `archive_fixture/`

Tick the folder → **Archive** in the selection toolbar. Before confirming, read the dialog:

- Heading names the folder **relative to the space root** — `archive_fixture/`, never
  `agriffith_three/archive_fixture/`.
- Says the data **will be removed from this space**, and that a restore takes **several hours**.
- Does **not** say "This can't be undone" — that would be false, and its absence is deliberate.
- **Focus is on Cancel, and Enter cancels.** The only dialog in the app where that is wanted; this
  is the only place it can be observed. Test it, then reopen.

Confirm, then expect:

- A toast saying the archive **started** — never that it finished.
- A notification within minutes: `Archived N files (X MB). They have been removed from your space.
  Archive id: {uuid} - you'll need it to restore them.`
- **The notification is a link** — follow it and land in `archive/{uuid}/`, not at the space root.
  A link that drops its prefix looks identical from the inbox.
- The folder is gone from the listing; `archive/{uuid}/receipt.txt` downloads and reads correctly.

**Record the archive id.** Everything downstream needs it.

Then check the read-only rules while I am here: inside `archive/` and `archive/{uuid}/`, Upload,
Rename, Delete and paste-into are all refused with a reason on the control, and the receipt still
downloads.

### B2. Request the restore — the point of no return

**Ask before pressing this.** Billed on request, uncancellable, 3–5 hours.

**Restore Archived Data** → paste the archive id → Restore. Then, **within a minute**:

- Download `archive/{id}/receipt.txt`. `Restore requested` must already carry a timestamp and
  `Restored to` must still read `-`. That marker is written **before the bill**; if it is absent
  now it never runs before the money is spent.
- A `restore_started` notification arrives. It is the app's only "started" notification and it is
  emitted after retrieval begins, which is where the bill starts.

Then leave it. Check back at roughly **1 h, 3 h and 5 h** — Phase C fills that time.

### B3. What I can and cannot observe about the retrieval

**Nothing human can read `dat-prod-archive`.** The bucket policy allowlists the execution and deploy
roles; the execution role trusts Lambda only and the deploy role is GitHub-OIDC-only. So:

- **Do not proxy a `head-object` from the UI.** A refusal that had already begun retrieval looks
  *identical* there, and being wrong costs 3–5 billed hours.
- The audit trail is the record. **Confirm `IsLogging: true` first** — a trail that is off returns
  exactly the same empty result as a call that never happened:

  ```bash
  aws cloudtrail get-trail-status --name <archive-audit-trail>
  ```

  Then count `RestoreObject` calls for this archive id in `dat-prod-archive-audit`. Data events
  arrive in batches — allow ~10 min. If my laptop identity cannot read that bucket either, that is
  a finding to record, not a check to fake.
- **Owed regardless of how well this goes:** the `Restore` header's format and the
  `GLACIER`-stays-`GLACIER` property. The trail does not report them. Record as owed.

### B4. Phase D — when it completes

- A second notification says it finished.
- Every file is back at its original path, including any empty folder the archive carried.
- The archive prefix for that id is gone.
- The receipt's ARCHIVE lines are **byte-identical to before** the restore, with `Restored to` now
  filled — a blanked `Requested` line is how I would know the rewrite broke it.
- **Owed, not runnable by me:** `head-object` confirming the restored object came back at
  `STANDARD`. The user-space bucket denies my laptop identity, and the UI cannot show a storage
  class. Record it.

### B5. The refusal worth staging, if there is time

The load-bearing one, and it needs a second restore: re-create one archived file at its exact
original path, then request the restore again with a **new request id** and the **same archive id**.
Expect the whole restore refused — nothing restored, my re-created file untouched, and a
notification starting **"Couldn't restore that:"** (not "Couldn't archive that") naming the path
**relative to the space root** and saying there may be more.

**The assertion is the negative one**, and it is read from the audit trail: for that archive id the
trail must show **no** `RestoreObject`. A refusal that had already started retrieval is invisible
from the UI and costs real hours and money.

---

## 5. Phase C — everything else

Each line: what to do, then the assertion and how I observe it. Areas whose flag is off are skipped
and recorded as skipped.

### Files

- Upload one, several, and a large file into a new folder → land in the folder in view; per-file
  progress; one failure does not take the others.
- Upload a colliding name → Overwrite vs keep-both with a numbered suggestion. Verify the result in
  the listing, not from the dialog.
- Bad folder names (slash, leading/trailing space, empty, very long, unicode) → a specific refusal.
- Download from the row and from Details → read the bytes back in-page (instrument 4).
- Rename / move / copy / delete on a file and on a folder → folder ops are recursive and **not
  atomic**; a partial failure must be reported per item.
- Details → size, type, timestamps, metadata; sizes read consistently across screens.
- **Managed folders, each by its own rule:** `athenaresults` visible but undeletable and not a paste
  target; `saved_queries` ordinary inside, folder itself undeletable/unrenameable; `archive`
  read-only throughout. For each refusal assert `aria-disabled="true"`, `disabled === false`,
  `tabIndex 0`, the exact reason string, **zero** `[role=alertdialog]` opened, and — with instrument
  2 — **zero requests issued**. Control: an ordinary folder beside it must show both controls
  enabled and its confirm must open.

### Query workspace

- Run a query → results, paging without re-running, the cost line.
- Multi-statement script → runs in order, stops at the first failure, earlier statements stay done.
- Broken SQL, missing table, permission failure → three distinct readable messages, editor intact,
  **no raw AWS text** anywhere.
- Schema rail → own database plus every shared space; expand shows columns; the per-table menu
  offers source files, DDL, refresh, share, drop.
- History records and re-runs. Save results writes a CSV where asked, with an overwrite confirm.

### Tables

- Flat build from `explorer150/` → notification, appears in the rail, returns rows, all columns text.
- Partitioned build from `partfix/` with key `year` → **one** Athena statement, no repair step, and
  `WHERE year = '2025'` returns rows immediately.
- Refresh after uploading `part0.csv` **into `year=2025/`** → `1 column added`, rail shows `channel`.
  *The sample is the first key of the whole listing*, so a file in `year=2026/` would be invisible
  by design and `already up to date` would be correct.
- Delete `part0.csv`, refresh with **no** opt-in → refusal naming `channel`, nothing changed. Follow
  the notification link → dialog pre-armed with `channel`, opt-in unchecked, submit `aria-disabled`
  with its reason. Tick and submit → `1 column removed`.
- After both refreshes the partition key still filters — the definition is replaced in place.
- Failure paths: empty folder, mixed formats, layout contradicting declared keys, name already taken
  → one notification each, naming which.

### Data Explorer

Counting executions is the whole point here; use instrument 2 and count on statements that succeed.

- Open a table → 1 execution. Paging Next/Prev/Next → **0**, running total unchanged.
- Apply a filter → 1 execution, a **new** scanned figure. Clear it and re-apply the same → **0**,
  and the line reads "Loaded from an earlier run in this tab — nothing more scanned".
- Filter on `O'Brien` → its rows come back and the disclosed SQL reads `WHERE "owner" = 'O''Brien'`.
  An empty grid here is a **failure**; count the rows first.
- Nonsense in the filter expression → readable banner, previous rows kept, toolbar kept. History
  back → 0 executions. Forward onto the failed step → "Nothing has been run" + *Run it anyway*, 0
  executions.
- Grouping → 1 execution, counts match the fixture, the percentage column is **absent** from the SQL
  and its header says `(this page)`. Compare the disclosed SQL to the `QueryString` on the request —
  **byte-identical**. Leaving grouping drops any `count_all` sort.
- Calc over a selection → **0** Athena requests across function toggles and reselections; the line
  says `N selected cells on this page`.
- Copy: a rectangle in grid order; a gappy selection as its **bounding rectangle** with blanks; a
  column header selects the **page** (100 rows), not the table; JSON gives `null` for NULL and `""`
  for empty. Read all of it from instrument 3.
- Export before anything succeeded → `aria-disabled`, tab-reachable, with its reason. Export after →
  one HEAD + one PUT, and the file holds **every** row (151 lines for the 150-row fixture) while the
  page held 100. Re-export the same name → Overwrite confirm. Export into a shared space →
  cross-bucket PUT.
- Save as query → exactly **one** PUT after a HEAD on the exact key, no sidecar; reopening in Query
  shows the **rendered** SQL, not a bare `SELECT *`.

### Data quality

- Check `dq_disagree/` → the cross-file finding, marked Exact, naming the column, while
  "rows with the wrong number of fields" stays **0**.
- Check `dq_agree/` as the control → clean, that section **absent** rather than empty.
- Check a single file → reports on that file alone; its neighbours are not counted.
- Empty/header-only → called out as a finding, never clean. Sampled/skipped figures never read as a
  pass.
- The runs list pages and reopens reports; a report link for an unreachable space refuses and issues
  **no** S3 request naming it.

### Saved queries, notifications, Help, feature flags

- Save prompts for name and space every time; re-save confirms; another space is a copy.
- A saved query loads back byte-identical and appears in `saved_queries/` in the file browser.
- Every background operation produced **exactly one** notification per outcome; the unread count is
  right after a reload; every link lands in the right place in the right space.
- Help: each section's guide count, the filtering guide's Athena-cost callout, and **no** promise of
  charts, cell editing, named filters, a References panel, or loading a `.sql` back into the
  Explorer.
- Flags: with one off, its surfaces are **gone** (not disabled) including buried entry points on
  other screens' toolbars and its guides in Help; its route renders the unavailable page, not a 404.

---

## 6. What one session cannot settle

Record these as **owed**, never inferred:

| Owed | Why |
|---|---|
| Anything two-sided — receiving a send, membership as a non-owner, opening a colleague's saved query, the roster after acknowledge | Needs a second real account. The one-sided version passes trivially. |
| The **400px** pass and the whole CSS list | `resize_window` does not change the viewport; needs DevTools emulation. |
| **Safari** | My tooling is Chromium. A Chromium pass corroborates and cannot discharge. |
| Bucket-policy Denies (the `DO_NOT_DELETE.txt` delete) | Needs portal-role credentials via the CLI; the app never issues that call. |
| `head-object` on user-space or archive | Explicit deny for the laptop identity. |
| Refresh-lock contention | Two UI submits cannot contend; needs an SQS double-send or a several-hundred-object folder. |
| `Description`/column-comment preservation | Needs the verification role, deliberately not created. |

---

## 7. Cleanup and write-up

**Cleanup:** delete the fixture folders, tables, view and saved queries I created — but leave
anything a still-owed check will need, and say in the write-up what I left and why. Never delete
something I did not create.

**Write-up:** `docs/testing/YYYY-MM-DD-live-check-session.md`, then update each script's owed table,
the delivery docs that still state the old status, and `CLAUDE.md`'s digest lines.

Two rules that outrank everything above:

- **Discharge only what was actually run.** Settling a premise is not running the check. A proxied
  assertion is recorded as owed.
- **Record every instrument.** The `visibilityState` override, the fetch and clipboard patches, and
  any staging shortcut are ways the run differs from a user's, and a reader needs to know which.
