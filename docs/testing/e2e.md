# End-to-end validation — the one guide

**One signed-in account, one browser, one pass.** This is the only script for validating the
deployed app end to end. Everything a signed-in session *cannot* settle — a second account, the
CLI, 400px, a real Glacier retrieval — lives in [`owed.md`](owed.md), which is the ledger
you update when a check moves.

> **This file replaced sixteen.** The per-arc and per-spec scripts (`table-builder-e2e.md`,
> `archive-restore-e2e.md`, `auth-e2e.md`, …) were folded in here on 2026-08-18; their per-spec form
> is in git history, and the evidence they cited is in [`sessions.md`](sessions.md). A spec that owes
> a live check adds it to the matching section below — an arc in flight may keep one script of its
> own, folded in when the arc closes (`docs/process/completion-ritual.md` step 8).

**How to use it.** Run §0 → §1 → §2 in order, then §3's run order, then the feature sections in
§4. Each check is written as **Do → Expect**, and the *Expect* line is the assertion — "the screen
looks right" is never one. Record the outcome in a dated session file (§5).

**Two rules outrank everything below.**

- **Discharge only what was actually run.** Settling a premise is not running the check. A proxied
  assertion is recorded as owed.
- **Record every instrument.** Each patch in §1 is a way your run differs from a user's.

---

## 0. Before you start

| Gate | How |
|---|---|
| `main` is green, and you know the deployed sha | `gh run list --branch main --event push --limit 5`. A red **Deploy SPA image** or **Publish Config** means you are testing something that is not there. **The deployed sha is NOT `git rev-parse HEAD`** — that workflow deploys only when an input to the image changed, so the running bundle is the last commit that changed one. Read it from the service: `aws ecs describe-services --cluster dat-prod-spa --services dat-prod-spa --query 'services[0].taskDefinition' --output text`, then `aws ecs describe-task-definition --task-definition <arn> --query "taskDefinition.containerDefinitions[?name=='spa'].image" --output text` — the tag is the 40-character sha after the last colon. A *green* Deploy SPA image no longer implies HEAD is live. |
| You are signed in, and you know as whom | Every result below is meaningless without the username it was observed under. |
| Feature flags are all on | `config/feature-flags.json` → `environments.prod` is `{}`. A surface that is *absent* under a flag reads exactly like a broken one. |

**Approval gates — ask Andrew before running any of these, every session:**

- **Archive** — removes files from a space; the only way back is a billed retrieval.
- **Restore** — **3–5 hours, billed on request, uncancellable.**
- **Deleting a shared space** — tears down its Glue database with it.
- **The file-operations plane's script** ([`fixtures/file-ops-plane.sh`](fixtures/file-ops-plane.sh))
  — it really moves and deletes files now, on buckets with **versioning off and no trash**. It ends
  in a placeholder no longer; treat every fixture it names as disposable and recreate them between
  runs.
- **The results-conversion plane's script**
  ([`fixtures/results-conversion-plane.sh`](fixtures/results-conversion-plane.sh)) — it writes
  real files into a real space and deliberately stages a name collision. Same bucket rules: no
  versioning, no trash. It needs a token and a finished execution id, and every check in it is an
  `owed.md` row that running it discharges. **SPEC-223 shipped the browser surface**, so the
  conversion itself is now a click and its steps live at §4.3 and §4.5; this script stays for the
  half a click cannot stage — the raw envelope, and a collision raced past the pre-flight probe.
- Anything touching data he did not say is disposable.

Everything else here is safe to run unattended. A missing approval means that part is recorded as
**not attempted** — never as owed-because-broken. **Only ever archive fixtures you created in this
session.**

---

## 1. Instruments

**The shell variables every `curl` step below uses.** Read them once, at the start, from state —
`tofu -chdir=infra init -backend-config=backend.conf` first, or every one comes back empty:

```bash
APP_URL=$(tofu -chdir=infra output -raw spa_origin)
API_ORIGIN=$(tofu -chdir=infra output -raw api_origin)
USER_BUCKET=$(tofu -chdir=infra output -raw s3_user_space_bucket_name)
SHARED_BUCKET=$(tofu -chdir=infra output -raw shared_space_bucket_name)
HOSTED_UI=$(tofu -chdir=infra output -raw cognito_domain)
REGION=$(tofu -chdir=infra output -raw aws_region)
for v in APP_URL API_ORIGIN USER_BUCKET SHARED_BUCKET HOSTED_UI REGION; do
  [ -n "${!v}" ] || echo "EMPTY: $v — every check reading it will pass vacuously"
done
```

**Check the emptiness, do not assume it.** An uninitialised backend makes `tofu output -raw` yield
the empty string through `$( )`, and §4.18's exclusion filter then reads
`amazonaws.com -cognito-idp..amazonaws.com …`, which excludes more than intended and reports **0** —
a wrong conclusion rather than an error. Names are worth reading off `infra/outputs.tf` rather than
guessing: the user-space bucket's is `s3_user_space_bucket_name`, unlike its siblings.

Install the page instruments after **every full page load**. Client-side nav (nav-tab clicks) preserves them; a
`navigate` does not.

```js
// 1. THE ONE THAT MATTERS MOST — see the trap table.
Object.defineProperty(document,'visibilityState',{get:()=>'visible',configurable:true});
Object.defineProperty(document,'hidden',{get:()=>false,configurable:true});
document.dispatchEvent(new Event('visibilitychange'));
window.dispatchEvent(new Event('focus'));

// 2. Count API route calls and S3 writes by path. Its x-amz-target arm should record only
// AWSCognitoIdentityProviderService.* (Amplify's token refresh, or a sign-out's RevokeToken);
// any other target is a direct AWS call, and a regression.
// The API arm was added when the catalog ported (SPEC-199) and has NOT been exercised live yet.
window.__ath=[];const of=window.fetch;
window.fetch=async function(...a){
  try{
    const r=a[0] instanceof Request?a[0]:new Request(a[0],a[1]);
    const t=r.headers.get('x-amz-target')||'', m=(r.method||'GET').toUpperCase();
    const u=new URL(r.url);
    if(t){let b='';try{b=await r.clone().text()}catch(e){} window.__ath.push({t,body:b,ts:Date.now()})}
    else if(u.pathname.startsWith('/v1/')){let b='';try{b=await r.clone().text()}catch(e){}
      window.__ath.push({t:'API:'+m+' '+u.pathname,body:b,ts:Date.now()})}
    else if(m!=='GET'){window.__ath.push({t:'S3:'+m,u:u.pathname,ts:Date.now()})}
  }catch(e){}
  return of.apply(this,a);
};
window.__clr=()=>{window.__ath.length=0};

// 2b. THE UPLOAD IS AN XHR, NOT A FETCH — without this, an upload records ZERO calls and the
// instrument above reads as "the browser issued nothing", which is the opposite of the truth.
const OX=XMLHttpRequest.prototype.open, OS=XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open=function(m,u){this.__m=m;this.__u=String(u);return OX.apply(this,arguments)};
XMLHttpRequest.prototype.send=function(b){
  try{const u=new URL(this.__u,location.origin);
    const rec={t:'XHR:'+this.__m+' '+u.hostname+u.pathname,ts:Date.now()};
    window.__ath.push(rec);
    this.addEventListener('load',()=>{rec.status=this.status});
  }catch(e){}
  return OS.apply(this,arguments)};

// 3. Capture what a copy actually wrote.
window.__clip=[];const ow=navigator.clipboard.writeText.bind(navigator.clipboard);
navigator.clipboard.writeText=async t=>{window.__clip.push(t);return ow(t)};

// 4. Capture a download URL without ever returning it to your context.
window.__dl=null;const owin=window.open;
window.open=function(u){window.__dl=String(u);return {focus(){},close(){}}};
const oc=HTMLAnchorElement.prototype.click;
HTMLAnchorElement.prototype.click=function(){if(this.href&&/\.(csv|txt|sql|json)/.test(this.href)){window.__dl=this.href;return}return oc.apply(this,arguments)};
```

**Counting a query's executions is method-and-path work now, not header work.** A start is
`POST /v1/queries`, a poll is `GET /v1/queries/{id}` and a results read is
`GET /v1/queries/{id}/results` — distinguishable in the network panel, unlike the single Athena
endpoint they replaced. Count with instrument 2 rather than by eye anyway: a poll fires every 1.5 s
and the panel fills fast. No SQS or Athena request carries `x-amz-target` any more — the enqueues
moved behind the API as well, so a control-plane enqueue is a `POST /v1/enqueue/…` like any other
route — and the only targets left are Cognito's. §4.18 is where the browser's whole network
surface is settled.

Read a downloaded file back **inside the page**; never pull a presigned URL into your context:

```js
const t = await fetch(window.__dl).then(r=>r.text());
JSON.stringify({lines:t.trim().split('\n').length, head:t.split('\n')[0], last:t.trim().split('\n').pop()})
```

### Traps, all measured

| Trap | What it looks like | What to do |
|---|---|---|
| **A hidden Chrome window pauses polling** | One `GetQueryExecution`, then "Running…" forever. `hasFocus()` true, `visibilityState` `hidden`. | Instrument 1. Without it you will file a hung-query bug that does not exist. |
| **A backgrounded tab reports a STALE viewport after `resize_window`** | "Successfully resized to 700x900" while `innerWidth` stays 1512, `outerWidth` reads **0**, and every media query still matches desktop. | The window really did resize — `app_list_windows` shows its true bounds, and checking that before concluding the call failed is the cheap move. **Foregrounding the WINDOW is not enough — the TAB has to be the active one, and recording only the window cost a session.** Observed 2026-09-09: minimized, stale; un-minimized by hand, **still** `innerWidth: 1512`; `Control_Chrome`'s `switch_to_tab` on the tab id, and the viewport reads true. Reach for `switch_to_tab` — it is the call that was shown to matter. (Whether un-minimizing is also needed was not tested; it may do both.) **Assert on `matchMedia`, and treat any reading taken while the tab is backgrounded as unusable** — the earlier "the call changes nothing" reading was this artifact (2026-09-01) — **unless a reload followed the resize and `matchMedia` pins the exact width — and then only for synchronous geometry of CSS-driven layout.** A hidden tab still gets no frames, so paint, polling (the row above), `ResizeObserver`, `requestAnimationFrame` and `matchMedia` change listeners stay unusable after a reload, and `switch_to_tab` stays the first choice. Observed 2026-09-11 with no `Control_Chrome` in the session: the tab still hidden, `resize_window` then a reload read true at nine widths, `(min-width: W px)` true and `(min-width: W+1 px)` false at each; without the reload the same tab took two resizes and then stuck at 930 through four more. Print `innerWidth` on every reading — that is the only thing that caught it. Sub-900px checks ARE reachable. Chrome's minimum window width is still 606px, so **400px needs DevTools device toolbar (⌘⇧M)**. |
| **`role="alertdialog"` ≠ `role="dialog"`** | `querySelector('[role="dialog"]')` returns null on the refresh and delete confirms. | Query both. `Drawer` also carries `role="dialog"`, so select modals **by title**. |
| **Page scroll desyncs click coordinates** | A click lands on a grid cell instead of a nav tab. | Derive coordinates from `getBoundingClientRect()` immediately before clicking, or use `find` → ref. |
| **Prefilled inputs are not selected on focus** | Typing appends: `explorer-shared-destexplorer-shared-filtered`. | `cmd+a` first, or set the value and dispatch `input`. |
| **Monaco needs a click into the text layer** | `type` silently does nothing. | Click the code line, confirm `document.activeElement.className` is `native-edit-context`, `cmd+a`, type. Escape dismisses autocomplete before running. |
| **The extension blocks returning query strings** | `[BLOCKED: Cookie/query string data]` from `javascript_tool`. | Return derived values — param *names*, booleans, counts — never the URL. |
| **`computer type` does not reach a React input** | The DOM value changes, React state does not, and submitting sends the *old* value — a folder create that silently does nothing. | Use `form_input` (it dispatches `input`) for every controlled field. `computer type` is fine for Monaco and for comboboxes that filter on keystrokes. |
| **A navigate wipes the instruments** | `window.__ath` is `[]` after any full page load, and an empty log reads as "no requests were issued". | Re-install after **every** `navigate`; prefer nav-tab clicks, which preserve them. |
| **An inline link's box spans wrapped lines** | Clicking a notification link's *centre* hits the parent `<p>` and nothing happens — it looks like a dead link. | Probe with `elementFromPoint` for a coordinate the anchor actually owns, or click its first line. Not a defect; ~30% of the box belongs to the parent. |
| **A failing Data Explorer apply used to double** | Two `StartQueryExecution` ~1.1 s apart for one gesture. | **Fixed** — `athena.start` declares no retry, so one failed apply is one `POST /v1/queries`. Counting on a failing statement is now meaningful; **two starts is a regression**, not the tool. |
| **A dialog's `max-w-md` is 392px, not 448** | A width checker expecting 448 reads every pass as a fail. | Root font-size is **14px**. |

---

## 2. Fixtures — build once, up front

**You can upload.** The Chrome extension's `file_upload` writes into the portal's own
`<input type=file>`, so the write is made by the portal role. Click **Upload**, then `find` the file
input by ref — never click the input itself (that opens a native picker you cannot see). A laptop
IAM identity cannot write `dat-prod-user-space` at all; the portal is the way in.

**`fixtures/explorer-fixture-150.csv` is committed — use it, do not regenerate it.** Every
discharged Data Explorer result in `sessions.md` was measured against that exact file (9 `O'Brien`
rows, 2 empty `qty` cells); the generator below seeds the same but yields a different draw, so a
regenerated copy silently changes the row counts the checks assert. It builds the rest:

```bash
cd "$SCRATCH" && python3 - <<'PY'
import csv
regions = ["north","south","east","west"]
def w(name, header, rows):
    with open(name,"w",newline="",encoding="utf-8") as f:
        wr = csv.writer(f, lineterminator="\n")   # LF, NOT csv's default CRLF
        wr.writerow(header); wr.writerows(rows)

# partitioned: part0 sorts first INSIDE THE FIRST PARTITION and carries the extra column
w("part1.csv", ["id","region","amount"], [[i,regions[i%4],i*7] for i in range(1,11)])
w("part2.csv", ["id","region","amount"], [[i,regions[i%4],i*7] for i in range(11,21)])
w("part0.csv", ["id","region","amount","channel"],
  [[i,regions[i%4],i*7,"web" if i%2 else "store"] for i in range(21,31)])
w("part00.csv", ["ID","Region","Amount"], [[i,regions[i%4],i*7] for i in range(31,41)])
w("part0a.csv", ["ID","Region","Amount","AMOUNT"], [[i,regions[i%4],i*7,i] for i in range(41,51)])
w("part0b.csv", ["ID","Region","Amount","Straße","STRASSE"],
  [[i,regions[i%4],i*7,"a","b"] for i in range(51,61)])

# a column named after the partition key, before the other columns and after them — kept under a new name
w("yearcase.csv", ["Year","id","region"], [[2025,i,regions[i%4]] for i in range(1,6)])
w("yeartrail.csv", ["id","region","year"], [[i,regions[i%4],2025] for i in range(1,6)])

# data quality: agreeing pair, and one that disagrees on columns
w("dq_a.csv", ["id","region","amount"], [[i,regions[i%4],i*3] for i in range(1,21)])
w("dq_b.csv", ["id","region","amount"], [[i,regions[i%4],i*3] for i in range(21,41)])
w("dq_bad.csv", ["id","zone","amount"],  [[i,regions[i%4],i*3] for i in range(41,61)])
w("dq_reorder.csv", ["id","amount","region"], [[i,i*3,regions[i%4]] for i in range(61,81)])

# data quality: one column spelled two ways across files, per format, and a clash inside one file
import json
w("dq_case_a.csv", ["CustomerID","Region"], [[i,regions[i%4]] for i in range(1,11)])
w("dq_case_b.csv", ["customerid","REGION"], [[i,regions[i%4]] for i in range(11,21)])
w("dq_case_clash.csv", ["Total","TOTAL","region"], [[i,i,regions[i%4]] for i in range(1,6)])
for name, keys, ids in (("dq_case_a.json", ("CustomerID","Region"), range(1,11)),
                        ("dq_case_b.json", ("customerid","REGION"), range(11,21))):
    with open(name, "w", encoding="utf-8") as f:
        f.writelines(json.dumps({keys[0]: i, keys[1]: regions[i%4]}) + "\n" for i in ids)
PY
```

The Parquet pair needs polars (in `lambdas/`' dev requirements). Both files must give `CustomerID`
the SAME type, or the profile query fails on the odd file — a different case from the one checked:

```bash
cd "$SCRATCH" && python3 -c '
import polars as pl
r = ["north","south","east","west"]
pl.DataFrame({"CustomerID": list(range(1,11)), "Region": [r[i%4] for i in range(1,11)]}).write_parquet("dq_case_a.parquet")
pl.DataFrame({"customerid": list(range(11,21)), "REGION": [r[i%4] for i in range(11,21)]}).write_parquet("dq_case_b.parquet")'
```

**LF line endings are load-bearing.** Python's `csv.writer` defaults to CRLF, which puts a trailing
`\r` on every value in the built table and silently breaks the numeric filter checks.

Upload each into a **new, empty** folder — the Table Builder reads a whole folder, and inference
samples **one object**, so a stray sibling changes what the table becomes.

| Folder | Holds | Feeds |
|---|---|---|
| `explorer150/` | `explorer-fixture-150.csv` | Data Explorer, copy/export, saved queries |
| `partfix/year=2025/` | `part1.csv` | partitioned table + refresh |
| `partfix/year=2026/` | `part2.csv` | " |
| `yearcase/year=2025/` | `yearcase.csv` | a CSV column named after the partition, first |
| `yeartrail/year=2025/` | `yeartrail.csv` | the same column, last |
| `dq_agree/` | `dq_a.csv`, `dq_b.csv` | data-quality clean control |
| `dq_disagree/` | `dq_a.csv`, `dq_bad.csv` | cross-file finding |
| `dq_reorder/` | `dq_a.csv`, `dq_reorder.csv` | cross-file finding on a CSV's column order |
| `dq_case_csv/`, `dq_case_json/`, `dq_case_parquet/` | `dq_case_a.*` and `dq_case_b.*` of that format | one column spelled two ways across files |
| `dq_case_clash/` | `dq_case_clash.csv` | a case clash inside one file |
| `archive_fixture/` | copies of `dq_a.csv`, `dq_b.csv` | **the only thing you archive** |
| `marker_control/` | *(empty)* | the control beside every protected-folder refusal |

Then build two tables: **`explorer150`** (flat) and **`partfix`** (partition key `year`, string,
`2025, 2026`). Each is a background build — wait for the notification, not a spinner.

**The NULL fixture is a view, not a CSV.** CSV columns are all-string, so an empty cell is `''` and
never SQL NULL; several checks need both side by side:

```sql
CREATE VIEW {db}.explorer150_nulls AS
SELECT id, region, owner, qty, NULLIF(qty, '') AS qty_null FROM {db}.explorer150
```

---

## 3. Run order

The restore is the long pole and everything else fits inside its wait. **Do not run §4
top-to-bottom.**

```
Phase A   §0, §1, §2 — gates, instruments, fixtures, tables            ~20 min
Phase B   §4.11 archive the fixture, then REQUEST the restore          ~15 min   [approval gate]
Phase C   everything else in §4, while the retrieval runs              3-5 h
Phase D   §4.11's completion assertions                                ~20 min
Phase E   §5 cleanup and write-up
```

Without the archive approval, Phases B and D drop out and Phase C is the whole session. Within
Phase C: read-only surfaces → writes → refusals → destructive. Deleting a shared space goes last,
because it takes its database with it.

**§4.18 brackets Phase C rather than ending it.** Its network-surface count needs one window holding
a listing, an upload, a download, a query **and** an enqueue — §4.2, §4.3 and §4.9 — so install its
recorder before them and read the totals after. Its `curl` rows stand alone and can run any time.

---

## 4. The checks

### 4.1 Sign-in and the shell

Run **signed out, in a clean profile**. An existing session refreshes via `cognito-idp` and stays
healthy even when fresh sign-in is completely broken.

**First run only — signup.** Needs a real inbox you control (the default Cognito sender allows
~50 mails/day) and a username matching the catalog-safe rule `^[a-z][a-z0-9_]{2,62}$`, because the
username becomes the S3 prefix, the principal tag **and** the Glue database name.

| Do | Expect |
|---|---|
| Sign up, then enter the emailed code | Account confirmed. **You are not auto-signed-in** — one explicit login follows, and that is the designed behaviour, not a defect. |
| First login | Lands on `/files` with your own empty prefix, and a Glue database named **verbatim** for the username. |
| Sign up again with the same username, a wrong code, a resent code, and a forgotten password | A specific, readable refusal each time — never raw Cognito text. |

**Every run.**

| Do | Expect |
|---|---|
| Sign in through the Hosted UI | Lands on **`$APP_URL`**`/files`, Managed Login v2 branding. A `redirect_mismatch` page instead means `appUrl` and the app client's `callback_urls` disagree — that is the distinguishing symptom, not a blank page. In the network panel, the `POST` to `https://$HOSTED_UI/oauth2/token` returned **200**: the code exchange is a `fetch`, which is what `connect-src` governs. |
| Reload | Still signed in — the session survives a refresh. |
| Sign out, then open `/query` directly | Redirected to sign-in; after signing in you land on **`/query`**, not `/files` (the return path). |
| Sign in again | The topbar carries every tab whose flag is on. |

**Any change to the response-headers policy counts as an auth change.** The CSP's `connect-src`
must list the Hosted UI domain — Amplify's code exchange is a `fetch`, not a navigation:

```bash
curl -sSI "$APP_URL" | grep -io "connect-src[^;]*"
```

### 4.2 Files

| Do | Expect |
|---|---|
| Upload one file, several, and a large one into a new folder | Each lands in the folder in view; per-file progress; one failure does not take the others. |
| Upload a colliding name | Overwrite vs keep-both with a numbered suggestion. **Verify in the listing**, not from the dialog. |
| Create folders named with a slash, a leading/trailing space, empty, very long, unicode | A specific refusal for each — never raw AWS text. |
| Download from the row and from **Details** | Read the bytes back in-page (instrument 4). |
| Rename / move / copy / delete **one FILE** | Done in front of you, listing updated on the spot — the synchronous path, unchanged. |
| Rename / move / copy / delete **a FOLDER, or more than one item** | Accepted immediately: a toast saying *requested*, never *moved*; a card in **File operations in progress**; the listing NOT yet changed. |
| Open **Details** | Size, type, timestamps, metadata — **and the storage class and ETag**, which are the two nobody remembers are here: an owed check sat for a month on "the UI cannot show a storage class", which has been false since this drawer shipped. Sizes read consistently across every screen (one TB ceiling, so 3 TB never reads `3072.0 GB` on one screen and `3.0 TB` on another); sizes read consistently across every screen (one TB ceiling, so 3 TB never reads `3072.0 GB` on one screen and `3.0 TB` on another). |

**The managed folders, each by its own rule.** For every refusal below assert all five:
`aria-disabled="true"`, `disabled === false`, `tabIndex 0`, the exact reason string, **zero**
`[role=alertdialog]` opened, and — with instrument 2 — **zero requests issued**.

| Folder | Rule |
|---|---|
| `system_settings/athenaresults/` | Reached by **opening** `system_settings/`; undeletable; not a paste target; **Archive** disabled with a reason naming it. Read-only **inside**: standing in it, **New folder** and **Upload** — and, for a result, **Move**, **Delete** and **Rename** — refuse with the reason naming query results, and the reason also shows as a visible note; **Copy** and **Download** still work. |
| `saved_queries/` | At the space root, outside `system_settings/`; ordinary inside (upload, subfolders, delete a file); the **folder itself** refuses Delete and Rename. |
| `system_settings/archive/` | Reached by **opening** `system_settings/`; read-only throughout — see §4.11. |
| `system_settings/` | An ORDINARY folder row, sorted among the user's own, with no disclosure control and no caption. Opening it lists exactly `athenaresults/` and `archive/` — **not** `shared_tables/`, which stays at the space root because those tables were sent to the space and are the user's to edit. Selecting it disables Delete, Move and Archive, each with its own reason; the destination picker does not offer it; **New folder** refuses the name `system_settings` with a reason naming the app. |
| **TRANSITIONAL — retire after the migration's `finish` run** | Between the write switch and `finish`, the root ALSO shows `athenaresults/` and `archive/` at depth one, because that is where every object written before the switch still is. (`shared_tables/` is at the root permanently and is not part of this — it never moves.) Assert that each still refuses every write and delete exactly as its new-home twin does — the rules read the plural builder, which answers both homes until the narrowing. New writes land only at the new home, so the depth-one folders should stop growing; that is the observable that says the switch took. |

**The control is not optional.** Select `marker_control/` beside each one: both controls enabled,
and its confirm **does** open. Without it a generic failure reads as the guard working.

**The async switchover — the boundary is "exactly one file", never "is it a folder".** Two rows
above are the whole of it, and getting the boundary wrong is invisible from the UI, so check the
Network tab (instrument 2): a single-file gesture issues **one call to the API** —
`POST /v1/objects/copy`, `POST /v1/objects/move` or `DELETE /v1/objects` — and everything else
issues **one** `POST /v1/enqueue/file-ops`, which the API turns into the queue's `SendMessage`, and
nothing more. **Zero direct AWS calls appear for either**, other than presigned S3 bytes on an
upload or a download.

| Do | Expect |
|---|---|
| Move a folder, then navigate away and back **while it is still running** | The in-progress card is still there — it lives at the app shell, not on the page. **Failed on 2026-09-10**, when `RootLayout`'s error boundary carried a React `key` of the path and remounted the shell on every route change; **passed on 2026-09-13** after #732 — see `owed.md`'s SPEC-190 row. Leave the page only after the card shows, or the check measures a registration race instead. |
| While it runs, select a **folder** (or several items) and try Copy / Move / Delete / **Archive** in that space | All four `aria-disabled` with a reason naming the in-progress list. **Check data quality** and **Send to…** stay enabled — they read, and this lock does not cover them. With a **single file** selected only Archive is gated, because single-file copy, move and delete are the synchronous path, which takes no lock. |
| Wait for the notification | The card reads *Finished*; the space accepts operations again. |
| Press **Refresh this folder** (or leave the tab and come back) | The listing now matches. It does **not** update on the notification — that is deliberate, and §4.12's poll is why. |
| Dismiss a card by hand | It goes, and the space is free again immediately. |
| Copy a FOLDER into the folder it is already in | The auto-number prompt appears **once** (one `POST /v1/objects/free-name`), and confirming enqueues with that name — it is not copied in the browser. |
| **Rename** a folder at a space root to `_data-quality-reports`; then make `x/_data-quality-reports/` and **Move** it to the space root | Both are accepted and then refused per item: each notification reads *"1 item needs your attention"* and labels the item `_data-quality-reports` — the name it would land under, not the renamed folder's old name — with *"that name belongs to a folder the app manages there. Please choose a different destination, or give it a different name first."* After **Refresh this folder**, both folders are still where they were, and a report opened from an earlier data-quality notification still loads. Its **control** is the same rename to an ordinary name, which completes. |
| Open **Details** on a folder the plane has just deleted | *This folder no longer exists*, and Rename/Archive are gone. Not merely an empty panel. |

**The conflict round trip.** Move something onto a name that already exists, then open the
notification and use **Review conflicts** — including from a tab that did not submit it (paste the
`?requestId=` link into a new tab). Expect the colliding items named, a bounded sample, and
*Overwrite* saying in words that it cannot be recovered. A rename offers **Use a different name**
instead, which re-submits safely. Confirm only the conflicted items are re-sent.

**The kill switch, which now switches a capability OFF rather than to a slower route.** Run the
async-off half of §4.14 (`{"asyncFileOperations": false}`, publish, hard-reload). A single-file
copy, move, rename, delete and download are unaffected. A **folder**, or any selection of more than
one item, is **refused at the control**: Copy, Move and Delete are `aria-disabled` with the reason
§4.14 step 3 quotes, so nothing is attempted — no file beside the folder goes through, no card
appears, and no `POST $API_ORIGIN/v1/enqueue/file-ops` fires. Restore the flag in the same sitting.

**The API surface, and the isolation proof (SPEC-198).** Start **signed out** — a signed-in pass
never tests the token path.

| Do | Expect |
|---|---|
| Browse, page a folder past 25 entries, open Details, rename, copy a file, delete a file, create a folder | **One** API call per gesture in the Network panel, and **zero** direct AWS calls other than presigned S3 bytes. |
| Upload a small file and watch the bar | An **intermediate** percentage — not 0 then 100. A `fetch` implementation completes correctly and never moves the bar, so completion is not the assertion. |
| Upload a **multi-GiB** file | Completes past the 900 s window. FR-005 AC8's premise — the URL's expiry is evaluated when S3 *receives* the request, not when the transfer finishes — and the only way to settle it. |
| Cancel an in-flight upload | `Cancelled`, and S3 holds **no partial object** (check the listing and `aws s3api head-object`). |
| Download a file whose name contains `"` and a space | The saved filename is exact. The RFC 6266 escaping is the route's now. |
| Copy a file into the folder it is already in | **One** `POST /v1/objects/free-name`, and the proposed name is `{name} (1)`. |
| Corrupt `{root}user_settings/query-history.json` by hand, then load the Query workspace | The quarantine object appears with its random 8-character token and the app recovers. Three API calls in order: read, copy-aside, write. |
| `curl` a `DELETE /v1/objects` for `{root}saved_queries/DO_NOT_DELETE.txt` | Refused. This discharges `owed.md` §2.1, owed since SPEC-186 — the API now holds the portal-role credentials the check needed. |
| As user A, `GET /v1/objects` naming user B's personal space | **403 `AccessDenied`**, envelope-shaped, `detail` carrying no AWS text, and **no re-login**. |
| As user A, `GET /v1/objects` naming a shared space A is not a member of | The same 403. |
| `curl` a `PUT /v1/objects/content` under `{root}system_settings/archive/` | **403 `AccessDenied`**, `detail` *"archived locations are not writable"*. Record it as the **route-layer** refusal it is: byte-identical to an IAM denial and issued before IAM sees anything, so the credential-layer half is SPEC-196 Phase 5 item 6's dated `_identity/self` result, **cited, never re-run here**. Run it with a **control** write to an ordinary key in the same pass, expecting **200**: without one, a blanket refusal and a key-specific one are indistinguishable. |
| `curl` a `PUT /v1/objects/content` for `{root}system_settings/athenaresults/x/`, and a `POST /v1/objects/copy` whose `destinationKey` is under that folder | **403 `AccessDenied`**, `detail` *"the query results folder is not writable"* — a refusal of a write IAM PERMITS, because IAM denies the delete there. Its **control** is a copy with `sourceKey` under the folder and an ordinary `destinationKey`, expecting **200**: that is Save Results, and it must keep working. |
| `curl` a `PUT /v1/objects/content` for `{root}_data-quality-reports/{requestId}/manifest.json` with `overwrite: true`, and a `POST /v1/objects/upload` for the same key | **403 `AccessDenied`**, `detail` *"the data-quality reports folder is not writable"*, and no URL minted. Its **control** is opening a finished report from its notification, which reads `report.json` through the same folder and must keep working. |
| `curl` a `PUT /v1/objects/content` under `{root}archive/` | **200.** The depth-one name is an ordinary user folder since the narrowing — the receipts moved under `system_settings/` and the Deny that named this path came out with them. It is kept as a row rather than deleted because the refusal above is only meaningful against a path that is NOT refused, and this is the nearest one. |
| `curl -X OPTIONS` the presign path from a foreign `Origin`, and from `$APP_URL` | No `access-control-allow-origin` for the foreign one; allowed for `$APP_URL`. `allow_origins` is **one deployed origin** since SPEC-202 narrowed it — the CloudFront entry that used to be the second is gone with the distribution. `allow_methods` carries `GET, POST, PUT, PATCH, DELETE, OPTIONS` and **not** `HEAD`. |
| Read one record in `logs/service=api/` | Present: `env`, a real build sha, `route_id`, `actor`. **Absent:** any bearer substring, any email, any object body, and any presigned-URL signature — sweep for **all six** of `X-Amz-Signature`, `X-Amz-Credential`, `X-Amz-Security-Token`, `AWSAccessKeyId`, `x-amz-security-token` and `Signature=`. **Name both families, always.** This sweep has already been unfailable once in each direction: it searched only for `X-Amz-Signature` against a deployment minting SigV2 (measured 2026-08-31), and was then narrowed to the SigV2 spelling, which the SigV4 pin of 2026-09-01 made the dead half. A sweep naming only the family currently deployed goes unfailable on a one-keyword change in a different tree. `Signature=` matches inside `X-Amz-Signature=` and is the backstop for a family nobody has thought of. A **hit is not automatically a leak**: `error.stack` carries source lines, and `botocore/auth.py` contains every one of these tokens as a string literal, so an exception raised inside signing puts them in a traceback with no credential present. Read the record before concluding. |

**Multipart uploads (SPEC-216).** Everything above a threshold the browser never sees is cut into
parts server-side. Run these against a real response, not offline — the ETag row is a cross-origin
claim and nothing else settles it.

| Do | Expect |
|---|---|
| Upload a file **above** the threshold (107 MiB; a ~200 MB file is comfortable) with the Network panel open | `POST /v1/objects/upload` answering `mode: "multipart"` with a `partSize` and `partCount`, then **one `POST /v1/objects/upload/part` per part, each immediately before that part's `PUT`** — never all the mints up front. Finally one `POST /v1/objects/upload/complete`. |
| Watch the bar across a part boundary | It **rises past one part's worth and never falls**. This is the aggregate, and it is a different and harder claim than the single-`PUT` intermediate percentage above: last-value-wins would make it drop at each boundary and a running sum would over-report. |
| On one part's `PUT` response, read the `ETag` response header in the Network panel | **Present and readable.** Offline this is a stubbed header; only a real cross-origin response proves the bucket CORS `expose_headers` allowlist. If it is absent the upload fails with "could not be verified" and **no** complete request is sent — which is the designed failure, not a bug. |
| Kill the network mid-upload (throttle to offline for a few seconds, then restore) | The failed part is re-minted and re-sent — **one part's bytes, not the file's**. Count `PUT` sizes in the Network panel. |
| Start a multipart upload, close the drawer with **Escape**, click another nav tab, then come back while it is still running | **No part `PUT` is aborted and no `POST /v1/objects/upload/abort` is sent**; the drawer still lists the upload, still rising. The upload queue lives at the app shell, so a route change between signed-in pages must not end it. Escape alone must not abort either — close the drawer first so the two causes are told apart. Failed on 2026-09-10, when the shell remounted on every route change. **On 2026-09-13, after #732, the survival half passed** — no abort, and the upload completed across the route change — but it finished before the return, so *still rising* on coming back was not observed. |
| Cancel an in-flight multipart upload | `Cancelled` immediately, a `POST /v1/objects/upload/abort` in the panel, and **no assembled object** in the listing or via `head-object`. The abort must be sent **without** the caller's signal — a cancel that aborts its own abort still says `Cancelled` and leaves the parts. |
| Close the tab mid-upload, then check the bucket | Parts remain and **nothing in the browser will ever abort them**. This is the honest limit: the bucket's 7-day `abort_incomplete_multipart_upload` rule is the only sweep. Verify with `aws s3api list-multipart-uploads --bucket <user-space>` **using an operator credential** — the portal role cannot list them, deliberately. |
| Upload a file at or just below the threshold | `mode: "single"` and **one** `PUT`. The comparison is `size > threshold`, so exactly the threshold takes the single path. |

**The zero-call half of the isolation proof is taken OFFLINE, by call count**, in
`lambdas/api/test_objects_routes.py`. A route that resolved the prefix from the request and let IAM
refuse would return the same 403 with the same body, and nothing observable from outside the process
separates the two — so claiming the live 403 proves *where* the refusal happened is the error to
avoid.

**The rest of the plane is still hand-crafted envelopes** — the lock, the give-up, the cross-space
two-lock path and the pagination boundary are not reachable from the UI. They live in
[`fixtures/file-ops-plane.sh`](fixtures/file-ops-plane.sh), behind the approval gate in §0.

### 4.3 Query workspace

| Do | Expect |
|---|---|
| Run a query | Results, paging **without re-running**, the cost line. |
| Run a multi-statement script | Runs in order, stops at the first failure, earlier statements stay done. |
| **A status poll that fails** (SPEC-233) — in DevTools → Network → **Request conditions**, block `*://*/v1/queries/*` — with the scheme: a pattern without one fails to parse as a URLPattern, and the old wildcard form's upgrade also matches the START at `/v1/queries`, which fails the run through a different path with the same sentence — then run any query | Within about two seconds the banner reads **Query failed.** *"Can’t reach the server. Check your connection and try again."*, the bar reads **Failed**, "Running…" is gone and **Run** is free. The start request itself went through (it is not in the blocked list). The network panel shows exactly **two** blocked status requests (the first and its one retry) and no more — then set DevTools to **Offline** and back to **No throttling**, and there is still no third. History shows the entry as **Unknown**. Unblock and run again: it succeeds. In a three-statement script the banner names statement 1 and says the other two did not run. |
| **A query that outlives the ceiling** (SPEC-234) — run a query that takes a minute or so and scans nothing, such as `SELECT count(*) FROM UNNEST(sequence(1, 20000)) AS a(x) CROSS JOIN UNNEST(sequence(1, 20000)) AS b(y)`. While it runs, in DevTools → Network right-click one of its `/v1/queries/<id>` status requests (state `RUNNING`) → **Override content**, and save the body unchanged, so every later poll reads `RUNNING` even after Athena finishes. Keep the tab **visible** and wait 30 minutes. | At about 30 minutes, within one poll, an amber banner titled **Still running** reads *"Data Quarry stopped waiting for this query after 30 minutes, so its results won’t appear here. When it finishes, they’re saved in your files under system_settings/athenaresults, in a file named after its query ID (<id>)."* The bar reads **Still running** with no timer, **Run** is offered and **Stop** is not, and the network panel shows no status request after the deciding one, including after DevTools → **Offline** and back, done at least 30 seconds after the banner: before that the last read is still fresh, and a reconnect would refetch nothing even with a broken stop. History shows the entry as **Unknown**. In Files, `system_settings/athenaresults/<id>.csv` exists, because the query really finished. Remove the override afterwards. The same flow in the Data Explorer (an apply held `RUNNING` the same way) ends in the same banner, with no "Running…" anywhere. |
| Broken SQL / missing table / a permission failure | Three distinct readable messages, editor intact. Athena's own words appear **only inside a closed Details** under the broken-SQL and missing-table messages — never in the sentence — and the permission failure has **no Details at all**. |
| Open the schema rail | Your own database plus every shared space; expand shows columns; the per-table **⋮** offers source files, DDL, refresh, share, drop, **Explore data**. |
| History | Records and re-runs. |
| **Save results** | Writes a CSV where asked, with an overwrite confirm. With `sharedWorkspaces` off it offers **the personal space only** (listed under your username) — a colleague's space must never be a write target. |
| **Save results after a script FAILS part-way** — run three statements with **Run Multiple Queries** where the first is a `SELECT` and the third has a syntax error | The bar shows **Failed** and, beside it, "N rows from an earlier statement" plus **Save results to my files**. Saving writes the FIRST statement's full CSV — check the row count against that statement run alone, not the batch. The point is that no re-run is needed to get it, so an absent button is the regression. |
| **Save results in each format** — run `SELECT * FROM explorer150`, then **Save results to my files** → **Format** | The select offers **CSV**, **Parquet**, **JSON**, **Excel** in that order, defaulting to **CSV**. With CSV the button reads **Save here** and the file appears immediately; with any other it reads **Convert and save**, the dialog closes, and a toast says *"Converting to Parquet — you’ll get a notification when {name}.parquet is ready."* (a curly apostrophe — this is the portal's own authored wording, not the plane's). Nothing is written yet, so the destination folder does **not** gain a row until the notification arrives. |
| **Read each converted file back** | Parquet and JSON through **Create table** on their folder — each table builds and `SELECT count(*)` returns **150**, the fixture's full row count, not the page's 100. Excel opens in a spreadsheet with 150 data rows plus a header. JSON is **one object per line**, not a JSON array — open it and check the first two lines each parse alone. |
| **The notification, and its link** | One notification per conversion: *"Saved 150 rows as Parquet to "{name}.parquet"."* The **message itself** is the link — there is no separate "Open folder" control, deliberately. Following it lands on the destination folder **with the file already listed**; that is the check, since the listing is invalidated on the way. Neither the notification nor the toast names a column or any SQL. |
| **The overwrite confirm on a conversion** — save Parquet twice to the same name | The second save raises **Overwrite "{name}.parquet"?** *before* anything is enqueued, and confirming re-submits. Cancelling returns to the dialog with the name editable, holding the file name the question showed (`{name}.parquet`, extension included), and the format, space and folder as the user left them. The plane still decides: it writes conditionally, so a name taken between the question and the write comes back as a failure notification, not a silent replacement. |
| **A shared-space destination** — the highest-value row here | Save Parquet into a shared space. The file lands under that space's root — `teamspace/reports/…`, **never** `teamspace/teamspace/reports/…`. That doubling is refused by nothing on the plane, and a personal-space save cannot tell the two apart, which is why this row is worth running even if you run no other. The notification's link carries `?space=` and lands in that space's browser. |
| **`resultsConversion` off** (§4.14 carries the method) | The **Format** select is **absent**, not disabled; the button reads **Save here**; saving still writes a CSV exactly as before. Notifications from conversions already run keep working links — the record outlives the surface. |
| **The Excel row limit** — `SELECT 'a' AS c FROM UNNEST(sequence(1, 1100)) AS t1(x) CROSS JOIN UNNEST(sequence(1, 1000)) AS t2(y)`: 1,100,000 rows, about 4.4 MB, 0 bytes scanned | A **failure** notification within a minute, naming the count and suggesting Parquet: *"Couldn't save the query results as Excel: the results have 1,100,000 rows, which is more than a spreadsheet can hold, so "{name}.xlsx" was not written. Please save them as Parquet instead, or narrow the query."* (ASCII apostrophe — the plane's wording, pinned in both languages.) The ceiling is **1,048,575 data rows** (Excel's 1,048,576 less the header), and the converter checks it **before** the cell cap, from a row count taken before anything is built — so a result over it names its rows however wide it is, up to 64 MB; over that, `describe-results` refuses on size first (`results_too_large`). Nothing is written, and the same query as **Parquet** succeeds, which is what makes the suggestion honest. |
| **The Excel cell limit — the query that ran the converter to its timeout at full memory** — `SELECT 'a' AS c01, 'b' AS c02, 'c' AS c03, 'd' AS c04, 'e' AS c05, 'f' AS c06, 'g' AS c07, 'h' AS c08, 'i' AS c09, 'j' AS c10, 'k' AS c11, 'l' AS c12, 'm' AS c13, 'n' AS c14, 'o' AS c15 FROM UNNEST(sequence(1,1023)) AS t1(x) CROSS JOIN UNNEST(sequence(1,1025)) AS t2(y)`: 1,048,575 rows × 15 columns, 62,914,590 bytes, 0 bytes scanned | A failure notification **within a minute, not ten**: *"Couldn't save the query results as Excel: the results have 1,048,575 rows and 15 columns (15,728,625 cells), which is more than the 4,100,000 cells an Excel file can be made from here, so "{name}.xlsx" was not written. Please save them as Parquet instead, or narrow the query."* The converter's log says `refused excel_cell_limit`, and its `REPORT` line shows a few hundred MB, not 3008 and not a timeout. Then save the same query as **Parquet**: it succeeds. |
| **The largest Excel conversion the cell cap admits** — `SELECT lpad(cast(x * 1025 + y AS varchar), 12, '0') || 'a' AS c1, lpad(cast(x * 1025 + y AS varchar), 12, '0') || 'b' AS c2, lpad(cast(x * 1025 + y AS varchar), 12, '0') || 'c' AS c3, lpad(cast(x * 1025 + y AS varchar), 12, '0') || 'd' AS c4 FROM UNNEST(sequence(1,1000)) AS t1(x) CROSS JOIN UNNEST(sequence(1,1025)) AS t2(y)`: 1,025,000 rows × 4 unique 13-character columns, **exactly 4,100,000 cells**, 65,600,020 bytes, 0 bytes scanned | It **converts**: *"Saved 1,025,000 rows as Excel to "{name}.xlsx"."* Then read that invocation's `REPORT` line in `/aws/lambda/dat-prod-results-conversion-convert`. **Max Memory Used must be at most 2,518 MB**, the model's figure for this input, and **Duration under 120 s**. The model's figure is the bound; do not predict the reading from a local peak plus an offset measured on another input. Record both in `sessions.md`. This row's input and figures are for today's constants: after a re-derivation, regenerate both at the new cap, as the Traps in `lambdas/info/planes/results-conversion.md` say. A figure over the model is a finding against the constants in `rccommon.config`, not a pass; one near 3,008 is the failure the cap exists to prevent. |
| **The total row count, from Athena and not by walking** — Rows per page at its default. `SELECT a.x, b.y FROM UNNEST(sequence(1, 2000)) AS a(x) CROSS JOIN UNNEST(sequence(1, 5000)) AS b(y)`: 10,000,000 rows, 0 bytes scanned | The bar reads **"10,000,000 rows"** within a few seconds of *Succeeded*. The network panel shows one to seven `GET /v1/queries/{id}/row-count` calls and **zero** `…/results?maxRows=1000`. The only `…/results` calls are the pager's, at the display page size. Before this change the same query walked about 10,000 billed pages, 1.6 a second, and stopped only when the page was left. |
| **A count the grid can check** — `SELECT x FROM UNNEST(sequence(1, 12345)) AS t(x) WHERE x % 7 = 0` | The bar reads **"1,763 rows"**, and paging to the last page ends at row 1,763. One to seven `…/row-count` calls (more than one only if Athena's count had not landed when the page first asked) and no `maxRows=1000` walk. |
| **A statement Athena does not count** — `SHOW TABLES IN <your database>` | The count is exact and arrives by the walk: `…/row-count` answers `{"rowCount": null, "pending": false}`, then one `…/results?maxRows=1000` call. |
| **The statement a `StatementType`-keyed rule would get wrong** — `EXPLAIN SELECT x FROM UNNEST(sequence(1, 10)) AS t(x)` | `…/row-count` answers **`{"rowCount": null, "pending": false}`, never 1**, and one `…/results?maxRows=1000` walk call follows; the bar reads the plan's own row count (20 when this row was written). **The route's body and the walk call are the check, not the bar**: the grid guard never shows a 1 below the rows loaded, so the bar alone cannot fail here. Athena labels this `DML/EXPLAIN` and reports `OutputRows: 1` over it, which is why only a `SELECT` gets Athena's count. |
| **Drag the divider** between the editor and the results, release, then reload the page | The panes follow the pointer continuously and the two always fill the column with no gap; Monaco's gutter and scrollbar match the new height (the reason the pane height alone is not the check). The split you left survives the reload and is gone in a private window — it is per session, per user. |
| Reach the divider by tabbing (**not** forward from the editor — Monaco swallows Tab; come backwards from the results, which is two Shift+Tabs, since the ▼ button sits between them), then use the arrow keys, **Home** and **End**; then double-click it | Focus is visible on the divider itself; the arrows step the split, `Home`/`End` go to the floors, and a double-click returns it to even. Then click the divider and press an arrow **without** dragging — the click must leave it focused, or the keyboard path is unreachable for anyone who found it with a mouse. |
| Use the **▲** and **▼** buttons on the divider, without dragging | Each click steps the split by one notch and the split sticks. This is the non-drag pointer path — run it with a click only, since a drag would pass it vacuously. **Measure one button** in the inspector: it must be at least 24x24 CSS px — they are `h-[24px] w-[24px]`, an absolute value chosen so neither the 14px root nor the type scale reaches them. axe's `target-size` cannot evaluate this and is now disabled; §4.13 carries the rule itself, including SC 2.5.8's spacing exception. |
| Shrink the window until the workspace is short, then grow it again | Neither pane collapses — the editor keeps its floor and the results keep theirs — and growing the window returns the split to the proportion you dragged, not to the clamped one. |

**The catalog behind the API (SPEC-199).** Start **signed out** — a signed-in pass never tests the
token path — and run these before anything else in this section, because the first one is the arc's
central claim.

| Do | Expect |
|---|---|
| **Run a real `SELECT` against your own database, and rows render** | This is the check the whole arc rests on: Lake Formation grants attach to a **principal**, and that principal is now the same portal role assumed by the API rather than vended to the browser. **Record the result against SPEC-196 as well — it discharges that spec's Phase 5 item 4.** No CloudTrail step exists to corroborate it: the account's only trail records S3 data events for the archive bucket. |
| Expand a rail node for a database you have no `DESCRIBE` on | **403**, envelope-shaped, `code: "AccessDenied"`, **no** AWS text in `detail`, the screen says *"You don't have permission to do that."* — and **no re-login**. |
| Run a `SELECT` against a table you have no `SELECT` on | **200** on `GET /v1/queries/{id}`, the execution reaches **FAILED**, and the banner reads *"You don't have permission to run that query."* Record both status codes: recording only the 403 above proves nothing about the shape that matters more. |
| `GET /v1/catalog/databases/{a stranger's username}` and `…/{a name nobody has}` | **Record what each actually returns.** This is the no-existence-oracle question and the answer is Lake Formation's, not this API's. If they differ, that is a finding for SPEC-202's sweep, not a failure here. |
| `SELECT NULL AS a, '' AS b` | Read the **raw response body** in the network panel — `"rows": [[null, ""]]`. The rendered grid shows the Value panel's rendering of both and cannot tell them apart. |
| `curl` `GET /v1/queries/{id}/results` against a still-running execution | **409 `QueryNotFinished`**, envelope-shaped. Then submit a malformed statement and confirm it is **400 `QuerySyntaxError`** — one exception name, two codes, and getting them from the name alone is the original defect. |
| **View DDL** on a real table, then **Options → Create view…** | One start, N polls at ~400 ms, one results call each. These are the **two** paths that send `database` on `POST /v1/queries` — `getTableDdl` and `useRunDdl` — and exercising only the first leaves the other unchecked. |
| Stop a running query, then stop it again | Both succeed. The second is a no-op on a terminal execution, not an error. |
| **An execution that is not yours (SPEC-232).** First `GET /v1/queries/{a random UUID}`, then the same for an execution the operator starts with its output outside every user's prefix (`aws athena start-query-execution --query-string 'SELECT 1' --work-group dat-prod-portal-wg --result-configuration OutputLocation=s3://dat-prod-athena-admin/fallback-results/spec232-probe/`) | Both answer **404 `NotFound`** on `GET /v1/queries/{id}`, `…/results`, `…/row-count` and `POST …/stop`, and the two bodies are identical apart from `requestId`. Run the unknown-UUID status probe **first**: it answered 500 before this spec shipped, so a 404 is what proves the new image is serving. Before SPEC-232, the operator's execution answered 200 with its state and admin-bucket location. In `logs/service=api/`, each refusal carries `execution_ownership: unknown` or `foreign`; the records arrive on the sweep, as the log row below says. Then a query of your own still polls and pages (the first row of this section), a stop of your own running query still works, and **View DDL** still opens, because the proof only refuses what is not yours. |
| Read one record in `logs/service=api/` for a catalog route | Present: `env`, a real build sha, `route_id`, `actor`, `sql_bytes`, `state`. **Absent:** the SQL text, any `stateChangeReason`, any result cell, any bearer substring, any email. Records arrive on the 10-minute sweep — wait for it rather than concluding from an empty query. |
| **The load-bearing negative**, after exercising this section and §4.5 end to end | **Zero** requests to `athena.*.amazonaws.com` and `glue.*.amazonaws.com`. |
| The **first** invocation after a deploy | Succeeds. Cold start is where an import that cannot resolve fails, and it is silent everywhere else. The layer-attachment form of that is gone — one image carries every shared package — but the class is not: a module missing from the image, or an environment variable read at import, still surfaces only here. |

~~**Safari**, since that is the browser in use; a Chromium pass corroborates and cannot discharge.~~
**A Chromium pass discharges this section.** The deployment's audience has no Safari (Andrew,
2026-09-01, recorded in SPEC-202's §9 criterion), so Andrew's own Safari use corroborates and never
gates.

### 4.4 Tables — build and refresh

**Build.**

| Do | Expect |
|---|---|
| Build from `explorer150/` | Notification, appears in the rail, returns rows, all columns text. |
| **Create table** at a space ROOT | The button is `aria-disabled` with a reason about the folder being read whole — the dialog never opens. A table there would SUCCEED over `athenaresults/` and friends, which is what makes this worth blocking. |
| Build from a folder whose CSV header has `Order ID` | Refused by notification, **naming the column**. Refused deliberately even though it would work today — one rule everywhere. |
| Build from a folder whose header has `Total` and `TOTAL` | Refused, naming **both**: Athena lowercases, so they are one column to it and two to everything else. |
| Build from a header with `_id`, `2024_total`, `select` | **Builds.** Leading underscores, leading digits and reserved words are quoted, not refused. |
| Refresh a table whose header the rule would now refuse for anything but a case collision, such as `Order ID` | **Refreshes.** Creates only — refusing would strand a table already in the catalog. |
| Build from `partfix/` with key `year` (string, `2025, 2026`) | **One** Athena statement, no repair step, and `WHERE year = '2025'` returns rows immediately. |
| Build from `yearcase/` (header `Year,id,region`) with key `year` (string, `2025`), then query it | **Builds**, and the ready notification ends *"A column named after a partition key keeps its values under a new name: "Year" is "year_in_file"."* The rail shows `year_in_file, id, region`, and `SELECT year_in_file, id, region, year` returns `2025, 1, south, 2025` for the first row — nothing shifted. Before any rename, the same rows with the column left out read `id` as `2025`. |
| Build from `yeartrail/` (header `id,region,year`) with the same key, then query it | **Builds** with `year_in_file` last in the rail, and `SELECT id, region, year_in_file, year` returns `1, south, 2025, 2025`. |
| Refresh the `yearcase` table with nothing changed | **Already up to date** — the refresh compares under the same rename, so `year_in_file` is not reported removed. |
| Build from an empty folder, a mixed-format folder, a layout contradicting the declared keys, a name already taken | One notification each, naming which. |

**Refresh — the sample is ONE OBJECT, and it is the FIRST KEY IN LISTING ORDER.** Inference keeps
the first key the listing yields, lexicographically. **A column added in a file that sorts later is
invisible by design**, and the refresh correctly reports `already up to date`. That is not a bug.
On a partitioned table the sample is the first key of the **whole** listing, so the file must go in
the **first** partition.

1. Upload `part0.csv` into `partfix/year=2025/`. **Refresh table** from the Query rail.
   → `1 column added`; the rail reads `id, region, amount, channel`.
2. Delete `part0.csv`, refresh **without** the opt-in.
   → A refusal naming **`channel`**. Nothing changed.
3. Follow the notification link.
   → The dialog opens pre-armed with `channel` named, the opt-in **unchecked**, and submit carrying
   an `aria-disabled` reason rather than being silently dead.
4. Tick the opt-in and submit. → `1 column removed`.
5. The same filtered `WHERE year = '2025'` still works after both refreshes — the definition was
   replaced in place and the partition key survived.
6. **The casing control:** upload `part00.csv` (`ID,Region,Amount`) **into `year=2025/`** — the same
   partition as step 1, because the sample is the first key of the whole listing and a copy in
   `year=2026/` is never read. It sorts before `part1.csv`, so it becomes the sample.
   → `already up to date` and the rail **unchanged** — the diff folds case rather than seeing 3
   added and 3 removed, and nothing is silently re-cased.
7. **The collision control:** delete `part00.csv` and upload `part0a.csv` (`ID,Region,Amount,AMOUNT`)
   into `year=2025/`, where it sorts before `part1.csv`. Refresh.
   → A refusal naming **both** `Amount` and `AMOUNT`, in a create's words, and the rail unchanged.
   `already up to date` here is the defect: the collision went unreported.
8. **The sharp-s control:** delete `part0a.csv`, upload `part0b.csv`
   (`ID,Region,Amount,Straße,STRASSE`) into `year=2025/`, refresh.
   → `2 columns added`, and the rail reads `id, region, amount, straße, strasse`. `1 column added`
   over that same rail is the defect: a diff folding `ß` into `ss` while the write keeps it.
9. Delete `part0b.csv` and refresh with the opt-in. → `2 columns removed`, and the fixture is back
   to `id, region, amount`.

> Refresh-lock contention is **not runnable from the UI** — two submits 2 s apart both return
> independently, because a small table's refresh finishes inside that window. See `owed.md`.

### 4.5 Data Explorer

**Counting executions is the whole point of this section.** Use instrument 2 and count
`POST /v1/queries`. A failing apply now issues exactly **one** of them, so a failing statement counts
as honestly as a succeeding one.

| # | Do | Expect |
|---|---|---|
| 1 | Open `explorer150` from the picker | The picker lists **Space**, then tables and views. A tab opens named for the table. **1** execution. |
| 2 | Query rail → table **⋮** → **Explore data** | Lands on `/explore` with the table open. The URL carries `?space=&db=&table=`, then **drops** them. Reload → the tabs you had, **not** a second copy. |
| 3 | Paste `/explore?space=<a space you are not in>&db=x&table=y` | The refusal page, and **zero Glue and zero Athena requests**. That negative is the check — the page must not become an existence oracle. |
| 4 | Apply a filter that removes most rows | **1** `StartQueryExecution` and a **different** scanned figure. "The grid changed" is not the assertion — a client-side filter would do that too. |
| 5 | **Next**, **Prev**, **Next** on the pager | **Zero** `StartQueryExecution`. `GET …/results` calls are expected: each scans nothing, though each is an API call. The running total does not move. |
| 6 | Clear the filter, then apply the **same** one again | **Zero** new executions, and the line reads *"Loaded from an earlier run in this tab — nothing more scanned"*. Total unchanged. |
| 7 | Click an `O'Brien` cell → **Filter by this value** | **Rows come back** — count them in the unfiltered grid first. **An empty grid here is a FAILURE.** **Generated SQL** reads `WHERE "owner" = 'O''Brien'`. The wrong escaper fails *silently*, as a predicate that matches nothing. |
| 8 | Type `qty >>> 5` into **Filter expression** → **Apply** | Error banner, the **previous** rows still beneath it, toolbar and expression bar still there. |
| 9 | History **back**, then **forward** onto the failed step | Back: the good rows, **no** re-run. Forward: *"This set of filters failed last time it ran. Nothing has been run."* + **Run it anyway**, and **zero** executions on arrival. |
| 10 | **Grouping** → group by `region`, `COUNT(*)`, tick **Show percentage**, Apply | **1** execution, changed figure. **Generated SQL** is a real `GROUP BY` and the percentage column is **not in it** — it is computed in the browser and its header says `(this page)`. |
| 11 | Copy the disclosed SQL, then `aws athena get-query-execution --query-execution-id <id>` and compare `QueryString` | **Byte-identical.** The only check that proves the disclosure and the executed string have not drifted — and a JSON hop now sits in the middle, so the comparison is against Athena's own read-back, not against the request body. |
| 12 | Leave grouping | Any sort on `count_all` is **dropped**, not carried onto the raw table. |
| 13 | Select a dozen numeric cells → **Calc**, toggle functions, reselect | The aggregates, the line `N selected cells on this page`, and **zero** Athena requests throughout. |
| 14 | Open `/explore`, pick a source, and watch the network panel through the QUEUED window | **Zero** `GET /v1/queries/{id}/results` until a poll reports `SUCCEEDED`. This is the surface the too-early read broke, and with the 409 mapping in place removing the gate now shows a *correct-looking* "still running" message — so the request count is the only assertion that can fail. |
| 15 | Page a >100-row result forward and back | Cached pages, no refetch. Every page request carries a properly encoded `nextToken` — an unencoded `+` decodes to a space and the next page silently restarts from the beginning. The Explorer shows no total row count, so there is none to wait for; the Query workspace's count is §4.3's. |

**Copy and export** (instrument 3 for the clipboard):

1. Select a rectangle, ⌘C, paste → cells in grid order, `NULL` where the grid showed NULL.
2. ⌘-click two non-adjacent cells, copy → the **bounding rectangle**, cells between blank.
3. Click a **column header**, copy → the loaded page's rows only.
4. **Copy…** → **JSON** → `null` for the NULL and `""` for the empty cell. Distinguishable is the point.
5. **Save results to my files** (Options) before anything has run → refused, `aria-disabled`, `disabled`
   false, `tabIndex 0`, *"Run a query first — there are no results to save yet."*, and no such button
   beside the pager. No need to be quick: "nothing has run" and "still running" are one state.
6. **Save results to my files** beside the pager → `explorer-export` → **My files** → **Save here** →
   success toast, and the file in **Files**.
7. **Open the saved CSV and count its rows.** It holds the **whole** result — 151 lines for the
   150-row fixture — while the page held 100. Download it through the portal.
8. Steps 1–7 started **zero** `StartQueryExecution`.
9. Save again, same name → the **Overwrite** confirm.
10. Save into a **shared space** → the cross-bucket copy succeeds.
11. **The format choice, on this surface too.** Re-open **Save results to my files** → **Format** now
    offers **CSV**, **Parquet**, **JSON**, **Excel**, defaulting to **CSV**. Choose **Parquet**: the
    button changes to **Convert and save**, the dialog closes on submit, and the toast names the
    format and the file. Still **zero** `StartQueryExecution` — a conversion reads the execution's
    results object and starts no query.
12. **The notification lands and its link works.** *"Saved 150 rows as Parquet to
    "explorer-export.parquet"."* — 150, the whole result, not the 100 on the page. Following the
    message link lands on the folder with the file already listed.
13. **Both surfaces, one dialog.** Save the same exploration as **Excel** and confirm the file opens
    with 150 data rows. This surface and §4.3's are the same component — if the two ever disagree
    about a label or the button text, that is the regression this pair exists to catch.

> **A query that outruns the watch's ceiling** is specified since SPEC-234. After 30 minutes the
> Explorer, like the Query tab, settles with an amber **Still running** banner that names the
> execution and where its CSV lands, and says "Running…" nowhere. §4.3's *A query that outlives the
> ceiling* row is the check. Do not file a "Running…" that ends at the ceiling as a hang.
>
> **The suspended-failed-statement state is per-mount, and that is accepted, not a defect.** Leave
> `/explore` and come back and the statement is submitted again. Do not file it.

**The rebuilt table — the check this whole eviction exists for.** Count executions throughout.

| # | Do | Expect |
|---|---|---|
| A | Open an exploration of `explorer150`, note the rows | Baseline. |
| B | In **Query**, `DROP TABLE` it; go back to `/explore` | The tab **re-runs on its own** — 1 execution. Old rows served here is the bug. |
| C | Rebuild it from a folder holding **different** data (Files → Create table), leave the window and come back | On focus the catalog is re-read and the tab re-runs, showing the NEW rows. Returning to a window you never left will not do it — `focus` fires on blur→focus only. |
| D | With an exploration open, use **Options → Create view…** on it | **Zero** new executions. Creating a view changes no rows, and re-running here was a measured defect. |
| E | With an exploration open, drop an **unrelated** table in the same database | **Zero** new executions on the open tab. |
| F | Apply a filter and change it back, having done B–E | Still a cache hit, still zero executions. The eviction must not have cost the cache its whole point. |

**Create and options, on the Explorer's own surfaces.**

| Do | Expect |
|---|---|
| Open the picker with no tabs | The space rail, then the object list headed **Tables (n)**, and **Views (n)** — either heading is omitted when that group is empty, which is symmetric, so a space with tables and no views correctly shows one heading. No title over the list, and NO create control anywhere on the picker. |
| **Options** on an open exploration | One menu holding Order and filter, Remove all filters, Filter by this value, Columns, Colours, Transformers, Value, Calc, Grouping, Copy…, Save results to my files, Save as query, Create view…. The bar keeps only undo/redo and the view switch. |
| **Options** with nothing selected | **Copy…** sits there `aria-disabled` with its reason on hover AND reachable by Arrow — not missing, not silently inert. |
| Pick any Options item, then press Tab | Focus is on the **Options** button, not at the top of the page. |
| **Options → Create view…**, name it, then look in the rail | The view appears. Its statement quotes both identifiers. |

### 4.6 Data quality

| Do | Expect |
|---|---|
| Check `dq_disagree/` | The cross-file finding, marked **Exact**, naming the column, while *"rows with the wrong number of fields"* stays **0**. |
| Check `dq_agree/` (the control) | Clean, with that section **absent** rather than empty. |
| Check `dq_reorder/` (same columns as `dq_a.csv`, `amount` and `region` swapped) | **Issues found**: the cross-file section names `dq_reorder.csv` with *"Positions: don’t line up with this report’s Columns"* (curly apostrophes on the page, so search on *"line up with this report"*) and no Missing or Extra line, and the report's *What to look at first* line says `dq_reorder.csv`'s columns don't line up with this report's Columns, marked **Exact** (the notification carries no issues, only the link). `dq_agree/` above stays clean, so the order is what is being compared. |
| Check a **single file** | Reports on that file alone — its neighbours are not counted. |
| Check an empty / header-only folder | Called out as a finding, never clean. Sampled and skipped figures never read as a pass. |
| The runs list | Pages, and reopens reports. |
| Check `dq_case_csv/`, `dq_case_json/` and `dq_case_parquet/` | Each **checks**, not refused, with cross-file agreement clean. Columns lists `CustomerID` once, with *"Also spelled customerid in other files"* beneath it, and `Region` with *"Also spelled REGION in other files"* — `dq_case_a` sorts first, so its spelling is the one shown. Both columns read **0%** null or blank: every value is filled, so anything above 0% means a file's spelling went unread. |
| Check `dq_case_clash/` | Refused by notification naming `"Total", "TOTAL"` — two spellings in ONE file are a header Athena cannot read. |
| Check a folder whose header has `Order ID` | Refused by notification naming the column — a check cannot report on data it cannot read, so this is the answer rather than a gap in it. |
| Check a folder with a `key=value` partition whose KEY is not `[a-z0-9_]` (e.g. `order-id=1/`) | Refused under its **own** wording, about folder names — not the column one, because the repair is renaming a folder. |
| Check `yearcase/` | **A report**, with no cross-file finding. Columns lists `year_in_file, id, region` with their own figures, and above them *"Year is listed as year_in_file. The folder has a partition of the same name…"*. `yeartrail/` reports the same with `year_in_file` last. |
| A report link for an unreachable space | Refuses, and issues **no S3 request naming it**. |
| Take the request id of a check **run after the claim deployed** from its report link — an older one holds no claim, and re-sending it overwrites that check's report — and, more than five minutes later, send it again with `POST /v1/enqueue/dataQuality` naming a different folder | **No notification arrives**, and the link still reports the first folder. From a read-only CLI, the second execution failed at `InspectSource` with `request_id_reused`. The same id in **upper case** is instead refused by notification as malformed. |

### 4.7 Saved queries

| Do | Expect |
|---|---|
| Save a query | Prompts for **name and space every time**. |
| Re-save unchanged | Confirms **once**. |
| Save to another space | A **copy** — the original stays. |
| Load it back | Byte-identical, and it appears in `saved_queries/` in the file browser. |
| Save a `.SQL`-cased name | Stem case is kept, extension is lowercased — no second object rendering identically. |
| From the Data Explorer: **Save as query** → `explorer-roundtrip` → your own space (listed under your username) | Exactly **one** `PutObject` after a HEAD on the exact key. No sidecar. |
| Open it in **Query** → **Saved queries** | The **rendered** statement — the filters and the ORDER BY, **not** a bare `SELECT *`. Run it: the same rows. |
| Save from Query, load in Query | Works. The Explorer offers **no** affordance to load a `.sql` as a source — confirming that absence *is* the check. |
| Save to a **shared space** | Cross-bucket write succeeds; the file appears in that space's `saved_queries/`. |

The `saved_queries/` folder's own Delete/Rename refusal is in §4.2. The bucket-policy layer beneath
it is CLI-only — see `owed.md`.

### 4.8 Shared spaces and connections

| Do | Expect |
|---|---|
| Create a space | Creator-only. It appears in the rail with its own Glue database. |
| Add a member | The member sees it after signing in; their status flips **Pending → Active** on first sign-in. |
| Add a member who does not exist | Silently ignored — the others are still added, and the execution still SUCCEEDS. |
| Add the same member twice | Idempotent. The owner can never be added as a member. |
| **Remove** a member | Their slot is cleared and their cache entry dropped; the space leaves their rail. The objects under it are **not** deleted. |
| Create a space whose name is already taken | Refused by name. The registry record **is** the name lock. |
| Read the roster | Every member sees a read-only roster, and **the reader's own row is never `Pending`**. No page ever asserts `Active` and `Pending` about one member at once. |
| Query the space's database | Results route to the space's own `system_settings/athenaresults/`, not yours. |
| Leave a space, then reload with its `?space=` still in the URL | Falls back, with **zero S3 requests naming the space** — no existence oracle. |
| **[approval gate]** Delete a space (type-to-confirm) | Gone from the rail, the Connections page and the Files browser, for the owner too. Its objects and its Glue database **survive** — a delete now removes people, not things. The dialog must not claim otherwise: no "can't be undone", no "permanently deletes". |
| **[approval gate]** Re-create a space with the just-deleted name | **Refused** by name. The record is never released, so the name is spent forever — the opposite of what this row asserted before, and the reason the create dialog now warns before the name is chosen. |
| **Transfer ownership** to a member (Manage → **Make owner**) | The dialog names the space and the member, says you stay a member, and says only they can transfer it back. After it lands: their card reads **Owner**, yours reads **Member** and names them as owner, and **both of you still read `Active` in the roster** — the outgoing owner rendering as `Pending` is the defect this is here to catch. |
| Transfer, then Refresh, then reopen Manage | You no longer have Manage on that space at all. The two of you get one notification each, naming the other; nobody else does. |
| Transfer to yourself, or to someone not in the roster | Refused, and the refusal **names the person**. Nothing changes and no notification pair is sent. |
| Transfer a space, then have the new owner transfer it back | Works, and both of you read `Active` throughout. A member who had never signed in reads `Active` after a round trip — accepted, and pinned by a unit test rather than fixed. |
| Delete a space, then re-mint credentials and try to open it | **Sign out and back in first, or wait out the Identity Pool TTL.** The principal tag is stamped when credentials are vended, so a session held from before the delete still carries it and can still reach the retained data. The deleter's own browser is the one most likely to be used for this check and the one most likely to mislead. |

### 4.9 Send files

**One-sided only from one account.** The receiving half is in `owed.md`.

| Do | Expect |
|---|---|
| Tick a **folder** then a **file**, → **Send to…** | The dialog names items **by name** with a count (`Sending 2 items`), not by full key. |
| Type into **Users** | Suggestions from the username directory. An unknown name stays typeable. |
| Switch to **Shared spaces**, type | Suggestions **under this kind too** — from your own connections. |
| Add several chips | **Send** stays reachable; the dialog body scrolls, not the page. |
| Send | Dialog closes, selection clears, toast says the send was **requested**. |
| Your inbox | **One notification per recipient**, each naming the recipient and the count. |
| Send the same items again to the same recipient plus a new one | A `conflict` for the first, **naming the item** (the first in selection order), and a success for the second. |
| Send with no recipients | The inline refusal is **reachable** — the submit is never merely disabled. |

### 4.10 Table share

| Do | Expect |
|---|---|
| Query rail → table → **Share table**, to a real user | Success notification naming the recipient. |
| Share to a **space** | The dialog's space entry suggests **only spaces you belong to** — no directory of all spaces exists, by decision. |
| Share to more recipients than the cap allows | *"…that's too many files to copy to that many recipients at once."* Nothing written — no manifest for that run. |

The scale pass (a several-hundred-object, >20 GiB table; the 100-column clone read back through
`GetTable`) needs the CLI — see `owed.md`.

### 4.11 Archive and restore — **[approval gate]**

The long pole. Start this in Phase B and finish in Phase D. **Nothing human can read
`dat-prod-archive`** — the bucket policy allowlists the execution and deploy roles only.

#### B1. Archive `archive_fixture/`

Tick the folder → **Archive** in the selection toolbar. **Before confirming, read the dialog:**

- The heading names the folder **relative to the space root** — `archive_fixture/`, never
  `agriffith_three/archive_fixture/`.
- It says the data **will be removed from this space**, and that a restore takes **several hours**.
- It does **not** say "This can't be undone" — that would be its one false sentence, and its
  absence is deliberate.
- **Focus is on Cancel, and Enter cancels.** The only dialog in the app where that is wanted, and
  the only place it can be observed. Test it, then reopen.

Confirm. Expect:

- A toast saying the archive **started** — never that it finished.
- Within minutes: `Archived N files (X MB). They have been removed from your space. Archive id:
  {uuid} - you'll need it to restore them.`
- **The notification is a link.** Follow it → you land in `system_settings/archive/{uuid}/`,
  **not** at the space root. A link that drops its prefix looks identical from the inbox.
- The folder is gone from the listing; `system_settings/archive/{uuid}/receipt.txt` downloads and
  reads correctly.

**Record the archive id.** Everything downstream needs it.

Then, while you are here — `system_settings/archive/` and `system_settings/archive/{uuid}/` are
read-only and say so, at **both**
widths (the mobile action bar mounts its own controls, so a CSS-hidden twin would pass a
desktop-only check):

- **Upload** and **New folder** present but unavailable, with a reason naming the folder as
  read-only. **No `AccessDenied` ever reaches you.**
- Selecting the receipt: **Move** and **Delete** likewise unavailable with a reason.
- **Archive** is **gone**, not disabled. An archive of an archive is not a thing.
- **Details** and **Download** work normally — that is the point of the folder being visible.
- At the space root: open the `system_settings` folder first — the archive receipts written since
  the switch are inside it. There `archive/` refuses Delete and Rename by name, and it is absent
  from the destination picker when you Move or Copy something else.
- **Until the migration's `finish` run, a depth-one `archive/` is ALSO at the root**, holding every
  receipt written before the switch. It refuses exactly the same things, through the same rules. An
  id from before the switch is found there, not inside `system_settings/` — which the Help and the
  restore dialog do not say, because they name only the new path. Retire this bullet with the
  transitional row in §4.5.

Also archive a **single file from its Details panel** — the only route to archiving something you
have not ticked, and a different component from the toolbar's.

#### B2. Request the restore — the point of no return

**Ask before pressing this. Billed on request, uncancellable, 3–5 hours.**

**Restore Archived Data** → paste nonsense first: an inline error names what a valid id looks like,
and the submit control is **never merely disabled**. Then paste the real id → Restore.

**Within a minute, before you walk away:**

- Download `system_settings/archive/{id}/receipt.txt`. **`Restore requested` already carries a
  timestamp** and
  `Restored to` still reads `-`. That marker is written **before the bill**; if it is absent now it
  never runs before the money is spent.
- A `restore_started` notification arrives — the app's only "started" notification, emitted where
  the bill begins. **No link** on this one.

Then leave it. Check back at roughly **1 h, 3 h and 5 h** — Phase C fills the wait.

#### D. When it completes

| Assertion | How |
|---|---|
| A terminal notification: `Restored N files (X MB) to your space, back where they came from. The archive has been cleaned up.` | Its **link works** and lands in the space with the files back. |
| Every file is back at its original path, **including any empty folder** the archive carried | The listing. |
| `system_settings/archive/{id}/` **still holds its receipt** | The folder survives the restore by design — the receipt is rewritten, never deleted, and it is the only durable record of the archive. A folder that vanished here is a defect. |
| The **vault** prefix for that id is gone | **Not observable from the browser** — the sweep is of `dat-prod-archive`, which no human principal can read. `owed.md` carries the CLI check; an **`archive swept`** event in `logs/service=archive/` is what you can see. **Not `cleanup`** — this row said that until 2026-08-31, and a reader grepping for it finds nothing and concludes the sweep never ran. |
| The receipt's ARCHIVE lines are **byte-identical to before** the restore, with `Restored to` now filled | A blanked `Requested` line is how you would know the rewrite broke. |
| The loop actually **looped** | `logs/service=archive/` carries multiple `retrieval polled` events **hours apart**, `poll_count` climbing. |
| A **child span** survived the pipe (SPEC-226) | Every assertion about child spans is made against an in-process sink; nothing offline shows one surviving the SQS sink, the sweep's read-modify-write and the day object. In `logs/service=archive/` for this run, find a record with `message: "span.start"` and **`function: "copy-batch"`**, and check its **`parent_span_id` is non-null** and equals the `span_id` of the `copy-objects` record in the same `trace_id`. A null parent is the failure that matters — it is what a span emitted where the trace context does not reach looks like, and it reads as instrumented. The same check works per plane: `write-roster` under `service=shared-space`, `download-results` under `service=results-conversion`, `athena-run-ddl` under `service=table-builder`. |

**Owed regardless of how well this goes:** the `Restore` header's format, the
`GLACIER`-stays-`GLACIER` property, and `head-object` confirming the restored object came back at
`STANDARD`. Nothing the UI or the audit trail reports settles them. See `owed.md`.

#### The refusal worth staging, if there is time

The load-bearing one, and it needs a second retrieval. Re-create one archived file at its exact
original path **while the restore is waiting**, then let it finish.

- The execution fails at `ReCheckDestinationClear` — not at the first guard, which passed hours ago
  and correctly.
- The notification starts **"Couldn't restore that:"** (not "Couldn't archive that"), names the path
  **relative to the space root**, says there may be more, and says the files **"have already been
  retrieved from long-term storage and will stay ready for a few days"**. That last clause is how
  you tell the second guard from the first.
- **The assertion this exists for:** the file you wrote is **still there and still yours**. Without
  the second guard the copy-back would have overwritten it, reported success and swept the vault —
  versioning is off, so unrecoverably.
- The archive prefix is **intact** — nothing is deleted on the refusal path.
- Clear the file and re-request: it completes in **minutes, not hours**, because the objects are
  still retrieved. That is the fact the refusal's wording promises, and this is the only place it
  is observable.

**Do not proxy a `head-object` from the UI to decide whether retrieval started.** A refusal that had
already begun retrieval looks *identical* there, and being wrong costs 3–5 billed hours. The audit
trail answers it — `owed.md` carries the query and the `IsLogging` precondition.

### 4.12 Notifications

| Assertion | How |
|---|---|
| Every background operation produced **exactly one** notification per outcome | Count them against the operations you ran. |
| The unread count is right after a reload | Reload and read the bell. |
| Every link lands in the right place **in the right space** | Click each one. A link carrying `?space=` that resolves to your personal space is the failure mode. |
| A failure notification never carries raw AWS text | Read the wording of any refusal you staged. |
| The requests queue deduplicates **per recipient** | From a read-only CLI, `aws sqs get-queue-attributes` on the notifications requests queue with `--attribute-names DeduplicationScope` answers `messageGroup`. Read the named attribute from the JSON output: text output drops columns. |
| **Following a `/files` link refreshes the folder it lands on** | A cross-producer mechanism since SPEC-223, not a results-conversion behaviour: the send and archive planes' links carry it too. Have the folder open in another tab, run an operation that writes into it, then follow the notification's link — the file is present **on arrival**, without a manual refresh. The `Review conflicts` control on the same row does it as well, since it resolves to the same listing. |

### 4.13 Help

- Each section's guide count matches what shipped — the Data Explorer section has **five**.
- The filtering guide's callout says plainly that each apply runs against Athena and scans data.
  That is the one thing a user cannot infer from the UI.
- Nothing promises a chart, cell editing, named filters, a References panel, or loading a `.sql`
  back into the Explorer.

**The contextual panel (SPEC-207) — the two things jsdom cannot decide.**

- On `/files`, activate the header help control (it is a *button* named `Help for this page`, not a
  link). Put focus on the panel's `Open the full guide` link and press **Tab**: focus must return to
  the first control inside the panel, not escape to the page behind it. jsdom reports no layout, so
  the unit suite can only assert containment.
- Narrow to 375px and open the panel on `/files`. It must fill the viewport, and the page beneath
  must not scroll sideways — drag horizontally and confirm nothing moves. At ≥900px the panel is a
  right-hand sheet with the page still visible beside it, and the close control is reachable at both
  widths without scrolling.
- While you are there: the panel on `/data-quality` is headed **Files** by design, and
  `/help#delete-space` opens the Help page at Shared connections with that one card expanded and
  scrolled to.
- **Open three or four guides at once** on `/files`, where the section has ten. The panel must
  SCROLL; no card may lose height to the ones you opened. The cards are `shrink-0` for this, and
  jsdom can only assert the class — every rect there is 0×0, so a squashed card and a whole one
  measure the same. While you are scrolled, check that a CLOSED card's title and subtitle are each
  one line ending in an ellipsis where the text is too long, and that the card you have open shows
  both in full. Then open `/help` itself and confirm the SAME closed cards wrap rather than clip —
  the clamp is the panel's, not the card's, because that page scrolls the document and its text
  column is narrower than the panel's.
- **Measure the panel's targets, because no suite can.** axe's `target-size` rule was enabled (it
  is tagged `wcag22aa`), and with no layout in jsdom a probe through the project's own axe config
  put it in `passes` — a pass it never evaluated. It is **disabled** now, in
  `RULES_JSDOM_CANNOT_DECIDE`, because the rule *running* was the hazard: asking "do we assert
  target size here" got yes. What replaced it, `src/lib/targetSize.test.ts`, sees only a control
  sized from the spacing scale — nothing with a text-derived height, and never the spacing
  exception. So this measurement is still the only one that is real. In the browser console with
  the panel open:
  `[...document.querySelector('[role=dialog]').querySelectorAll('a,button')].map(e => [(e.textContent.trim() || e.getAttribute('aria-label')).slice(0,24), e.getBoundingClientRect().height])`
  (the `aria-label` fallback is not optional — the close button is icon-only and prints an empty
  name without it). Anything under **24** is a *candidate*, not yet a finding: SC 2.5.8 exempts an
  undersized target that nothing crowds. Against a neighbour that is itself ≥24 the test is a 24px
  circle centred on your target not reaching that neighbour's box; against a neighbour that is
  ALSO undersized it is circle-to-circle, so the two centres must be 24px apart — the stricter
  half, and the one a quick check drops. Report what you could not decide rather than calling every
  undersized control a violation; an isolated small target is conformant and still worth fixing for
  comfort.

  Three numbers make this easy to get wrong here, all measured rather than read off class names.
  The spacing scale is **3.5px to the unit** (a 14px root against `0.25rem`), so `h-6` is 21px and
  only `h-7` (24.5) and up clear 24. The **type scale is authored in px** and does not scale with
  the root — `text-sm` is 13px on an 18px line-height. And a **bare inline** element's box is the
  font's content area, **not** its line box: an unpadded `text-sm` link measures 15.5px, and
  becomes 18 once it is no longer a bare inline box (any of `inline-flex`, `inline-block`, `block`
  — leaving bare inline is the mechanism, not becoming a flex container). So a control with no
  height class at all can be under the minimum with no suspicious number anywhere in its markup.
  The 15.5 is font-dependent — the system fallbacks give 15.0 — so re-measure rather than reusing
  it.

- **The two targets pinned to an absolute 24, measured the same way.** On `/files`, **select an item
  first** — the toolbar disables **Send to…** at zero selected — then open it, add a recipient, and
  measure the chip's ✕:
  `document.querySelector('[aria-label^="Remove"]').getBoundingClientRect()` must be **24 x 24**.
  Not 24.5: that is what the rem scale gives, and it is what a restyle normalising `h-[24px]` back
  to `h-7` would leave. On `/files` no other control's accessible name begins with "Remove", so the
  bare selector is unambiguous there and nowhere else — on `/connections` it would hit the roster.
  Then on `/query` with history showing, at ≥900px:
  `[...document.querySelectorAll('[aria-label="Open this query in the editor"],[aria-label="Re-run this query"]')].map(e => e.getBoundingClientRect().height)`
  — both **24**. (Below 900px the same row renders View / Run at 38.5px, which is the mobile floor,
  not this check.) Both sites also passed SC 2.5.8 via the spacing exception *before* they were
  pinned, so a regression here restores conformance-by-luck rather than breaking it — which is
  exactly why no suite failure will ever tell you, and why the number is checked here. A source
  tripwire in `sharedPrimitives.guard.test.ts` catches the textual edit; only this catches the
  rendered size.

- **The file details sheet's actions, below 900px.** On `/files` at 375px, open a file's Details
  and run the one-liner above with the sheet open: **Download**, **Rename** and **Archive this
  item** each read **38.5**. They stack in a flex column there, where a `flex-1` without its
  `tablet:` prefix replaces the declared height with the text's, and they read about 20, under 24.
  It shipped that way once, and no suite can see it: jsdom has no layout.

**The Inline exception does NOT cover a breadcrumb trail — settled 2026-09-01, and what would
re-open it.** SC 2.5.8's Inline exception reads "the target is in a sentence or its size is
otherwise constrained by the line-height of non-target text", and the W3C Understanding text gives
one example, a link inside a paragraph, with the rationale that reflowing prose makes a link's
position unpredictable to the author. A crumb trail is neither half of that. It is not a sentence —
it is a `<nav>` holding an `<ol>` of controls, whose non-target text is the `/` separators and the
final `aria-current` crumb. And
its size is not *constrained* by that text's line-height, which was settled by measuring rather than
arguing: the crumbs are flex items, so flooring one at `min-h-[24px]` takes it from 18px to 24px
while the separator beside it stays at its own 18px line-height, and the row simply grows. A
constraint you can lift by editing one class is not a constraint. **What would re-open this:** laying
the crumbs out as inline text inside a real sentence, where raising one would change the leading of
the text around it. The trail being visually compact is not the test.

**The controls measured out of the register, and what to spot-check.** All were measured at the 14px
root against the built stylesheet. Both crumb trails (`/files`, and the destination picker in a
copy/move dialog) now carry `min-h-[24px] min-w-[24px]` — **both axes**, because a one-character
folder name draws a 7px-wide box and two of those sit 22.8px apart, inside each other's circle.
Confirm a one-character folder crumb is at least 24×24, and that a long folder name still shows an
ellipsis: the fix deliberately does **not** use `inline-flex`, which makes the label an anonymous
flex item and stops `truncate` rendering its `…` while still clipping, so the regression looks like
a slightly shorter name rather than a broken one.

**Then check the trail WRAPS, which is the half a target-size check will not tell you.** Flooring
the crumbs widens every short one, and `/files`' trail did not wrap before this — so at 375px a
path six or more folders deep ran its content past the nav, clipped the folder you are standing in
at the screen edge, and put the whole document into a horizontal scroll, which is an SC 1.4.10
Reflow failure traded for an SC 2.5.8 one. Narrow to **375px**, then to **320px**, and walk into a
deep folder: the trail must wrap onto a second row with the current folder fully visible, and the
page must not scroll sideways — drag horizontally and confirm nothing moves. **Confirm `innerWidth` actually changed before believing any of this** — §1's stale-viewport trap is exactly this shape, and a resize that silently did nothing leaves a desktop-width trail that wraps at no width and passes. At 320px with nine
segments it takes three rows and pushes the file list down about 47px, which is the accepted cost.
The refresh button beside the trail is centred against the whole block, so it sits lower than the
first crumb row once wrapped; that is expected, not a bug. The two tab strips' ✕ closes are `h-[24px]
w-[24px]` inside a tab whose own `h-7` did **not** change. That was tried and reverted, and the
reasoning is worth keeping: `h-7` is a 24.5px BORDER box over a 22.5px CONTENT box, so a 24px ✕
stays inside the tab's outer bounds (measured: 0.25px to spare) but overhangs the content box by
0.75px a side onto the 1px border, where its own hover fill paints over it. Raising the tab to
`h-8` removes that 0.75px artifact and costs a visible 3.5px mismatch against the `+` button, the
bar buttons and `ResultTabs`, all of which are `h-7`. The artifact is invisible below about 8x
magnification; the mismatch is not. Nothing about the ✕'s conformance depends on the tab. A 24×24 target needs **no**
exception, which is what makes the ✕ fixable at all: the exception could never rescue it, since it
sits inside the tab's own box, and that was misread for a while as "unfixable" rather than "not
rescuable". `Toast`'s dismiss and the schema rail's `TableActionsMenu` trigger are also 24×24 now;
both already conformed via spacing (37.8px and a 14px centre-to-box against the row button), so
those two are robustness rather than fixes — the menu trigger was clearing the requirement by
2px, on a `gap-1` rail row. Do not repeat the claim that a `gap-0.5` there would have broken it:
1.75px + half the 21px trigger is 12.25px, which still clears the 12 the exception needs. Only
`gap-0` would have, and the honest statement is that it was the app's tightest pass, not that a
named edit would have ended it.

### 4.14 Feature flags

**The whole point is that the app cannot tell you the answer.** Every compiled-in default is `true`,
so a permanently-blocked read renders *exactly* like a healthy all-on environment. "It looks fine"
is not a pass.

**The read is real** (all flags on):

1. Hard-reload signed in. In the network panel, find `GET $API_ORIGIN/v1/feature-flags` → **200**.
   That status is the assertion. `ProtectedLayout` mounts the hook and discards the result precisely
   so this request exists to be observed. A **404** carrying `"code": "NotFound"` means nothing has
   ever been published to this bucket — a deploy defect, and the app renders all-on over it.
2. The response is `{"body": …, "etag": …}`, and **`body` is a string**: the document's JSON text,
   passed through unparsed. It must be non-empty and, parsed, carry `"version": 1` and a `defaults`
   object — the reader refuses an empty `body` or any other `version`, silently, into the all-on
   defaults. That, with the 200, is the whole of the evidence available in production — the hook's
   own `ready`/`fallback` console line is behind `import.meta.env.DEV` and prints **nothing** in a
   production build, so its absence says nothing either way.
3. `_config/` is **not browsable** in the file browser — the API lists only a space the caller's
   claims authorize, and `_config/` belongs to none. Not IAM: the portal role may list `_config/`,
   which is what lets a never-published document answer 404 rather than a denial.

**A flag actually hides things** (one sitting; step 3 restores the environment):

1. Run the precondition row's two reads at the top of this file now, and note the image tag.
   Set `environments.prod` to `{"query": false, "dataQuality": false}`. Merge, wait for **Publish
   Config**. **Do not redeploy the app** — that is the point.
2. Hard-reload. Expect:

   | Where | Expect |
   |---|---|
   | Topbar | **Files** and **Connections** only — Query and Data quality *absent*, not greyed |
   | `/query` typed in | The **"Query isn't available"** page with a working **Go to Files** link — **not** "Page not found" |
   | Files, in a folder | **No "Create table"** on the toolbar |
   | Files, one item selected | **No "Check data quality"** in the selection toolbar |
   | `/help` | Neither the **Query** nor the **Tables** section; in **Files**, *"Check data quality"* and *"Find a past quality check"* are gone while *"Upload files"* remains |
   | Hamburger at 400px | Files, Connections, Notifications, Help — and not the two hidden tabs. A tab hidden in the topbar and present here is the feature still one tap away. |

3. Set it back to `{}`, merge, wait for **Publish Config**, hard-reload. Everything returns. Now
   read the image tag again: **it must be the tag step 1 noted.** Read it after the reload rather
   than waiting on **Deploy SPA image** — it runs on every push, so seeing it proves nothing, and
   the question is which image served these screens, not what that run does next. Compare the tag,
   not the task-definition ARN: a config-only merge may re-point the service, which registers a new
   revision around the same image. A new tag means a new bundle may have served what you saw — an
   input to the image changed since the commit the service was running, someone dispatched the
   workflow, or it could not read that commit — and the sitting proves nothing; run it again. A
   push only ever moves the tag forward, which is what lets one read stand for the whole sitting;
   a re-run of an older Deploy SPA image run can move it back, so a re-run or a dispatch during
   the sitting voids it whatever the tag says. Hidden in step 2 and back in step 3 on one image is
   what proves the app reads the document at runtime and picks its `prod` block by the
   `environment` key the container renders into `/config.json` — nothing in the all-on pass can.

**`asyncFileOperations` is the sixth key and it is the odd one out** — a kill switch, not an area,
so what it hides is a behaviour rather than a tab. Its own sitting, and §4.2's async rows are what
it is checked against:

1. Set `environments.prod` to `{"asyncFileOperations": false}`; publish; hard-reload.
2. In **Help**, the *Files* section keeps *"Rename, move, copy, or delete"* and loses *"When a move
   or copy is refused"*. That is the only visible surface until you act.
3. Select an ordinary folder — not one of §4.2's managed folders, whose own reasons come first.
   Copy, Move and Delete are `aria-disabled="true"` with `disabled === false`, and each carries the
   reason as its tooltip: *"Folders and multi-item actions are handled by the file operations
   service, which is not available."* — the same for any selection of more than one item. No
   `POST $API_ORIGIN/v1/enqueue/file-ops` fires and no in-progress card appears: the switch turns
   the capability off, and the browser has no recursive copy to fall back to. A single file still
   moves, through `POST $API_ORIGIN/v1/objects/move`, exactly as it does with the switch on.
4. Set it back to `{}`, publish, hard-reload, and confirm §4.2's async rows behave again.

**`resultsConversion` is the seventh key and the third kind** — neither an area nor a kill switch
but a **presentation** flag over one control, so what it hides is three options in one `<select>`
and nothing else. It takes nobody's access away: the enqueue route is live and ungated either way.

1. Set `environments.prod` to `{"resultsConversion": false}`; publish; hard-reload.
2. **Save results to my files**, on **both** the Query workspace and the Data Explorer: the
   **Format** select is **absent** — not present-and-disabled — and the button reads **Save here**.
   Saving writes a CSV exactly as it did before this key existed.
3. **A notification from a conversion run while the flag was on still links**, and following it still
   refreshes the folder. Notifications are never gated: the record of what happened outlives the
   surface that would show it.
4. Set it back to `{}`, publish, hard-reload, and confirm the select returns on both surfaces.

### 4.15 Responsive, and the 400px pass

~~**Corroborated in Chrome ≠ discharged.** Behavioural checks (execution counts, SQL text, refusals)
are waived to Chrome by user decision. **Rendering is not** — sticky columns, menu clipping,
sheet-vs-panel and toolbar wrap are exactly where Safari differs. The list below is owed in Safari,
at **400px via DevTools device toolbar**.~~ **Superseded 2026-09-01 (user decision):** the
deployment's audience has no Safari, so a Chromium pass discharges rendering too (SPEC-202's §9
criterion records the decision). The list below is still owed at **400px via the DevTools device
toolbar** — the width is the gap, not the engine.

**The Save-results modal is checked across a BAND, not at one width (SPEC-223).** A responsive fix
has a band rather than a width — hiding something at `tablet:` has fixed 375 and broken 900–1023
here before. Open it at **375**, **768**, **899** and **900**: the file-name, **Format** and space
fields each stay full-width and stacked at every one of them, the format select never sits beside
the name field, and the primary button (**Save here** / **Convert and save**) keeps its height —
`h-9`, which is **31.5 px** at this app's 14 px root, the same as in the Copy, Move and
Start-quality-check dialogs, since the button is `DestinationPicker`'s. jsdom measures no geometry
at all, so this is the only place the layout is checked.

**The top bar and the Files selection toolbar, across the `tablet` band.** Both switch their words
on at 900 px, which makes the band just above it the tightest in the layout. On `/files`, signed
in and foregrounded — or reloaded after each resize with `matchMedia` pinning the exact width,
§1's stale-viewport row — with a classic 15 px scrollbar, since an overlay one hides the worst case.
On a Mac set to overlay scrollbars, inject `html{overflow-y:scroll}` and
`::-webkit-scrollbar{width:15px}` and confirm `clientWidth` is `innerWidth − 15`. At `innerWidth`
**900, 930, 959, 1024 and 1299**:
`document.documentElement.scrollWidth` equals `clientWidth`; the **account button's** right edge is
within `clientWidth`; no tab label and no toolbar label sits on two lines; and **Delete** ends inside
the toolbar's border. Then at **1300**: the tab icons, the toolbar glyphs and the username are back.
And at **375** (the device toolbar — Chrome's window stops near 606) with a three-digit selection:
the toolbar is glyph-only and the count reads whole, on two lines if it must, never as "12…".
Checking only the page's `scrollWidth` is not enough — a row that clips passes it. *Quicker, and
not a discharge:* a same-origin `srcdoc` iframe of the page's own `#root` and stylesheets, set to
each width inside one signed-in tab, answers the same questions without a resize or a foreground —
its media queries follow the iframe's width — and it reproduced the 2026-09-10 sweep's 945 px page in
an 885 px `clientWidth` exactly. Mount-gated markup is whatever the tab rendered, so below 900 it
shows the desktop file table where the app mounts a card list.

- The **sticky pinned column block** — pin, scroll right, confirm it stays put and its background is
  opaque over the scrolling cells.
- A column **⌄** menu near the grid's right edge is **not clipped**.
- Below `tablet` the header menu is unreachable by design — **Order and filter** is the way in, and
  every sort and filter must be settable from that dialog alone, at 400px.
- The **Value panel** renders as a sheet, not a side panel; **Calc and Grouping stack below** the
  grid.
- The toolbar's controls **wrap rather than overflow**. Count them rather than trusting a number.
- The **Colours** dialog's rows wrap; a gradient's shades are readable against real rendered text.
- A **band boundary** is visible where two striping groups meet.
- An **anchor in a truncating cell** does not push the cell's layout around.
- The **header-drag-onto-Grouping** gesture, which no test performs.
- **Record view is the default** on an unchosen tab at this width.
- Every dialog is **392px** at this width (root font-size 14px), centred, with no horizontal page
  scroll — and the suggestion listbox stays **inside** its dialog, not overhanging it.

### 4.16 Dark mode (SPEC-210)

The palette itself is measured offline by `lib/contrast.test.ts` in both themes, so what a browser
adds is the three things jsdom cannot see: the first paint, the editor's own state, and whether the
whole app actually looks right.

1. **No flash of light.** With **Dark** already chosen, hard-reload (⇧⌘R) a deep link such as
   `/query`. The page must arrive dark. A white flash means `/theme-init.js` did not run before the
   first paint — check the Network panel for a **200** on it and a `Cache-Control: no-cache`, and
   the Console for a CSP refusal (an inline initialiser is the failure this shape exists to avoid).
2. **The switch, and where it lives.** Signed in or out, at any width: the **half-circle** button
   labelled **Theme** on the top bar, beside Notifications — the three choices carry a tick on the
   current one. Narrow below 900px and the word goes but the button stays, and there is no copy in
   the ☰ drawer and none in the account menu. It spent one release inside that menu; the
   half-circle on the bar is the state to check.
3. **System follows the OS.** Choose **System**, then flip macOS *Appearance* between Light and
   Dark with the tab in the foreground. The app must follow **without a reload**. Choose **Light**
   and flip again: it must not move.
4. **Monaco keeps its place.** On `/query`, type a multi-line statement, put the cursor mid-line and
   scroll the editor. Switch the theme. The text, the cursor and the scroll position must all
   survive — this is the half `SqlEditor.test.tsx` cannot assert, because it stubs the editor.
5. **Walk the surfaces in dark**: Files (table and, below 900px, the card list), the Query workspace
   with a result, the Data Explorer with a colour rule and a **gradient** rule applied, the schema
   rail, Help, Notifications, the landing page signed out, and one danger dialog. Nothing washes
   out; the landing page's indigo call-to-action strip is deliberately unchanged by the theme.
6. **Shadows.** A modal and the Menu popover must still read as raised against the dark page. If
   they look flat, the `--shadow-tint-*` override is not landing.
7. **Target size, in the browser and not in the suite.** Read off the built CSS, not off the class
   names: `--spacing` is `.25rem` against a **14px** root, so a spacing-derived size is 12.5%
   smaller than it reads — `h-8` is 28px, `h-7` is 24.5px, `h-6` would be 21px and fail WCAG
   2.5.8's 24px. **Type does not scale the same way**: `--text-sm` is authored as `13px` with an
   18px line-height, so a PADDED control with no height class is its line box plus padding, at any
   root size — but one with no padding either is smaller still, because a bare inline box is the
   font's content area rather than its line box (15.5px for `text-sm`, measured). §4.13 owns that
   rule in full, along with SC 2.5.8's spacing exception, which is what decides whether an
   undersized target is a violation at all. The three to measure, and what they should be:
   the signed-out header's theme button `h-8` → **28px**; the account-menu trigger, whose avatar
   is `h-8` → **28px** and which additionally carries an absolute `min-h-[24px]` so the floor
   survives a change of root size; and a menu row, which has **no height class at all** — 18px
   line box plus `py-2` (2 × 3.5px, twice) → **32px**. The drawer's three `h-7` options are gone
   with the drawer's theme block. axe's `target-size` rule is **disabled** in the suite,
   because with no layout engine jsdom made it report a pass it could not make; the static sweep
   that replaced it sees the drawer option's `h-7` directly and the header button's size through
   `IconButton`'s pinned `SIZES` map, and is blind to the menu row — so a browser is still the only
   place that last number is real. §4.13 carries the rule; the coding side is
   `apps/portal/info/best-practices/accessibility/accessibility.md` → *Target size in this app*.

### 4.17 Give feedback (SPEC-211)

Write-only: there is no read surface, so **the only way to see whether a submission landed is the
AWS CLI**, and the account that can read the admin bucket is not the one in the browser. That
split is why most of this is owed rather than run — see `owed.md`.

| Do | Expect |
|---|---|
| At 1300 px or wider, signed in | Open the **kebab** beside your name (below 1300 the name is withheld and the kebab sits beside the avatar): **Give feedback** is the first item, with an icon, above a separator and **Sign out**. Help and the theme are on the bar, not in here. |
| Narrow to 375px | The bar's three words (Help, Notifications, Theme) go and their icons stay; the menu is unchanged — **Give feedback** is in the same place. The ☰ drawer carries no copy of it. |
| Open it | A dialog with **no category preselected**, an empty message, and a line naming the page you were on. **Send** is disabled. |
| Choose a category, leave the message empty | **Send** stays disabled. Type a space or two — still disabled. |
| Type a message, press Enter inside it | A newline. It does **not** submit. |
| Focus the category select and press Enter | It submits. |
| Send | The dialog closes and a toast reads the thank-you. Reopen it — the message is empty, not the last one. |
| Reopen, and watch the network panel | Exactly **one** `POST /v1/feedback`, answering 200 with `{submittedAt}`. The request body carries `category`, `message` and `route` — and **no username of any kind**. |
| Navigate to another page with the dialog open, then send | The `route` in the body is the page you **opened** it on, not the one you ended on. |

**Then, with CLI credentials that can read the admin bucket** (a different identity from the
browser's — see `owed.md`):

```bash
aws s3 cp "s3://$ADMIN_BUCKET/feedback/$(date -u +%Y/%m/%d).json" - | python3 -m json.tool
```

Expect one object for today, `version` 1, and your submission in `entries` with the username
taken from your token, an `eventId`, and the `route` you were on. Submit twice more and confirm
all three are present, in order — the append preserves what is there.

### 4.18 The front door, and the browser's network surface (SPEC-192 → 202)

**Folded in when Arc B closed** (2026-09-02, from `arc-b-api-container-e2e.md`, which is deleted —
its per-spec sections and their dated results are in git history and in [`sessions.md`](sessions.md)).
`portal.dataquarry.app` is a container on Fargate and **the only front door**; the CloudFront
distribution and the Identity Pool are destroyed. Run this section on any change to the API, the
image, the CSP, the origins or the credential path — none of it is observable offline.

**Classify every other arc's owed checks against this one before trusting them.** Anything asserting
a URL, a CSP, a browser AWS call or a bucket-CORS behaviour was **invalidated by the origin change
and must be re-run**; anything asserting a Lambda, a state machine, an IAM simulation or a `logs/`
record is **unaffected**. Leaving one unclassified is how a discharged check silently becomes stale.

**The two cheap CLI checks, worth a glance on every run.**

- `curl -s https://api.dataquarry.app/healthz` returns `{"status": "ok", "version": "<sha>"}`. The sha
  is the commit whose image the function runs. One image carries the whole fleet and CI points
  every function on every run, so it is HEAD unless a deploy failed — there is no per-function
  "changed since" any more, and the older-sha case now means a failed or skipped deploy rather than
  an untouched function. Resolve it with
  `git log -1 --format=%h -- lambdas/api/ lambdas/control-plane-common/`, never by grepping
  `lambdas/api/` alone: on 2026-09-01 healthz reported HEAD because that commit changed
  `cpcommon/config.py`, while `lambdas/api/` alone pointed four commits back. Reading it either way
  round — as necessarily HEAD, or as necessarily the api-only sha — makes a healthy API look broken.
- `curl -sSI "$APP_URL"` carries the whole header set: `Content-Security-Policy` (never
  `-Report-Only`), HSTS `max-age=31536000; includeSubDomains` (**no** `preload`), `X-Frame-Options:
  DENY`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, COOP, CORP, and
  `Server: nginx` — the last three are the container's three deliberate divergences from the
  distribution it replaced. `connect-src` must name `'self'`, `cognito-idp`, **the Hosted UI host**,
  both S3 buckets and `https://api.dataquarry.app`, and must **not** name `cognito-identity.`,
  `athena.`, `glue.` or `sqs.`. A header *name* is not evidence a policy is enforced — that is the
  next check.

**The CSP is enforcing, proved by a positive violation and a negative control.** Paste into the
console on `$APP_URL`:

```js
window.__csp=[];addEventListener('securitypolicyviolation',e=>window.__csp.push(
  {effectiveDirective:e.effectiveDirective,blockedURI:e.blockedURI,disposition:e.disposition}));
fetch('https://athena.us-east-1.amazonaws.com',{mode:'no-cors'}).catch(()=>{});
fetch('/config.json').then(r=>console.log('control',r.status));   // must be 200 in the SAME run
setTimeout(()=>console.log(window.__csp),500);
```

**Expect** one violation with `effectiveDirective: "connect-src"` and `disposition: "enforce"`, and
the control returning **200**. Without the control, a blocked request and a broken network are the
same observation. **The method matters and was wrong once:** CDP/console evaluation is exempt from
`script-src`, **not** from `connect-src` — the older "inject a same-origin `<script>`" recipe is
unsatisfiable under `script-src 'self'` and its failure reads as a broken snippet rather than a
finding.

**The load-bearing negative: the browser makes no AWS call other than presigned S3 bytes.** Record a
window that includes a file listing, an upload, a download, a query and **one enqueue** (an `sqs.`
row counted without an enqueue in the window is vacuous).

**§1's instrument cannot settle this one** — it records `/v1/` calls, `x-amz-target` calls and
non-`GET` S3 calls, and drops every plain `GET` to an undeclared host, which is exactly the class
this check exists to catch. Install this recorder instead, which counts **every** request by host:

```js
window.__hosts={}; const _f=window.fetch;
const bump=(u,m)=>{try{const h=new URL(u,location.origin).hostname;
  (window.__hosts[h] ||= []).push(m)}catch(e){}};
window.fetch=function(...a){bump(a[0] instanceof Request?a[0].url:a[0],
  (a[0] instanceof Request?a[0].method:(a[1]||{}).method)||'GET'); return _f.apply(this,a)};
const _o=XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open=function(m,u){bump(u,m); return _o.apply(this,arguments)};
// at the end of the window:
Object.entries(window.__hosts).map(([h,ms])=>[h,ms.length]).sort((a,b)=>b[1]-a[1]);
```

| Host | Expect |
|---|---|
| `$API_ORIGIN`'s host | **> 20** over a window this wide |
| `$USER_BUCKET.s3.$REGION.amazonaws.com` | **≥ 2, at least one `GET` and one `PUT`** — the presigned bytes, and only those |
| `cognito-idp.$REGION.amazonaws.com`, `$HOSTED_UI` | any — sign-in and refresh are not failures |
| `athena.`, `glue.`, `sqs.`, `cognito-identity.` | **0** each |
| **anything else ending `amazonaws.com`** | **0** — the catch-all, and the only row that can catch a host nobody listed |

Record the numbers, not a tick. The two positive controls are what make the zeros mean anything: a
window with no enqueue and no download in it produces the same zeros as a perfect one.

**Cross-check in DevTools**, whose filter box is the other way to read the same window. Paste the
catch-all as one line — a `-`-prefixed term is an exclusion:

```
amazonaws.com -cognito-idp.$REGION.amazonaws.com -$USER_BUCKET.s3.$REGION.amazonaws.com -$SHARED_BUCKET.s3.$REGION.amazonaws.com
```

The Hosted UI host is deliberately **not** excluded: it is `*.auth.$REGION.amazoncognito.com` and
contains no `amazonaws.com` substring, so it never matches. `$API_ORIGIN` is a custom domain and
does not match either. Do not read a zero from the browser extension's network reader — it has been
observed to see 1 of 13 requests, and every zero-count check passes vacuously against a reader that
drops requests.

**Each S3 request must be presigned, not header-signed** — a header-signed request is the browser
holding credentials, and at the host level the two are identical. Expect the signature in the
**query** (`X-Amz-Algorithm=AWS4-HMAC-SHA256`, `X-Amz-Credential`, `X-Amz-Date`, `X-Amz-Expires`,
`X-Amz-SignedHeaders`, `X-Amz-Security-Token`, `X-Amz-Signature` — SigV4 is pinned in code) and
**no** `Authorization` and no `x-amz-security-token` **header**. Record the family you saw rather
than trusting this paragraph: it has been wrong in both directions.

**A presigned URL is a bearer token, so it must appear in no log.** Sweep the day's
`logs/service=api/` for all six of `X-Amz-Signature`, `X-Amz-Credential`, `X-Amz-Security-Token`,
`AWSAccessKeyId`, `x-amz-security-token`, `Signature=` — all six, always, because a sweep naming
only the family currently deployed goes unfailable the day a different tree changes. **Zero needs
its positive control**: the window must hold real mints, evidenced by `key_length` /
`presign_expires_in` records, or zero means the window was empty. And a **hit is not automatically a
leak** — `error.stack` carries source lines, and `botocore/auth.py` contains all six as literals, so
read the record: a leak carries a signature *value*, a traceback carries the parameter *name*.

**What a signed-in session cannot settle here** — the platform's own verification (the no-NAT pull
read beside a route table, the redirect, target health), the container under real concurrency, and
anything about `/config.json` that the container renders rather than the browser reads. Those are
[`owed.md`](owed.md)'s, and the platform half was discharged 2026-08-26.

---

## 5. Cleanup and write-up

**Cleanup.** Delete the fixture folders, tables, view and saved queries you created — but leave
anything a still-owed check will need, and say in the write-up what you left and why. **Never delete
something you did not create.**

**Write-up.** Add a dated section to the **top** of [`sessions.md`](sessions.md) — not a new file;
`scripts/validate_docs.py` rejects one. Record what ran, under which username, at which width and
browser, with which instruments, and what each check returned. Then update:

1. [`owed.md`](owed.md) — move discharged rows out, add anything newly found unrunnable.
2. The delivery docs that still state the old status.
3. The Fences of the area's `docs/decisions/` file.

**An unrunnable check is a finding, not a failure.** If a step here cannot produce the outcome it
claims, fix the step and say so — that has been the most valuable output of several sessions.
