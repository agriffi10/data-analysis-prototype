# End-to-end validation — the one guide

**One signed-in account, one browser, one pass.** This is the only script for validating the
deployed app end to end. Everything a signed-in session *cannot* settle — a second account, the
CLI, Safari, 400px, a real Glacier retrieval — lives in [`owed.md`](owed.md), which is the ledger
you update when a check moves.

> **This file replaced sixteen.** The per-arc and per-spec scripts (`table-builder-e2e.md`,
> `archive-restore-e2e.md`, `auth-e2e.md`, …) were folded in here on 2026-08-18; their per-spec form
> is in git history, and the evidence they cited is in [`sessions.md`](sessions.md). A spec that owes
> a live check adds it to the matching section below — an arc in flight may keep one script of its
> own, folded in when the arc closes (`docs/process.md` §5 step 8).

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
| `main` is green, and you know the deployed sha | `gh run list --branch main --limit 5`, then `git rev-parse HEAD`. A red **Deploy App** means you are testing something that is not there. |
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
- Anything touching data he did not say is disposable.

Everything else here is safe to run unattended. A missing approval means that part is recorded as
**not attempted** — never as owed-because-broken. **Only ever archive fixtures you created in this
session.**

---

## 1. Instruments

Install after **every full page load**. Client-side nav (nav-tab clicks) preserves them; a
`navigate` does not.

```js
// 1. THE ONE THAT MATTERS MOST — see the trap table.
Object.defineProperty(document,'visibilityState',{get:()=>'visible',configurable:true});
Object.defineProperty(document,'hidden',{get:()=>false,configurable:true});
document.dispatchEvent(new Event('visibilitychange'));
window.dispatchEvent(new Event('focus'));

// 2. Count API route calls, remaining x-amz-target calls, and S3 writes by path.
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
and the panel fills fast. `x-amz-target` now identifies only the SQS enqueues.

Read a downloaded file back **inside the page**; never pull a presigned URL into your context:

```js
const t = await fetch(window.__dl).then(r=>r.text());
JSON.stringify({lines:t.trim().split('\n').length, head:t.split('\n')[0], last:t.trim().split('\n').pop()})
```

### Traps, all measured

| Trap | What it looks like | What to do |
|---|---|---|
| **A hidden Chrome window pauses polling** | One `GetQueryExecution`, then "Running…" forever. `hasFocus()` true, `visibilityState` `hidden`. | Instrument 1. Without it you will file a hung-query bug that does not exist. |
| **`resize_window` reports success and changes nothing** | "Successfully resized to 400x800" while `innerWidth` stays 1512 and every media query still matches desktop. | Never trust the call — assert on `matchMedia`. Chrome's minimum window width is 606px, so **400px needs DevTools device toolbar (⌘⇧M)**. |
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
    with open(name,"w",newline="") as f:
        wr = csv.writer(f, lineterminator="\n")   # LF, NOT csv's default CRLF
        wr.writerow(header); wr.writerows(rows)

# partitioned: part0 sorts first INSIDE THE FIRST PARTITION and carries the extra column
w("part1.csv", ["id","region","amount"], [[i,regions[i%4],i*7] for i in range(1,11)])
w("part2.csv", ["id","region","amount"], [[i,regions[i%4],i*7] for i in range(11,21)])
w("part0.csv", ["id","region","amount","channel"],
  [[i,regions[i%4],i*7,"web" if i%2 else "store"] for i in range(21,31)])
w("part00.csv", ["ID","Region","Amount"], [[i,regions[i%4],i*7] for i in range(31,41)])

# data quality: agreeing pair, and one that disagrees on columns
w("dq_a.csv", ["id","region","amount"], [[i,regions[i%4],i*3] for i in range(1,21)])
w("dq_b.csv", ["id","region","amount"], [[i,regions[i%4],i*3] for i in range(21,41)])
w("dq_bad.csv", ["id","zone","amount"],  [[i,regions[i%4],i*3] for i in range(41,61)])
PY
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
| `dq_agree/` | `dq_a.csv`, `dq_b.csv` | data-quality clean control |
| `dq_disagree/` | `dq_a.csv`, `dq_bad.csv` | cross-file finding |
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
| Sign in through the Hosted UI | Lands on `/files`. Managed Login v2 branding. |
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
| Open **Details** | Size, type, timestamps, metadata; sizes read consistently across every screen (one TB ceiling, so 3 TB never reads `3072.0 GB` on one screen and `3.0 TB` on another). |

**The managed folders, each by its own rule.** For every refusal below assert all five:
`aria-disabled="true"`, `disabled === false`, `tabIndex 0`, the exact reason string, **zero**
`[role=alertdialog]` opened, and — with instrument 2 — **zero requests issued**.

| Folder | Rule |
|---|---|
| `athenaresults/` | Visible; undeletable; not a paste target; **Archive** disabled with a reason naming it. |
| `saved_queries/` | Ordinary inside (upload, subfolders, delete a file); the **folder itself** refuses Delete and Rename. |
| `archive/` | Read-only throughout — see §4.11. |

**The control is not optional.** Select `marker_control/` beside each one: both controls enabled,
and its confirm **does** open. Without it a generic failure reads as the guard working.

**The async switchover — the boundary is "exactly one file", never "is it a folder".** Two rows
above are the whole of it, and getting the boundary wrong is invisible from the UI, so check the
Network tab (instrument 2): a single-file gesture issues **one call to the API** —
`POST /v1/objects/copy`, `POST /v1/objects/move` or `DELETE /v1/objects` — and everything else
issues **one** `SendMessage` to the file-ops queue and nothing more. **Zero direct AWS calls appear
for either**, other than presigned S3 bytes on an upload or a download.

| Do | Expect |
|---|---|
| Move a folder, then navigate away and back | The in-progress card is still there — it lives at the app shell, not on the page. |
| While it runs, try Copy / Move / Delete / **Archive** in that space | All four `aria-disabled` with a reason naming the in-progress list. **Check quality** and **Send to…** stay enabled — they read, and this lock does not cover them. |
| Wait for the notification | The card reads *Finished*; the space accepts operations again. |
| Press **Refresh this folder** (or leave the tab and come back) | The listing now matches. It does **not** update on the notification — that is deliberate, and §4.12's poll is why. |
| Dismiss a card by hand | It goes, and the space is free again immediately. |
| Copy a FOLDER into the folder it is already in | The auto-number prompt appears **once** (one `HeadObject`), and confirming enqueues with that name — it is not copied in the browser. |
| Open **Details** on a folder the plane has just deleted | *This folder no longer exists*, and Rename/Archive are gone. Not merely an empty panel. |

**The conflict round trip.** Move something onto a name that already exists, then open the
notification and use **Review conflicts** — including from a tab that did not submit it (paste the
`?requestId=` link into a new tab). Expect the colliding items named, a bounded sample, and
*Overwrite* saying in words that it cannot be recovered. A rename offers **Use a different name**
instead, which re-submits safely. Confirm only the conflicted items are re-sent.

**The kill switch, which now switches a capability OFF rather than to a slower route.** Run the
async-off half of §4.14 (`{"asyncFileOperations": false}`, publish, hard-reload). A single-file
copy, move, rename, delete and download are unaffected. A **folder** copy, move or delete is now
**refused**, per item: the operation summary names each folder with *Folders are handled by the file
operations service, which is unavailable right now*, and any files selected alongside it still go
through. No card appears, and no `SendMessage` is issued. Restore the flag in the same sitting.

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
| `curl` a `PUT /v1/objects/content` under `{root}archive/` | Refused — and record it as the **route-layer** refusal it is. It is byte-identical to an IAM denial and is issued before IAM sees anything; the credential-layer half is SPEC-196 Phase 5 item 6's dated `_identity/self` result, **cited, never re-run here**. |
| `curl -X OPTIONS` the presign path from a foreign `Origin`, from the SPA origin, and from the CloudFront origin | No `access-control-allow-origin` for the foreign one; allowed for **both** of the others — the CloudFront one is the rollback FR-011 preserves. `DELETE` and `HEAD` are still in `access-control-allow-methods`; SPEC-202 is where that changes. |
| Read one record in `logs/service=api/` | Present: `env`, a real build sha, `route_id`, `actor`. **Absent:** any bearer substring, any email, any object body, and any presigned-URL signature — sweep for **`AWSAccessKeyId=`, `x-amz-security-token=` and `Signature=`**. **Not `X-Amz-Signature`:** this deployment's presigned URLs are SigV2 and never contain that string, so a sweep for it passes on a log that is leaking (measured 2026-08-31). |

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
| Broken SQL / missing table / a permission failure | Three distinct readable messages, editor intact, **no raw AWS/Athena text anywhere**. |
| Open the schema rail | Your own database plus every shared space; expand shows columns; the per-table **⋮** offers source files, DDL, refresh, share, drop, **Explore data**. |
| History | Records and re-runs. |
| **Save results** | Writes a CSV where asked, with an overwrite confirm. With `sharedWorkspaces` off it offers **My files only** — a colleague's space must never be a write target. |

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
| Read one record in `logs/service=api/` for a catalog route | Present: `env`, a real build sha, `route_id`, `actor`, `sql_bytes`, `state`. **Absent:** the SQL text, any `stateChangeReason`, any result cell, any bearer substring, any email. Records arrive on the 10-minute sweep — wait for it rather than concluding from an empty query. |
| **The load-bearing negative**, after exercising this section and §4.5 end to end | **Zero** requests to `athena.*.amazonaws.com` and `glue.*.amazonaws.com`. |
| The **first** invocation after a deploy | Succeeds. Cold start is where a layer imported and not attached fails, and it is silent everywhere else. |

**Safari**, since that is the browser in use; a Chromium pass corroborates and cannot discharge.

### 4.4 Tables — build and refresh

**Build.**

| Do | Expect |
|---|---|
| Build from `explorer150/` | Notification, appears in the rail, returns rows, all columns text. |
| **Create table** at a space ROOT | The button is `aria-disabled` with a reason about the folder being read whole — the dialog never opens. A table there would SUCCEED over `athenaresults/` and friends, which is what makes this worth blocking. |
| Build from a folder whose CSV header has `Order ID` | Refused by notification, **naming the column**. Refused deliberately even though it would work today — one rule everywhere. |
| Build from a folder whose header has `Total` and `TOTAL` | Refused, naming **both**: Athena lowercases, so they are one column to it and two to everything else. |
| Build from a header with `_id`, `2024_total`, `select` | **Builds.** Leading underscores, leading digits and reserved words are quoted, not refused. |
| Refresh a table whose header the rule would now refuse | **Refreshes.** Creates only — refusing would strand a table already in the catalog. |
| Build from `partfix/` with key `year` (string, `2025, 2026`) | **One** Athena statement, no repair step, and `WHERE year = '2025'` returns rows immediately. |
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
| 5 | **Next**, **Prev**, **Next** on the pager | **Zero** `StartQueryExecution`. `GetQueryResults` calls are expected and free. The running total does not move. |
| 6 | Clear the filter, then apply the **same** one again | **Zero** new executions, and the line reads *"Loaded from an earlier run in this tab — nothing more scanned"*. Total unchanged. |
| 7 | Click an `O'Brien` cell → **Filter by this value** | **Rows come back** — count them in the unfiltered grid first. **An empty grid here is a FAILURE.** **Generated SQL** reads `WHERE "owner" = 'O''Brien'`. The wrong escaper fails *silently*, as a predicate that matches nothing. |
| 8 | Type `qty >>> 5` into **Filter expression** → **Apply** | Error banner, the **previous** rows still beneath it, toolbar and expression bar still there. |
| 9 | History **back**, then **forward** onto the failed step | Back: the good rows, **no** re-run. Forward: *"This set of filters failed last time it ran. Nothing has been run."* + **Run it anyway**, and **zero** executions on arrival. |
| 10 | **Grouping** → group by `region`, `COUNT(*)`, tick **Show percentage**, Apply | **1** execution, changed figure. **Generated SQL** is a real `GROUP BY` and the percentage column is **not in it** — it is computed in the browser and its header says `(this page)`. |
| 11 | Copy the disclosed SQL, then `aws athena get-query-execution --query-execution-id <id>` and compare `QueryString` | **Byte-identical.** The only check that proves the disclosure and the executed string have not drifted — and a JSON hop now sits in the middle, so the comparison is against Athena's own read-back, not against the request body. |
| 12 | Leave grouping | Any sort on `count_all` is **dropped**, not carried onto the raw table. |
| 13 | Select a dozen numeric cells → **Calc**, toggle functions, reselect | The aggregates, the line `N selected cells on this page`, and **zero** Athena requests throughout. |
| 14 | Open `/explore`, pick a source, and watch the network panel through the QUEUED window | **Zero** `GET /v1/queries/{id}/results` until a poll reports `SUCCEEDED`. This is the surface the too-early read broke, and with the 409 mapping in place removing the gate now shows a *correct-looking* "still running" message — so the request count is the only assertion that can fail. |
| 15 | Page a >100-row result forward and back, then let the row count finish | Cached pages, no refetch; the total lands. Every walk request carries a properly encoded `nextToken` — an unencoded `+` decodes to a space and the next page silently restarts from the beginning. |

**Copy and export** (instrument 3 for the clipboard):

1. Select a rectangle, ⌘C, paste → cells in grid order, `NULL` where the grid showed NULL.
2. ⌘-click two non-adjacent cells, copy → the **bounding rectangle**, cells between blank.
3. Click a **column header**, copy → the loaded page's rows only.
4. **Copy…** → **JSON** → `null` for the NULL and `""` for the empty cell. Distinguishable is the point.
5. **Export** before anything has run → refused, `aria-disabled`, `disabled` false, `tabIndex 0`,
   *"Run a query first — export saves the results Athena returned."* No need to be quick: "nothing
   has run" and "still running" are one state.
6. Export → `explorer-export` → **My files** → **Save here** → success toast, and the file in **Files**.
7. **Open the exported CSV and count its rows.** It holds the **whole** result — 151 lines for the
   150-row fixture — while the page held 100. Download it through the portal.
8. Steps 1–7 started **zero** `StartQueryExecution`.
9. Export again, same name → the **Overwrite** confirm.
10. Export into a **shared space** → the cross-bucket copy succeeds.

> **A query that outruns the poll guard.** Results are read only at `SUCCEEDED`.
> `MAX_POLL_DURATION_MS` is 5 minutes and `refetchOnWindowFocus` is off, so an execution still
> running after that renders an indefinite **"Running…"** with no banner and no re-attach. If you
> can stage a >5-minute query, record what it looks like — the behaviour is not specified anywhere.
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
| Open the picker with no tabs | A **Create** section below the list: *Create table from a folder…*. Its dialog refuses the space ROOT and says why. |
| **Options** on an open exploration | One menu holding Columns, Colours, Transformers, Value, Calc, Grouping, Copy…, Export, Save as query, Create view…. The bar keeps only undo/redo, Order and filter, Clear, Filter by this value and the view switch. |
| **Options** with nothing selected | **Copy…** sits there `aria-disabled` with its reason on hover AND reachable by Arrow — not missing, not silently inert. |
| Pick any Options item, then press Tab | Focus is on the **Options** button, not at the top of the page. |
| **Options → Create view…**, name it, then look in the rail | The view appears. Its statement quotes both identifiers. |

### 4.6 Data quality

| Do | Expect |
|---|---|
| Check `dq_disagree/` | The cross-file finding, marked **Exact**, naming the column, while *"rows with the wrong number of fields"* stays **0**. |
| Check `dq_agree/` (the control) | Clean, with that section **absent** rather than empty. |
| Check a **single file** | Reports on that file alone — its neighbours are not counted. |
| Check an empty / header-only folder | Called out as a finding, never clean. Sampled and skipped figures never read as a pass. |
| The runs list | Pages, and reopens reports. |
| Check a folder whose header has `Order ID` | Refused by notification naming the column — a check cannot report on data it cannot read, so this is the answer rather than a gap in it. |
| Check a folder with a `key=value` partition whose KEY is not `[a-z0-9_]` (e.g. `order-id=1/`) | Refused under its **own** wording, about folder names — not the column one, because the repair is renaming a folder. |
| A report link for an unreachable space | Refuses, and issues **no S3 request naming it**. |

### 4.7 Saved queries

| Do | Expect |
|---|---|
| Save a query | Prompts for **name and space every time**. |
| Re-save unchanged | Confirms **once**. |
| Save to another space | A **copy** — the original stays. |
| Load it back | Byte-identical, and it appears in `saved_queries/` in the file browser. |
| Save a `.SQL`-cased name | Stem case is kept, extension is lowercased — no second object rendering identically. |
| From the Data Explorer: **Save as query** → `explorer-roundtrip` → My files | Exactly **one** `PutObject` after a HEAD on the exact key. No sidecar. |
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
| Query the space's database | Results route to the space's own `athenaresults/`, not yours. |
| Leave a space, then reload with its `?space=` still in the URL | Falls back, with **zero S3 requests naming the space** — no existence oracle. |
| **[approval gate]** Delete a space (type-to-confirm) | Gone from the rail **and** its Glue database gone. A partial teardown that frees the name is the failure this catches. |
| **[approval gate]** Re-create a space with the just-deleted name | It is accepted. That is the proof the teardown was complete — a partial one leaves the registry record standing, and the record is the lock. |

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
- **The notification is a link.** Follow it → you land in `archive/{uuid}/`, **not** at the space
  root. A link that drops its prefix looks identical from the inbox.
- The folder is gone from the listing; `archive/{uuid}/receipt.txt` downloads and reads correctly.

**Record the archive id.** Everything downstream needs it.

Then, while you are here — `archive/` and `archive/{uuid}/` are read-only and say so, at **both**
widths (the mobile action bar mounts its own controls, so a CSS-hidden twin would pass a
desktop-only check):

- **Upload** and **New folder** present but unavailable, with a reason naming the folder as
  read-only. **No `AccessDenied` ever reaches you.**
- Selecting the receipt: **Move** and **Delete** likewise unavailable with a reason.
- **Archive** is **gone**, not disabled. An archive of an archive is not a thing.
- **Details** and **Download** work normally — that is the point of the folder being visible.
- At the space root: `archive/` refuses Delete and Rename by name, and is absent from the
  destination picker when you Move or Copy something else.

Also archive a **single file from its Details panel** — the only route to archiving something you
have not ticked, and a different component from the toolbar's.

#### B2. Request the restore — the point of no return

**Ask before pressing this. Billed on request, uncancellable, 3–5 hours.**

**Restore Archived Data** → paste nonsense first: an inline error names what a valid id looks like,
and the submit control is **never merely disabled**. Then paste the real id → Restore.

**Within a minute, before you walk away:**

- Download `archive/{id}/receipt.txt`. **`Restore requested` already carries a timestamp** and
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
| `archive/{id}/` **still holds its receipt** | The folder survives the restore by design — the receipt is rewritten, never deleted, and it is the only durable record of the archive. A folder that vanished here is a defect. |
| The **vault** prefix for that id is gone | **Not observable from the browser** — the sweep is of `dat-prod-archive`, which no human principal can read. `owed.md` carries the CLI check; a `cleanup` block in `logs/service=archive/` is what you can see. |
| The receipt's ARCHIVE lines are **byte-identical to before** the restore, with `Restored to` now filled | A blanked `Requested` line is how you would know the rewrite broke. |
| The loop actually **looped** | `logs/service=archive/` carries multiple `retrieval polled` events **hours apart**, `poll_count` climbing. |

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

### 4.13 Help

- Each section's guide count matches what shipped — the Data Explorer section has **five**.
- The filtering guide's callout says plainly that each apply runs against Athena and scans data.
  That is the one thing a user cannot infer from the UI.
- Nothing promises a chart, cell editing, named filters, a References panel, or loading a `.sql`
  back into the Explorer.

### 4.14 Feature flags

**The whole point is that the app cannot tell you the answer.** Every compiled-in default is `true`,
so a permanently-blocked read renders *exactly* like a healthy all-on environment. "It looks fine"
is not a pass.

**The read is real** (all flags on):

1. Hard-reload signed in. In the network panel, find `_config/feature-flags.json` → **200**. That
   status is the assertion. `ProtectedLayout` mounts the hook and discards the result precisely so
   this request exists to be observed.
2. The response body is **non-empty JSON** carrying the document's `version` and `defaults`. That,
   with the 200, is the whole of the evidence available in production — the hook's own
   `ready`/`fallback` console line is behind `import.meta.env.DEV` and prints **nothing** in a
   production build, so its absence says nothing either way.
3. `_config/` is **not browsable** in the file browser — the IAM condition, not an SPA filter.

**A flag actually hides things** (one sitting; step 4 restores the environment):

1. Set `environments.prod` to `{"query": false, "dataQuality": false}`. Merge, wait for **Publish
   Config**. **Do not redeploy the app** — that is the point.
2. Hard-reload. Expect:

   | Where | Expect |
   |---|---|
   | Topbar | **Files** and **Connections** only — Query and Data quality *absent*, not greyed |
   | `/query` typed in | The **"Query isn't available"** page with a working **Go to Files** link — **not** "Page not found" |
   | Files, in a folder | **No "Create table"** on the toolbar |
   | Files, one item selected | **No "Check quality"** in the selection toolbar |
   | `/help` | Neither the **Query** nor the **Tables** section; in **Files**, *"Check data quality"* and *"Find a past quality check"* are gone while *"Upload files"* remains |
   | Hamburger at 400px | Files, Connections, Notifications, Help — and not the two hidden tabs. A tab hidden in the topbar and present here is the feature still one tap away. |

3. Set it back to `{}`, merge, wait for **Publish Config**, hard-reload. Everything returns, and
   `gh run list --limit 5` shows **Publish Config and no Deploy App**. That restoration is what
   proves `VITE_ENVIRONMENT` reached the bundle — nothing in the all-on pass can.

**`asyncFileOperations` is the sixth key and it is the odd one out** — a kill switch, not an area,
so what it hides is a behaviour rather than a tab. Its own sitting, and §4.2's async rows are what
it is checked against:

1. Set `environments.prod` to `{"asyncFileOperations": false}`; publish; hard-reload.
2. In **Help**, the *Files* section keeps *"Rename, move, copy, or delete"* and loses *"When a move
   or copy is refused"*. That is the only visible surface until you act.
3. Move a folder. It runs in the browser — `CopyObject`/`DeleteObject` in the network panel, no
   `SendMessage`, no in-progress card, and the listing updated when it finishes.
4. Set it back to `{}`, publish, hard-reload, and confirm §4.2's async rows behave again.

### 4.15 Responsive, and the Safari pass

**Corroborated in Chrome ≠ discharged.** Behavioural checks (execution counts, SQL text, refusals)
are waived to Chrome by user decision. **Rendering is not** — sticky columns, menu clipping,
sheet-vs-panel and toolbar wrap are exactly where Safari differs. The list below is owed in Safari,
at **400px via DevTools device toolbar**.

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

### The container platform — what a signed-in session CANNOT reach

`portal.dataquarry.app` is a **placeholder** and no user is pointed at it: the portal you sign in to
is still the CloudFront one. There is nothing here to click.

Two things are worth a glance whenever this guide is run, because both are invisible until a rollback
or a ported route needs them, and both are cheap:

- `curl -s https://api.dataquarry.app/healthz` returns `{"status": "ok", "version": "<sha>"}`. The sha
  is the last commit that changed `lambdas/api/`, **not** HEAD — the deploy skips unchanged
  functions, and reading it as HEAD makes a healthy API look broken.
- `curl -sSI $CLOUDFRONT_URL | grep -io 'connect-src[^;]*'` still names `https://api.dataquarry.app`.
  If it does not, a ported feature will fail in the browser and nowhere else.

The platform's own verification — the no-NAT pull, the redirect, target health — is **§B of
`arc-b-api-container-e2e.md`**, discharged 2026-08-26 and recorded in `owed.md`.

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
3. `CLAUDE.md`'s digest lines.

**An unrunnable check is a finding, not a failure.** If a step here cannot produce the outcome it
claims, fix the step and say so — that has been the most valuable output of several sessions.
