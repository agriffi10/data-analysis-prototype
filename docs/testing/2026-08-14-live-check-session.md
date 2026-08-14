# Live-check session — 2026-08-14

One session against the deployed portal (`d1kbh4bnvh1je8.cloudfront.net`), driven from the browser
as a **fresh account, `agriffith_three`**, signed up during the session. A clean account was chosen
deliberately: deterministic fixtures, and no risk to existing data.

`CLAUDE.md` carries one line per outcome and points here. This file is the evidence.

---

## Environment and what it can reach

Findings here decide what is checkable at all, so they come first.

| Target | Laptop identity (`user/tofu-deploy-user`) |
|---|---|
| `dat-prod-athena-admin` | **readable** — `logs/service=*/…/data.jsonl`, restore plans |
| `dat-prod-user-space` | explicit deny (bucket policy) |
| `dat-prod-archive` | explicit deny; execution role trusts `lambda.amazonaws.com` only; deploy role is GitHub-OIDC-only |
| Glue / catalog | `Insufficient Lake Formation permission(s): Required Describe` |
| CloudTrail | **no trails exist** |
| `dat-prod-table-builder-requests.fifo` | reachable (`get-queue-url` succeeds) |

Two consequences: **no principal can `head-object` the archive vault**, and **no principal can
`GetTable`**. Both take out owed assertions — see SPEC-186 FR-004.

Logs are swept on a **10-minute schedule**, so an empty partition immediately after an action means
*wait*, not *fail*. `logs/service=archive/` did not exist at all, confirming that plane has never run.

**Uploads cannot be automated** — the browser pane has no file-upload tool and the CLI is denied on
the user-space bucket, so every fixture was placed by hand.

---

## Discharged

### SPEC-137 Phase 4 — the auth spans

Signing up `agriffith_three` succeeded, which alone rules out the cold-start `ModuleNotFoundError`:
on `pre-signup` that failure blocks sign-up outright. `logs/service=auth/` carried both spans at
`status: "ok"`:

- `pre-signup` — `span.start` + `span.end`, 0.149 ms
- `post-confirmation` — `span.start` + `user provisioned` (`username: agriffith_three`,
  `database: agriffith_three`) + `span.end`, 1381.8 ms

Field rule holds: username and database only, no token, no email.
**Defect found:** every record carries `"version": "0.0.0"` and `"env": ""` → SPEC-186 FR-005.

### SPEC-146 — the username directory read

Typing one character in **Add members** returned **8 suggestions** (`adamparker`, `admin`,
`agriffith`, `akinwale14`, `denapolia`, `malathi`, `mrag`, `tencalade27`). Suggestions only render
if the portal role's SigV4 `GetObject` on `_directory/usernames.json` succeeded, so seeing them *is*
the end-to-end read confirmation.

The minutes-old `agriffith_three` was correctly **absent** — the document is built daily from S3
prefixes. That is the design, not a miss.

### SPEC-175 — the cross-bucket `PutObject`

Saving a query into shared space `livecheck_0814a` produced, in order:

```
HEAD  dat-prod-shared-space/livecheck_0814a/saved_queries/DO_NOT_DELETE.txt        → 404
PUT   dat-prod-shared-space/livecheck_0814a/saved_queries/DO_NOT_DELETE.txt        → 200
HEAD  dat-prod-shared-space/livecheck_0814a/saved_queries/livecheck shared save.sql → 404
PUT   dat-prod-shared-space/livecheck_0814a/saved_queries/livecheck shared save.sql → 200
```

Two design points confirmed live beyond the write itself: the folder marker is planted **on demand**,
and the name-collision check is a **HEAD on the exact key**, not a scan of the loaded array.

### The refresh arc — FR-010, end to end

On `agriffith_three.sales_livecheck`, built from a 2-file CSV folder (`id,region,amount`):

| Step | Action | Result |
|---|---|---|
| 1 | Add `part0.csv` (`id,region,amount,channel`), sorting first | `1 column added`; rail → `id, region, amount, channel` |
| 2 | Delete `part0.csv`, refresh **without** opt-in | Refused: *"these columns are no longer in the data and would be removed: **channel**. Nothing was changed - refresh again and confirm the removal to apply it."* |
| 3 | Follow the notification link | `/query?refreshTable=agriffith_three.sales_livecheck&removed=channel` opens the dialog **pre-armed**; banner names `channel`; opt-in **not** pre-checked; submit `disabled` until ticked |
| 4 | Tick opt-in, submit | `1 column removed`; rail → `id, region, amount` |

The opt-in was unchecked on every fresh open — **persisted nowhere**, as specced.

> **The trap that cost a false bug report.** Schema inference probes exactly **one** sample object —
> the first key in listing order (`sample_by_format.setdefault(fmt, key)` in `inspect-source`). A
> column added in a file that sorts *later* is invisible **by design**, and the refresh correctly
> reports `already up to date`. The first attempt used `part3.csv` and read as a defect until the
> code was checked. → SPEC-186 FR-006.

### The casing premise — now demonstrated, not corroborated

Uploaded `part00.csv` with headers `ID,Region,Amount` so it became the sample, against a stored
schema of `id,region,amount`.

- Refresh reported **`already up to date - no schema changes were found`** → `diff-schema` folds
  case, rather than seeing 3 added + 3 removed
- The rail still reads `id, region, amount` → **nothing was silently re-cased**

That is the mutation CLAUDE.md warned would be reported by no test and no notification. It did not
occur. Still unobserved: `get-table-versions` (that no new version was written), which needs FR-004.

### SPEC-142 — the disagreeing-files check

Two checks over sibling folders, each 2 files.

| | `dq_agree` | `dq_disagree` |
|---|---|---|
| Verdict | No issues found | Issues found |
| Rows / Files | 4 / 2 | 4 / 2 |
| Disagreement section | **absent** | present, **Exact** |
| Rows with wrong field count | 0 | **0** |
| `qty` null or blank | 0% | 50.0% |

The finding read: *"b.csv is missing the column `qty` that the other 1 file has"*, under **Files that
disagree about their columns**, naming `agriffith_three/dq_disagree/b.csv` and `Missing: qty`.

**The load-bearing assertion is the negative one:** the disagreement did **not** leak into a
ragged-row count. Both runs appeared immediately in the `/data-quality` index (SPEC-123) with correct
badges.

---

## Half done

### SPEC-125 — shared-space smoke run

**Create and add-member pass**, which is the risky half: a shared layer's import-time `_require`
fails at *cold start* (PR #196), and it did not.

- `livecheck_0814a` went **Active**
- adding `agriffith` showed **Pending** (SPEC-073's join status), with a Remove control
- `logs/service=shared-space/`: `validate` → `validated` (`action: create`, `known_space: false`) →
  `create` → `membership slot assigned` (slot 1, cap 10, store `cognito`)

**Leave PASSES too, run as `agriffith` (2026-08-14).** On signing in, the membership had flipped
**Pending → Active** — SPEC-073's `acknowledge-membership` working. As a non-owner the row offered
only **View members** and **Leave**, never Manage or Delete. The confirm read *"Leave
livecheck_0814a? You'll lose access to its files and tables. They are not deleted — everyone else
keeps access."* After leaving, the space vanished from the list, and revisiting
`/files?space=livecheck_0814a` showed *"That shared space is no longer available, so we switched
back to your personal files"* with **zero S3 requests naming the space** — the fallback resolves
from the connections list, so there is **no existence oracle** (SPEC-113/163's rule, confirmed).

**Delete PASSES, run as the owner — the smoke run is COMPLETE.** The confirm is `role="alertdialog"`,
names exactly what is lost (*"all of its files, all of its tables, the database, and every member's
access"*), and gates on **type-to-confirm**: Delete measured `disabled: true` before typing and
`false` only once the exact space name was entered. Afterwards the connections list was empty **and
`livecheck_0814a` was gone from the Query rail**, so the teardown removed the catalog side and not
merely the registry row — the shape SPEC-151's partial-teardown fix cares about. The owner's row had
also dropped to **"1 member"** after the leave, so `leave` fans out correctly where acknowledge does
not.

Minor, low severity: signing out does **not** purge the prior user's `s3portal.query.tabs.{username}`
sessionStorage key. Namespacing works and nothing is shown cross-user, but that session's SQL
buffers and saved-query pointers persist for the life of the browser tab — relevant only on a
shared machine.

**Defect found while here — the roster contradicts the connections list.** Same page, same moment:
the row read `Member | Active` while the members drawer read `agriffith | Pending` under *"…hasn't
signed in yet"*, to a reader who plainly had. The drawer's Refresh did not reconcile it.
`cache.write_roster_to_all` fans out on add/remove/leave and **not** on acknowledge — visible in
`logs/service=shared-space/` as `roster fanned out` under `add-members` and nothing after — so
roster copies stay frozen at add time. → SPEC-186 FR-008.

### SPEC-175 — opening a colleague's query

As `agriffith`, the Saved queries panel's space selector listed `livecheck_0814a`; the colleague's
query appeared as *"livecheck shared save · 44 min ago · 85 B"* with Open and Delete. Opening it
fetched `GET dat-prod-shared-space/livecheck_0814a/saved_queries/livecheck shared save.sql → 200`
and opened a tab named for the query with the saved body. **Discharged.**

Side observation: merely opening the panel planted the reader's own marker —
`agriffith/saved_queries/DO_NOT_DELETE.txt` 404 → `PutObject` 200 — so a read path creates the
folder too, not only a save.

### SPEC-158 — the suggestion pass

**Passes:** 7 chips tokenize on Enter from comma-separated input; the confirm control stays inside
the dialog, in the viewport, and hit-testable. Backspace deliberately does not remove chips.

**Fails:** the list does *not* position inside the panel. Listbox spans y 472→682; dialog ends at
585 — a **97px overhang** clipped by the dialog's `overflow: auto`, leaving **3 of 8** options
visible (still reachable via the listbox's internal scroll: 259px of content in a 208px box).
→ SPEC-186 FR-003. Re-measure after FR-007, since this was measured inside an oversized dialog.

**Owed:** the **Share table** dialog under **both share kinds**, the **400px** pass, and the whole
thing in **Safari** — a Chromium run corroborates but cannot discharge a Safari pass.

---

## Unrunnable as written — the most valuable class

### SPEC-173's marker check

Asks: delete `{root}saved_queries/DO_NOT_DELETE.txt` through the portal, confirm `AccessDenied`.
**The portal never issues that call.** The marker is hidden **by basename** so it cannot be selected,
and the folder delete is refused **client-side** by `UNDELETABLE_ROOT_FOLDERS` before any S3 request.
A network trace of both attempts shows **zero** `DeleteObject` requests against the marker.

Verified instead — the client-side layer, personal **and** shared:

> "Deleted 0 items. Could not delete 1: **saved_queries — Saved queries live in this folder, so it
> can't be deleted.**"

with the folder surviving, and an ordinary empty folder (`refresh_step2`) deleting cleanly beside it
as the control. The bucket-policy Deny — the second layer — remains unverified. → SPEC-186 FR-001.

### SPEC-157's concurrency check

Not performable from the UI, and now measured. Two submits **2 seconds apart** — two tabs pre-armed
via the `/query?refreshTable=` deep link, which is the floor two browser clicks allow — **both
returned independently** with no `refresh_already_running`. An earlier pair 9 s apart behaved the
same. A small table's refresh completes inside that window, so the lock is never contended and the
check can neither pass nor fail this way. → SPEC-186 FR-006.

### The archive arc's `head-object` assertions

SPEC-170's negative assertion (no `Restore` header after a `destination_occupied` refusal), SPEC-169's
`StorageClass: GLACIER` read-back and its empty-archive-prefix check all need `head-object` on
`dat-prod-archive`. No principal can reach it, and with no CloudTrail there is no independent record
of whether `RestoreObject` was called. **Do not proxy from the UI** — the script itself says a
refusal that had already started retrieval looks identical there, and being wrong costs 3–5 billed,
uncancellable hours. → SPEC-186 FR-004.

### SPEC-149 / SPEC-153's catalog read-backs

`get-database` returns `Insufficient Lake Formation permission(s): Required Describe` — the same wall
that forced 153's docs-transcribed stand-in. → SPEC-186 FR-004.

---

## Defects found

| # | Finding | Where |
|---|---|---|
| 1 | **Nine dialogs render at full viewport width.** `New folder` and `New shared connection` both measured **1372px in a 1400px viewport, `max-width: none`**, against `Create table`'s correct 448px/`max-w-lg`. Root cause: `cx()` returns `''`, `FormDialog` passes it to `Modal`, and `Modal`'s `className ?? 'max-w-md'` does not fall back on an empty string | SPEC-186 FR-007 |
| 2 | Suggestion listbox overhangs its dialog by 97px; 3 of 8 options visible | SPEC-186 FR-003 |
| 3 | `saved_queries` shows Delete/Move **enabled**, raises "This can't be undone", then refuses — the most alarming confirm in the app for an action that cannot happen | SPEC-186 FR-002 |
| 4 | Refresh dialog's submit is natively `disabled` with no reason, where SPEC-172 set `Button.disabledReason` as the fleet-wide pattern | SPEC-186 FR-002 |
| 5 | `version: "0.0.0"` and `env: ""` on every structured log record | SPEC-186 FR-005 |
| 6 | The members roster shows `Pending` — with *"hasn't signed in yet"* — for a member the same page shows as `Active`; Refresh does not reconcile | SPEC-186 FR-008 |
| 7 | Recipient chips are three copied implementations, already drifted: remove target is **20×20** in Share table and Send files against **24×24** in Add members (WCAG 2.2 SC 2.5.8 minimum). Chip width is unbounded — a 63-char username extrapolates to ~610px, wider than its 448px dialog | SPEC-186 FR-009 |

---

## Fixtures

`~/Downloads/portal-live-check-fixtures/` — `sales/` (base table), `refresh_add/part0.csv` (sorts
first, adds `channel`), `refresh_casing/part00.csv` (headers `ID,Region,Amount`), `dq_agree/`,
`dq_disagree/`. Keep `part00.csv`'s name: the sampling rule makes ordering load-bearing.

**Left behind in the account:** shared space `livecheck_0814a` (member `agriffith` pending, one saved
query), table `agriffith_three.sales_livecheck`, and the fixture folders. The space is still needed
for SPEC-125's `leave`/`delete`.
