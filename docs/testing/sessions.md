# Live-check session log

What was actually run against deployed prod, when, and what it returned. **This is the evidence
behind every DISCHARGED row** in [`owed.md`](owed.md) — the scripts say what to assert, this says
what happened.

Add a new section at the top after each session, following [`e2e.md`](e2e.md) §5. Record the
username, the browser and width, and every instrument used — each one is a way the run differed
from a user's.

---

## Live-check session — 2026-09-22 (the restore's completion, and the rows the 2026-09-21 sitting never reached)

**What was under test.** The SPA image **`aecc93fd`** (task definition `dat-prod-spa:230`, read from
the service) and the API and planes at **`d4b4fa14`** (`/healthz`) — the first sitting on the build
that carries the archive count fix. **The restore checked below is not on that build**: its
execution ran and notified at 01:51Z, and `d4b4fa14` merged at 02:20Z, so every count it printed
came from the old code rather than from the new code's fallback. Times are UTC.

**Browsers.** `agriffith` only, signed in by Andrew himself in both; nothing was typed or clicked on
a credential form by the session.
- A **Chrome** tab of the Claude-in-Chrome group, window hidden, at 1512 px.
- The Claude app's **Browser pane**, at its own 388 px width and, for SPEC-190's row, emulated at
  **400 × 820** (`matchMedia` confirmed: `min-width: 400px` true, `401px` false).

**Instruments, each a way this run differed from a user's.**
- `document.visibilityState` and `hidden` overridden to visible after every load in both browsers.
- **A focus return was dispatched, not performed**: `visibilitychange` on `window` plus a `focus`
  event. TanStack Query's focus manager subscribes to `visibilitychange` **on `window`**, so a
  `document.dispatchEvent` of a non-bubbling event reaches nothing — the first attempt did exactly
  that and read as a stale listing. What is proven is the app's own refetch path, not that a real
  tab return fires the event.
- Most requests were sent in-page with `fetch` and the tab's own `idToken`, because the classifier
  refused a `window.fetch` patch. Where a count of requests was needed, **Resource Timing** was the
  recorder (`performance.getEntriesByType('resource')`), not the extension's network reader.
- Enter was sent with the extension's `computer` key action into the hidden window, **with a
  positive control first**: Enter on a focused **New folder** opened its dialog.
- Log reads used `aws s3api get-object` against `s3://dat-prod-athena-admin/logs/`. Two compound
  reads were refused by the classifier as *Production Reads*; single calls of the same shape ran.

### §4.11 D — the restore of `57d14bb9-be06-4790-81ab-d5a95d484926` — **every row settled**

Requested 2026-09-21 22:45:26Z, finished 2026-09-22 01:51:08Z: **3 h 5 min**.

| Assertion | What it returned |
|---|---|
| The terminal notification | *"Restored 2 files (38 B) to your space, back where they came from. The archive has been cleaned up."* The **2 is the known miscount**, printed by the pre-fix code this execution ran on. |
| Its link | `/files?space=livecheck_186&prefix=livecheck_186/` — the space root, not a folder. Following it listed `live0921_archive` back at the root. |
| Every file back at its original path | `livecheck_186/live0921_archive/archive_0921.csv`, 38 B, written 01:51:02Z. |
| The empty folder the archive carried | `livecheck_186/live0921_archive/` **exists** (`GET /v1/objects/exists`), against a made-up key answering `exists: false` as the control. |
| The receipt survives | `system_settings/archive/57d14bb9-…/receipt.txt`, 428 B, rewritten 01:51:08Z. |
| The ARCHIVE lines byte-identical | All six compared literally against the copy quoted in this file before the restore: identical. `Restore requested` still reads `2026-09-21 22:45:26 UTC`; `Restored to` now reads `s3://dat-prod-shared-space/livecheck_186/`. |
| The vault prefix is swept | `archive swept` in `logs/service=archive/`, `objects: 3, residue: 0, expected: 3`. |
| The loop actually looped | **37 `retrieval polled` events**, five minutes apart, 22:50:39Z → 01:50:57Z (14 on day 21, 23 on day 22). |
| A child span survived the pipe | `span.start` with `function: "copy-batch"`, `parent_span_id` `0c0aa2241d15949e`, which **is** the `span_id` of the `copy-objects` record in the same `trace_id` `17c61780…`. Not null. |

`agriffith` then **left `livecheck_186`**, which the row said to do once this finished. The leave
was accepted and the space left the connections cache; **the leaver gets no notification of their
own leave**, which is worth knowing before anyone waits for one.

### The rows the 2026-09-21 sitting never reached

| Row | What ran, and what it returned |
|---|---|
| **A destination conflict is reported PER ITEM** (SPEC-188 FR-005), the **folder** variant | **PASS.** One `copy` of two folder items into `live0922_ops/dest/` with `onConflict: "refuse"`, where `dest/folder_a/a1.csv` was in the way. **One** notification: *"Copied 1 of 2 items to "dest". 1 needs your attention: "folder_a" - something is already in the way there. …"*. Its payload's `conflicts` names `itemKey` `…/src/folder_a/`, `kind: "folder"` and a `sample` of the colliding derived key. `folder_b` arrived; the occupied object's body and `LastModified` (17:40:49Z) were unchanged. |
| The same row's **`overwrite`** half | **PASS on behaviour.** One `copy` with `onConflict: "overwrite"` into `dest2/`, `submittedAt` 17:42:00.227Z, against `old.csv` written 17:41:58Z and `new.csv` written 17:42:04Z. The **older** destination object was replaced (`SOURCE_OLD`); the **newer** one came back a `conflict` and was left untouched, body and `LastModified` both. **A wording defect, not a behaviour one:** the conflict sentence is keyed on the outcome alone (`focommon/messages.py`, `_OUTCOME_ADDITIONS`), so this request — sent *with* overwrite on — was told *"Sending it again with overwrite turned on replaces what is there"*. Both messages were byte-identical. Raised as a task. |
| **SPEC-191 §20's single-folder repeat** | **PASS.** A `delete` of the single item `live0922_ops/single/`: *"Deleted 1 item."*, payload carrying the request id, and the link landing in **`live0922_ops/`** — the parent, not the removed folder. |
| SPEC-191's **§22 re-run** | **Already closed** on 2026-09-21 by the defect row's own re-run; the row's prescription is stale and is struck in `owed.md`. |
| **A real folder move** (SPEC-190) — the listing after a focus return | **PASS**, by the dispatched focus return described under Instruments. The move of `src2/` into `dest2/` settled at 17:48:06Z; the listing still showed `src2` until the event, then dropped it and showed `moved_here`, with one `GET /v1/objects` in Resource Timing across the event. |
| The same row — **400 px** | **PASS**, in the Browser pane at 400 × 820. `folder_b` moved into `moved_here/`: accepted at once, the in-progress card **fixed at 642–736 px** and the mobile action bar **fixed at 767–820 px**, so the card is clear of the bar with 31 px to spare. The card settled on the notification to *"Finished — see your notifications for what happened."*, and the listing was correct after the focus return. The toast (744–803 px) does overlap the action bar while it shows; it is transient and not treated as a finding. |
| **SPEC-239's API-level half** | **PASS.** Against execution `c9ae7f2a-…` (`explorer150`: `id, region, owner, qty`). `columnIndexes: [1,0]` wrote `live0922_conv/live0922-columns.csv` reading `region,id` / `south,1` / `east,2` — the 2nd and 1st columns in that order and no others — and notified *"Saved 150 rows as CSV…"*. `[0,0]` was **refused by the verb**: *"Couldn't save the query results: the columns chosen for this file don't match the query's results, so nothing was saved."*, **no file written**. The refusal came from **`validate-authorize`** with reason `invalid_columns` (`logs/service=results-conversion/`), which is the path the ledger already excuses from carrying a `format`: its payload carries `requestId` alone, while the success payload carries `format: "csv"`. |
| **§4.5 row 14** — no early results read | **PASS.** Opening `explorer150` in the Data Explorer: `POST /v1/queries`, **two** status polls, then **one** `…/results`, 192 ms after the second poll. Zero results reads during the queued/running window. |
| **§4.5 row 15** — paging | **PASS.** Forward: one `…/results` carrying a **percent-encoded** `nextToken` (108 chars), *Rows 101–150 of 150*. Back: **zero** requests. Forward again: the only request was an unrelated `objects.content` read; a further back-and-forward pair made **zero**. |
| **§4.11 "Enter cancels"** | **PASS**, in the hidden Chrome tab after the positive control. With `old.csv` ticked, the archive dialog read *"Archive "old.csv"? This will be removed from this space and stored in long-term storage. You can restore an archive later using its id, but a restore takes several hours to complete."* — naming the item relative to the space, and **not** saying it cannot be undone. Focus was on **Cancel**. Enter closed the dialog, started no archive, left the file in place and kept the selection. |
| **A multipart upload's abort during SIGN-OUT** (SPEC-216 FR-004) | **RUN, and the abort did NOT land.** A 448 MB file (four 112 MiB parts; the threshold is `MULTIPART_PART_BYTES`, 112,500,000 B) was uploaded in the pane and the session signed out mid-transfer. `logs/service=api/` shows `objects.upload` at 18:03:16Z and `objects.uploadPart` calls through 18:03:28Z, and **no `objects.uploadAbort` at all**. `list-multipart-uploads` on `dat-prod-user-space` was empty before and afterwards held `agriffith/live0922_ops/live0922_big.bin`, initiated 18:03:18Z. Not a correctness bug — FR-004 declines to guarantee the abort and the bucket's seven-day rule is the backstop — but the cost is now measured rather than assumed. |
| **A shared space whose NAME is not catalog-safe** | **HALF RUN.** The name must contain a **space** and not a backtick or a double quote: a space name becomes an STS **session tag value** on every call that account makes (`apicommon/identity.py`, `session_tags`), and STS's tag-value grammar admits `\p{Z}` but neither of the others — so a backtick would have broken every credential call `agriffith` makes until the membership was removed. `live0922 odd` was created through `POST /v1/enqueue/shared-space` and **Glue did not refuse it**: *"Your shared workspace "live0922 odd" is ready."*, active in the connections cache. The DDL half is below. |
| **§4.11 B1a** (a reused archive id) | **NOT RUN.** It needs an archive whose prefix is not yet empty, and the only one to hand had just been restored. Andrew declined a fresh archive for it, so it stays owed. |

**Two things the create path showed, neither a defect:**
- **The membership limit is real and it bites the owner.** The first create of `live0922 odd`
  failed with *"membership limit reached"* — `agriffith` held eleven connections. Leaving
  `livecheck_186` freed the slot and the same create then succeeded.
- **A new space is unreachable to its own creator until the token refreshes.** Immediately after
  the create, `PUT /v1/objects/content` into it answered `403 AccessDenied`, *"no membership for
  that space"*, and `GET /v1/catalog/databases/live0922%20odd` answered `403`. That is the stale
  membership tag `owed.md` already records, seen from the owner's side.

**Left behind.**
- `agriffith/live0922_ops/` (`dest/`, `dest2/`, `moved_here/`, `src/`) and `agriffith/live0922_conv/`.
- The shared space **`live0922 odd`**, owned by `agriffith`; its name is spent.
- `agriffith` is **no longer a member of `livecheck_186`**.
- An **incomplete multipart upload**, `agriffith/live0922_ops/live0922_big.bin`, which no browser
  session can abort now and which the bucket's seven-day rule will clear.

---

## Live-check session — 2026-09-21, night (two accounts: the send, the share, membership, the refusals and catalog isolation)

**What was under test.** The same build as the evening sitting: the SPA image **`8061989c`**
(task definition `dat-prod-spa:228`, read from the service) and the API and planes at **`a1931c9a`**
(`/healthz`). `environments.prod` is `{}`. Times are UTC.

**Browsers.** Two accounts, each signed in by Andrew himself; nothing was typed or clicked on a
credential form by the session.
- **`agriffith`** in the Claude app's **Browser pane**, at its own 716 px width and, for the table
  build and the archive, emulated at 1280 × 800 (the narrow toolbar hides **Create table**).
- **`agriffith_three`** in a **Chrome** tab of the Claude-in-Chrome group. The window was hidden:
  screenshots timed out, and `computer` clicks did nothing.

**Instruments, each a way this run differed from a user's.**
- In Chrome: `document.visibilityState` and `hidden` overridden to visible after every load, with
  `visibilitychange` and `focus` dispatched. Controls were driven with `element.click()` and form
  fields with the native value setter plus an `input` event, because the hidden tab ignored
  `computer` clicks.
- In the pane: uploads went through the Upload dialog's own file input, given a `File` through
  `DataTransfer`.
- The query, catalog and refusal probes were sent from each page with its own token, in the UI's
  own request shape. The shared-space negatives had to be sent that way, because the UI offers a
  non-owner none of those actions.
- **The permission classifier refused some calls, named here because others of the same kind ran.**
  Refused: `aws logs filter-log-events` on `/aws/lambda/dat-prod-api` piped into `python3`; a
  single `aws stepfunctions list-executions` on `dat-prod-shared-space-orchestrator`; a batch of
  three shared-space requests from the pane, as "Modify Shared Resources"; and listing the tables of third-party spaces, as
  personal data. Ran: one earlier `filter-log-events` for the execution id (it matched nothing),
  `list-state-machines`, and `ecs describe-services` and `describe-task-definition`. The three
  requests then ran as single calls, and the cross-space negative used a new space of Andrew's own.
  After #868 merged, with Andrew's go-ahead in chat, the histories and the swept API log were read; see
  *Read after #868 merged* below.
- The Chrome extension redacts a script's output when it holds a query string; the links were read
  with `?`, `=` and `&` substituted.

**SPEC-232, the two-user twin** (`owed.md`, *Needs a second (or third) account*).

| Check | Result |
|---|---|
| `agriffith` asks about an `agriffith_three` execution | **PASS.** `agriffith_three` ran `SELECT count(*) AS n FROM employees` (`946b415e-5acc-45f2-8fdc-e90767c0d406`, output under `agriffith_three/system_settings/athenaresults/`, result `2`). From `agriffith`, status, results, row-count and stop each answered `404` `{"error":{"code":"NotFound",…,"detail":"no execution with this id belongs to the caller"}}`. A made-up id's four answers were byte-identical apart from `requestId`. |
| The reverse | **PASS.** `agriffith`'s `SELECT 1` (`7e761189-ea67-4c27-9e77-72d48398ea11`, output under `agriffith/`), asked about from `agriffith_three`: the same four `404`s. |

**Add, acknowledge, then the roster** (SPEC-125, SPEC-186 FR-008), on `livecheck_186`, owned by `agriffith_three`.

| Step | Result |
|---|---|
| Before | The card read *1 member*, and the roster held the owner alone. |
| The owner adds `agriffith` | Toast *"Adding 1 member to “livecheck_186”…"*. 10.5 s later the owner's roster read `agriffith` **Pending**, with **Make owner** and **Remove**. |
| The member, before any acknowledge | With no sign-out, `/connections` showed `livecheck_186` as Member, Active, owner `agriffith_three`. **View members**, with no acknowledge key yet in `sessionStorage`, read `agriffith` **Active**. |
| The acknowledge | Opening `/files?space=livecheck_186` set `s3portal.ackMembership.agriffith.livecheck_186`. The page read *"Applying your access… You were just added to this space. Access applies once your session refreshes…"*. **Refresh access** brought a token carrying `custom:shared_space_10 = livecheck_186`, and the listing appeared. |
| The owner refreshes | **PASS.** `agriffith` **Active**; the card read *2 members · created Aug 14, 2026*. |

**Shared-space authorization negatives** (SPEC-053/054). There is one FIFO group for the whole
plane, so a later request's notice proves the earlier ones were started.

| Request | Result |
|---|---|
| Owner `leave` (`933a5270-a3ca-47b6-808b-bcc361c3cfab`) | `200` at the API; no notice, the designed silence for a refusal that raises. The owner was still the owner. |
| Non-owner `delete` (`c6bf68f7-0c20-4c45-8311-e393e5eda9ed`) | `200`; no notice, and no card anywhere read *Deleting*. The space was still in both accounts' lists. |
| Non-owner `add_members` of `live0921_nobody` (`8e4e9163-fec5-4e43-9db7-a6b462cb6993`) | *"We couldn't change who belongs to the shared workspace "livecheck_186"."* |
| Non-owner `remove_members` of themselves (`84148e0f-fc74-431d-9b5e-a924cbd213ca`) | The same sentence, as a second notice. `agriffith` was still in the roster. |
| After all four | The roster was unchanged, and the owner's bell stayed at 33 unread. The execution records, read after #868 merged, show which state refused each (*Read after #868 merged* below). |

**Catalog isolation, the Lake Formation half.** It was run before any table existed in `livecheck_186`,
so that a `DROP` could not be refused for a non-empty database instead.

| Probe | Result |
|---|---|
| A member's query against the space | `SELECT 1` with the context database `livecheck_186` succeeded. Its output went to `agriffith/system_settings/athenaresults/`, the caller's prefix; `e2e.md` §4.8 said the space's, and was corrected. |
| `ALTER DATABASE livecheck_186 SET DBPROPERTIES ('live0921' = 'probe')` | **Refused** (`b90af084-44e9-40d2-abeb-82bb5562e25b`): *"…assumed-role/dat-portal-user-role/agriffith is not authorized to perform: glue:UpdateDatabase … because no identity-based policy allows the glue:UpdateDatabase action"*. |
| `DROP DATABASE livecheck_186` | **Refused** (`895fcc09-af25-4893-9ced-3b5fd66cfa7d`): the same shape, on `glue:DeleteDatabase`. Afterwards `GET /v1/catalog/databases/livecheck_186` answered `200`. |
| The prefix cousin's personal database | From `agriffith`, both catalog reads of `agriffith_three` answered `403 AccessDenied`, and `SELECT count(*) FROM agriffith_three.employees` failed on `glue:GetDatabase` (`1132e81a-9bde-44a7-abfd-f8d7e62d2b9e`). Its owner's count is 2. |
| Another space's database | `agriffith_three` created `live0921_iso`; 12 s later its card read Active, *1 member · created Sep 21, 2026*. The owner's own catalog read answered `403` until **Refresh access** added the slot, then `200`. The Files page told the creator *"You were just added to this space"*. From `agriffith`: both catalog reads `403 AccessDenied`, and `SHOW TABLES IN live0921_iso` failed *"Database does not exist"* (`148c84c9-39c0-4ce3-98dd-a653d487d480`). The same text came back for a name no space has (`90f6c23e-bb88-47d9-a275-b04752cdd31d`). A table-less `SELECT 1` succeeded with either as the context database, so nothing tells the two apart. |

**Membership as a non-owner member** (`agriffith` in `livecheck_186`).

| Step | Result |
|---|---|
| Upload and build | Created `live0921_pair/` and uploaded `pair_0921.csv` (12 rows, 158 B). **Create table** on the selected folder, 22:36:19Z. The catalog held `live0921_pair` (`id`, `city`, `score`, all `string`, at `s3://dat-prod-shared-space/livecheck_186/live0921_pair`) by 22:36:28Z, and the notice read *"Table "live0921_pair" is ready to query in "livecheck_186"."* |
| The Data Explorer | From the Query rail's **Explore data**: *Rows 1–12 of 12*, *"This query scanned 158 B"*. The owner's `count(*)` of the same table was `12`. |
| Archive, **approved** | `live0921_archive/` holding `archive_0921.csv` (38 B). The confirm (`alertdialog`) named *“live0921_archive/”*, relative to the space, said it *"will be removed from this space"* and that a restore *"takes several hours"*, never said it cannot be undone, and opened with focus on **Cancel**. Enter was not tested: §1's new trap. Confirmed at 22:43:22Z; the toast said *"Archive started"*. The notice came about 24 s later: *"Archived **2 files** (38 B). … Archive id: 57d14bb9-be06-4790-81ab-d5a95d484926"*, linking to `/files?space=livecheck_186&prefix=livecheck_186/system_settings/archive/57d14bb9-…/`. |
| The archive's miscount | **FAIL, a new defect.** There was one file. The archived objects cannot be listed (no human principal reads the archive bucket), but the code accounts for the second: **New folder** writes an empty object at the folder's key (`createFolder`), and the plan carries and counts placeholders (`plan.expand`). The receipt, read through `GET /v1/objects/content`, says `Files archived: 2` and `Total size: 38 B (38 bytes)`. It is now a row in `owed.md`, and a follow-up task was offered to Andrew. |
| The archive folder | The link landed on it. A banner reads *"The archive folder is read-only…"*. **Upload** and **New folder** are unavailable with that reason, and **Archive** is absent. With the receipt selected, **Move** and **Delete** are unavailable with the same reason. `live0921_archive/` was gone from the space root. |
| Restore, **approved** | A nonsense id gave an inline *"That doesn’t look like an archive id. Ids look like 3f8a1c2e-…"*, with `aria-invalid` set and **Restore** still enabled. The real id was sent at 22:45:26Z; the toast said *"Restore started…"*. At 22:45:40Z the receipt read `Restore requested: 2026-09-21 22:45:26 UTC` and `Restored to: -`. The started notice had no link: *"Restoring 2 files from long-term storage…"*. **§4.11 D is owed** when it finishes. **B1a (a reused archive id) was not attempted.** The runbook orders it before B2, because a finished restore empties the archive prefix the check relies on. |

The receipt before the restore, whole (last modified 22:43:39Z), read through `GET /v1/objects/content`, for
§4.11 D's byte-identical comparison:

```
Requested:         2026-09-21 22:43:22 UTC
Request ID:        57d14bb9-be06-4790-81ab-d5a95d484926
Original path:     s3://dat-prod-shared-space/livecheck_186/
Archived path:     s3://dat-prod-archive/shared/livecheck_186/archive/57d14bb9-be06-4790-81ab-d5a95d484926/
Total size:        38 B (38 bytes)
Files archived:    2
Restore requested: No
Restored to:       -
```

At 22:45:40Z only `Restore requested` had changed, to `2026-09-21 22:45:26 UTC`.

**Table share** (SPEC-161). **PASS.** `agriffith` shared `explorer150` to `agriffith_three` as
`live0921_share150`. `agriffith_three` got *"agriffith shared table "live0921_share150" with you in
"agriffith_three"."*, and the table sits at `agriffith_three/shared_tables/live0921_share150`.
`SELECT count(*)` there returned `150` (`22dd24ab-cfc2-453b-a118-5395a9791d51`), and the source's own count was `150`
(`1e8ffdb6-2e8d-476a-a178-236236db7eb9`). The sender got one outcome.

**Receiving a send** (SPEC-167). **PASS.**

| Send | Result |
|---|---|
| `send_a_0921.csv` and `send_b_0921.csv` to the user `agriffith_three`, 22:38:50Z | The dialog read *"SENDING 2 ITEMS"* by name. The arrival: *"agriffith sent you "send_a_0921.csv" and "send_b_0921.csv" (2 files). You'll find them in shared_files/agriffith/."* Its link, `/files?prefix=agriffith_three/shared_files/agriffith/`, landed on *agriffith_three / shared_files / agriffith* with both files. |
| `send_a_0921.csv` to the space `livecheck_186`, whose owner is not the sender, 22:40:18Z | Typing `li` under **Shared spaces** suggested `livecheck_186`. The owner's arrival: *"agriffith sent "send_a_0921.csv" (1 file) to your space "livecheck_186"."* Its link, `/files?space=livecheck_186&prefix=livecheck_186/shared_files/agriffith/`, landed on *livecheck_186 / shared_files / agriffith* with the file. |
| The sender | One outcome per send: *"Sent … (2 files) to user "agriffith_three"."* and *"Sent "send_a_0921.csv" (1 file) to space "livecheck_186"."* |

**A forged `idToken`.** **PASS.** At 22:46:22Z, `agriffith`'s token with one signature character
changed got `401 {"error":{"code":"SessionExpired",…}}` on `POST /v1/enqueue/shared-space`
(an `acknowledge_membership` for `livecheck_186`, which returned no request id) and on
`GET /v1/catalog/databases/livecheck_186`. The real token answered every call before and after.

**Read after #868 merged**, with Andrew's go-ahead in chat for read-only log and Step Functions calls.
`aws stepfunctions list-executions` on `dat-prod-shared-space-orchestrator` listed four `FAILED`
executions between 22:28:26Z and 22:29:45Z. One `get-execution-history` with `--output text` was
refused by the classifier; the same call with `--output json` ran.

| Execution | What its history shows |
|---|---|
| `a91eec5a-fc20-5e98-8733-8f714d9d802d`, the owner's `leave` | `Validate` failed with `AuthorizationError`, *"owner cannot leave their own space (delete it instead)"*, then `ValidateFailureSeed`, `RecordFailure`, `NotifyFailure` and `Failed`. It is matched by that refusal and its start, 22:28:26.782Z, 118 ms after the leave's `200` at 22:28:26.664Z. |
| `34218176-0614-5d26-9681-e25db7f91d38`, `requestId` `c6bf68f7-…`, the non-owner's `delete` | Its input carries `identity.actor: agriffith` and `SenderId` `…:dat-prod-api`. `Validate` failed with *"delete on 'livecheck_186' is owner-only"*, then the same failure path. |
| `8d46761a-51f9-52e7-be9d-1531e00012f9`, `requestId` `8e4e9163-…`, `add_members` | `Validate` succeeded. Its output carries `refusal: {code: MemberNotOwner}` and a registry last updated at 22:27:26Z. Then came `Route`, `RefusedSeed`, `NotifyFailure` and `Failed`. |
| `a5c3468a-7a51-536e-ac6a-25a1c85d2337`, `requestId` `84148e0f-…`, `remove_members` of `agriffith` | The same as the add: `MemberNotOwner`, the registry unchanged since 22:27:26Z, and no verb state. |

The SPEC-232 stamps are in the swept API log. Structured events go to the logs queue rather than to
CloudWatch (`cpcommon/observability.py`), and a `filter-log-events` on `/aws/lambda/dat-prod-api` for
`execution_ownership` over 22:10–22:25Z returned nothing, while
`s3://dat-prod-athena-admin/logs/service=api/year=2026/month=09/day=21/data.jsonl` holds them.
`agriffith`'s four probes of `946b415e-…` read `foreign`, the four of the made-up `0b1c2d3e-…` read
`unknown`, and `agriffith_three`'s four of `7e761189-…` read `foreign`. The log records `404 NotFound` for
`agriffith`'s probes; the pages received the same `404` for all twelve.

**Left behind.**
- The space `live0921_iso` (its name is spent), owned by `agriffith_three`.
- `agriffith` as a member of `livecheck_186`, kept until the restore finishes.
- In `livecheck_186`: `live0921_pair/` and its table, `shared_files/agriffith/send_a_0921.csv`, and
  the archive folder for `57d14bb9-…`. The restore will put `live0921_archive/` back.
- `agriffith/live0921_send/`, `agriffith_three/shared_files/agriffith/send_{a,b}_0921.csv`, and the
  table `agriffith_three.live0921_share150`.

---

## Live-check session — 2026-09-21, evening (the owed rows a signed-in session could reach: SPEC-232, -239, -240, -242, -243, -244, the create post-condition, #716, and the narrow widths)

**What was under test.** The SPA image **`8061989c`** (task definition `dat-prod-spa:228`, read from
the service) and the API and planes at **`a1931c9a`** (`/healthz`). Every commit these rows check
is an ancestor of both. `environments.prod` in `config/feature-flags.json` is `{}`. Times are UTC.

**Browsers.** Two, both signed in as **agriffith** by Andrew himself. The Hosted UI cookie had
expired, and each tab reached the credential form. Nothing was typed or clicked on either form by
the session.
- **Chrome**, a tab in the Claude-in-Chrome group: visible, 1512 px wide, for everything except
  the narrow widths. Monaco took input once it had focus: a second click into the editor left
  `document.activeElement` on its `native-edit-context`, and `Cmd+A` plus typing then entered each
  statement. Each statement was read back before it ran.
- **The Claude app's Browser pane**, for 375, 400, 500 and 640 px. Its `resize_window` emulates the
  viewport, so `innerWidth` read exactly the width asked for, and `(min-width: W+1px)` was false at
  each. The pane followed the app's dark theme.

**Instruments, each a way this run differed from a user's.**
- `window.fetch` wrapped in the page's main world to count `POST /v1/queries` (the execution
  count) and the other API calls. It was re-installed after each full load.
- In the pane only: `document.visibilityState` and `hidden` overridden to visible, with
  `visibilitychange` and `focus` dispatched. The pane reported `hidden`, and its poll sat on
  "Running…" until the override.
- Several requests were sent from the page with its own token, in the UI's own wire shape, where the
  UI could not reach the fixture. The interval create adds the two fields only a hand-built request
  can send. The new fixture folders sat past the root listing's first
  page, so the data-quality checks and the table-build creates were sent that way. So was every
  refusal probe. Each row says which.
- One operator call from the laptop CLI: `aws athena start-query-execution` of `SELECT 1` in
  `dat-prod-portal-wg`, output `s3://dat-prod-athena-admin/fallback-results/spec232-probe/`
  (`5dd1fa55-f3bf-4461-bd3e-a7faac8ecc16`, `SUCCEEDED`). Step Functions histories and the API log
  were read with the read-only CLI. The permission classifier refused one in-page batch that
  included a `stop` of that execution. Sent again as single calls, the same probes ran.

**SPEC-232** (`e2e.md` §4.3's row; the `owed.md` section is now settled).

| Check | Result |
|---|---|
| An unknown UUID, then the operator's execution: status, results and row-count | **PASS.** All six answered `404` `{"error":{"code":"NotFound","requestId":…,"detail":"no execution with this id belongs to the caller"}}`, identical apart from `requestId`. |
| `POST …/stop` for each | **PASS.** `404 NotFound`, the same detail, for both. |
| The API log | **PASS.** `logs/service=api/…/day=21/data.jsonl` holds a `request refused` record for each of the eight probes. The four for the unknown UUID carry `execution_ownership: unknown` and the four for the operator's execution carry `foreign`, on `athena.status`, `athena.results`, `athena.rowCount` and `athena.stop`. |
| A query of my own still polls, pages and stops; View DDL | **PASS.** `SELECT * FROM agriffith.explorer150`: one start, one status poll, *Rows 1–100 of 150*. **Next** made one results call and no start, and read *Rows 101–150 of 150*. A running `count(DISTINCT …sha256…)` cross join was stopped about 4 s in: `POST …/stop` 200, and the bar read *Cancelled*. (`e2e.md`'s `count(*)` cross join finished in 1.6 s, too fast to stop.) **View DDL** opened `DDL: explorer150`. |

**SPEC-244** (`e2e.md` §4.3's four rows). The suggestion list was read from the widget's rows, paged with `PageDown`.

| Row | Result |
|---|---|
| Autocomplete follows the statement | **PASS.** `SELECT * FROM agriffith.explorer150 t ORDER BY ` plus `⌃Space` offered 47 items: 43 tables and views, and exactly four columns, `id`, `owner`, `qty` and `region`, each detailed `string · agriffith.explorer150`. With the `FROM` clause deleted it offered 216, with columns from at least 22 tables across `agriffith`, `amits_data_emporium` and `dwb_testing_all`. |
| The dot opens the popup | **PASS.** With the widget closed, typing `.` after `t` opened it on four items, the same four columns. `SELECT * FROM agriffith.` then **Return** gave `SELECT * FROM agriffith.arcb_live_table`, with the database once. |
| The CTAS quoting, against the real engine | **PASS.** Using view `agriffith.spec244_v` (`SELECT 1 AS "Last Name", 2 AS "order"`), in `CREATE TABLE agriffith.spec244_ctas WITH (format = 'PARQUET') AS SELECT `, accepting `last name` inserted `"last name"`. With `FROM agriffith.spec244_v` added, the CTAS **succeeded**, and the catalog shows one column named `last name`. Glue lowercases a column name, so `Last Name` is stored as `last name`. Table and view dropped after. |
| A quoted insert, and the editor's closing quote | **PASS.** Typing `"La` left `"La"`, since the editor closed the quote. Accepting `last name` gave `"last name"`, with one closing quote. `ord` with no quote accepted as `"order"`, and the statement ran and returned its one row. In `DROP VIEW agriffith.spec244_v `, the same `ord` accepted **bare** as `order`. That is the discriminating half: the accepted table and view names in the two `DROP`s would be bare under either rule. |

**SPEC-242** (`e2e.md` §4.5 rows G to K).

| Row | Result |
|---|---|
| G | **PASS.** Two `SELECT id, region, owner, qty FROM agriffith.explorer150 WHERE region = …` statements, both selected, then **Run Statement**: two starts, and a result strip `1 · SELECT id, region, owner, qty…` and `2 · …`, the second selected. |
| H | **PASS.** **Explore in Data Explorer** on the second: `/explore` with no query string, one tab `SELECT id, region, owner, qty…`, those four columns, 38 rows, one start. Later the same statement was run on its own and explored again: another tab, 38 rows, **one** start, no dialog. |
| I | **PASS.** Hid `qty` and applied `id IN ('2', '6', '10')`, giving 3 rows. After a full reload there was one tab, still filtered and still without `qty`, and no dialog. The reload re-ran the stored statement to fetch its rows. |
| J | **PASS.** Grouped by `owner`, giving `owner` and `count_all`. Reopened, the panel's columns were still `id`, `region`, `owner` and `qty`, the statement's, with `owner` listed as the chosen grouping. |
| K | **PASS.** After `SELECT count(*) FROM agriffith.explorer150`, **Explore in Data Explorer** was `aria-disabled` with the title *"Give every column its own name with AS to explore this result."* `SHOW TABLES IN agriffith` offered no button at all. |

**SPEC-243 row O's edit** (rows L to O ran earlier the same day; see the SPEC-243 entry below). This is a new `explorer150` tab, filtered by the two chips again (36 rows).
Open in Query put the statement in a new `explorer150` tab with no execution. The statement was
edited to `SELECT * FROM "agriffith"."explorer150" WHERE "region" IN ('east', 'north', 'south',
'west')` and run, one start returning **150** rows. Back in the Data Explorer, with no start, the
tab held both chips and **36** rows, all Jones. **Back** stepped to the `owner` chip alone (36),
then to no filter (150), then read *"This is the earliest set of filters in this tab."* Neither step
started an execution. **PASS.**

**SPEC-243 row P**, in the pane at 375 px. Filtered `explorer150` to `owner = 'Jones'` (36 rows, and
the tab opened in Record view). **Open in Query** showed the read-only view, with `explorer150` over
`SELECT * FROM "agriffith"."explorer150" WHERE (owner = 'Jones')`, a **Run** button, no editor, and
no start. **Run** started one execution, which returned 36 rows. **PASS.**

**SPEC-239** (`e2e.md` §4.5 steps 8 and 9, on `explorer150` unfiltered).
- With `qty` hidden and `owner` pinned, the dialog said *"The file holds 3 result columns, in the
  order shown."* and offered **Convert and save**. The toast read *"Converting to CSV — you’ll get a
  notification when explorer-hidden-0921.csv is ready."* The notification read *Saved 150 rows as CSV
  to "explorer-hidden-0921.csv".* The file's header is `owner,id,region`, with 150 data rows. **PASS.**
- After **Show all** and **Unpin all**, the dialog offered **Save here**, made a straight
  `POST /v1/objects/copy`, and wrote `explorer-all-0921.csv` with header `"id","region","owner","qty"`
  and 150 data rows. **PASS.**
- Grouped by `region` with **Show percentage**, then `region` and `count_all` hidden. **Save results
  to my files** was `aria-disabled`: *"Show at least one of the result’s columns to save it."*
  Clicking it opened nothing and made no call. **PASS.** Two things on the way: the percentage
  checkbox set through the extension's `form_input` did not register, so the first apply had no
  percentage column, and a `.click()` did register. And until the percentage column showed, the
  Columns drawer refused to hide `count_all`: *"The grid needs at least one visible column."*

**SPEC-240** (`e2e.md` §4.6's three `dq_dupes` rows). The fixtures were uploaded through the portal
from §2's generator into `dq_dupes_0921/` and `dq_dupes_nested_0921/`. Each check was sent to
`POST /v1/enqueue/data-quality` with the dialog's body.

| Row | Result |
|---|---|
| `dq_dupes_0921/` | **PASS.** 7 rows, 2 files, **4 duplicate rows**. *Most repeated rows*: `Ann` `Leeds` `(empty)` ×4 first, then `Bo` `(empty)` `x` ×2, and no `NULL` in the table. |
| *Rows in each file (2 files)* | **PASS.** Closed until clicked, then `dq_dupes_a.csv` **6** and `dq_dupes_b.csv` **1**. A single-file check of `dq_dupes_a.csv` has no such disclosure: 6 rows, 3 duplicates. |
| `dq_dupes_nested_0921/` | **PASS.** The count reads **1**, and *Most repeated rows* shows the sentence about lists and objects in place of a table. |

**The create post-condition** (`owed.md` §1). Fixtures were uploaded through the portal. Each create
was sent to `POST /v1/enqueue/table-build` in the modal's wire shape.

| Row | Result |
|---|---|
| `digits` on an integer key | **PASS.** `live0921_digits` (`num`, range `1,2`, `digits: 2`, over `num=01/` and `num=02/`): *Table "live0921_digits" is ready to query in "agriffith".* `GROUP BY num` gave `1, 10` and `2, 10`. |
| A date key's `interval` and `intervalUnit` | **PASS.** `live0921_interval` (`day`, `2025-01-01,2025-01-05`, `yyyy-MM-dd`, `interval: 2`, `intervalUnit: DAYS`, over `day=2025-01-01/` and `day=2025-01-03/`): ready to query, and `GROUP BY day` gave `2025-01-01, 10` and `2025-01-03, 10`. |
| Two same-name creates | **PASS, inside the window.** `live0921_race` over `live0921race_a/` and `live0921race_b/`, both sent within 218 ms, gave one *ready to query* and one *"Couldn't create table "live0921_race": a table with that name already exists in "agriffith"."* Execution `38512ddd-5357-5527-b743-4ef6ce9c7142` passed `CheckTableAbsent` and failed in `ExecuteDdl`: *"table_exists: table 'live0921_race' in database 'agriffith' was built by another request: its LOCATION is not this one's. Nothing was created."* The table holds `race_a`'s ids 1–10. |

**#716's re-run.**
- **file-ops**, through the API. The vehicle was a copy of `live0921race_a/part1.csv` into
  `agriffith/_data-quality-reports/`, not the ledger's delete of a shared space's root, because a
  copy is harmless if the refusal had regressed. The notification read *"Couldn't copy that: that
  folder is managed for you, so things cannot be put into it."*, with payload
  `{"requestId":"22e202e7-5c4c-4a24-80a4-18268034913e"}`, the request's own id. **PASS.**
- **results-conversion at the terminal.** The execution was `SELECT 1 AS a`, with `onConflict: refuse`
  onto the existing `explorer-all-0921.csv`. The notification read *"Couldn't save the query results
  as CSV: a file called "explorer-all-0921.csv" is already in that folder, so nothing was saved. …"*,
  with payload `{"requestId":"242b7806-9012-4460-8b46-02837535b345","format":"csv"}`. Execution
  `f8aace98-4ce0-5bae-ae79-adb3d2e860f9` ran `ValidateAuthorize`, `DescribeResults`, `Convert` and
  then `NotifyFailure`, so it was refused past the validator. **PASS.** **A first attempt was
  malformed:** it sent `prefix: "agriffith/"`, but the prefix is relative to the space root, so that
  request wrote a new one-row file at `agriffith/agriffith/explorer-all-0921.csv` and reported
  success. The root file was untouched (last modified 20:57:37, 151 lines). This was the probe's
  error, not a defect.

**The narrow widths, in the pane.**
- **SPEC-223's Save-results modal, opened from the Explorer.** At 375, 500 and 640 px the name,
  **Format** and **Save to** fields were full width and stacked: 312 px wide at 375, and 413 px at
  500 and 640. **Convert and save** was 31.5 px tall at each width, and **Save here**, measured at
  375, was too. There was no page scroll at any width. **PASS.**
- **§4.15's list at 400 px.**

  | Item | Result |
  |---|---|
  | Record view on a new tab | **PASS.** `aria-pressed` true on Record. |
  | Toolbar wraps | **PASS.** Six controls; **Options** wraps to a second line, the rightmost ends at 333 px, and there is no page scroll. |
  | Order and filter on its own | **PASS, for one sort and one filter.** Each column offers Show and Pin, a sort (none, ascending or descending), and a filter with eighteen operators. `owner` **equals** `Jones` with `id` **Descending** made one start and 36 rows (97, 93, 9, 89, 85: a string sort), with the SQL `WHERE "owner" = 'Jones' ORDER BY "id" DESC`. |
  | Sticky pinned column | **PASS.** Pinned `id` held at 64 px while the grid scrolled 392 px, and its cell background is opaque. |
  | Right-edge column menu | **PASS.** `qty`'s menu spans 198–382 px of 400, inside the grid's scroller. Its lower items sit below the fold, and the page scrolls to them. |
  | Value panel | **PASS.** A fixed `aside` across 0–400 px at the viewport's foot: a sheet. |
  | Calc and Grouping | **PASS.** Stacked below the grid, which ends at 1027: Grouping 1034–1344, then Calc 1351–1694. |
  | Header drag onto Grouping | **PASS.** A real pointer drag of the `region` header onto the panel added `region` to the grouping columns. |
  | Colors | **PASS.** A rule's controls wrap over five lines inside the dialog. A number-range shading on `qty` (default range 0–100) gave eight shades, with text contrast 6.11–6.15:1 over each, in the dark theme. Banding by `region` alternates the row background and draws a 2 px top border where the band changes. |
  | Suggestion listbox | **PASS.** **Send to…**'s username list, after typing `a`, showed 8 options inside the dialog's box. Cancelled, and nothing was sent. |
  | Anchor in a truncating cell | **PASS.** A Link transformer on `owner`, then its resize separator narrowed with **ArrowLeft** to the 72 px floor. (A first attempt used a pane drag and a synthetic `Home` keydown, which the separator does not handle, and changed nothing.) At 72 px, `Nakamura`'s link truncated, with 84 px of content in a 72 px cell, and stayed on one line. Every row stayed 35 px tall and every `owner` cell 72 px wide, and the next column started at the cell's edge in each row. |
  | Header menu *"unreachable by design"* below `tablet` | **Contradicted in Grid view, and left as a question.** Record view, the default here, has no header. In Grid view `Column options: <column>` is present at 400 px, and `id`'s menu opens with all 21 items. Nothing in the header gates it by width. Whether the docs or the build is right is an open row in `owed.md`'s *Needs 400px*. |
  | *"Every dialog is 392px"* | **Wrong for 400 px, and `e2e.md` is corrected.** Order and filter, Colors, Transformers and Send to… each measured **372 px**, centred, with nothing overflowing. The overlay's 14 px padding (`p-4`) on each side of a full-width panel leaves 400 − 28. |
- **The Files toolbar at 375 px.** With 22 selected, the page's maximum, the toolbar is glyph-only,
  **Delete** ends at 350 px, and *22 selected* reads whole over two lines with nothing clipped.
  **PASS as far as it goes.** A three-digit selection cannot be made: a page holds 25 items, and
  the selection clears on a page change. `e2e.md` §4.15 now asks for a full page instead.

**Left behind.** Tables `live0921_digits`, `live0921_race` and `live0921_interval`, and folders
`dq_dupes_0921/`, `dq_dupes_nested_0921/`, `live0921digits/`, `live0921interval/`,
`live0921race_a/` and `live0921race_b/`. In `agriffith/`: `explorer-hidden-0921.csv` and
`explorer-all-0921.csv`; in `agriffith/agriffith/`, the malformed probe's `explorer-all-0921.csv`.
Also the CTAS's orphaned data under `system_settings/athenaresults/tables/e0971a71-…`, three
data-quality reports, and in the pane's `explorer150` tabs a Link transformer and a colour rule.

---

## Live-check session — 2026-09-21, afternoon (SPEC-245: the footer probe, and polars 1.44.2 on every streamed save)

**What was under test.** Two deploys, read in order. First **`1c09d2e1`** (#863), the footer-only
Parquet probe on polars 1.12.0 — `/healthz` reported that sha and `Deploy Lambdas` had succeeded —
for FR-001's live check and, on the same 1.12 fleet, FR-005's positive control. Then
**`a1931c9a`** (#865), the move to polars 1.44.2, once its `Deploy Lambdas` had succeeded and
`/healthz` reported it, for FR-005's remaining checks. `REPORT` lines were read from
`/aws/lambda/dat-prod-results-conversion-convert` with `aws logs filter-log-events`; times are UTC.

**Browser.** Andrew's Chrome through the Claude-in-Chrome extension, as **agriffith**, in a new tab
in the extension's group. It came up signed out, and one click on the portal's **Sign in** signed it
in on the Hosted UI cookie; no credential form was shown. Viewport 1568 × 760.

**Instruments, each a way this run differed from a user's.**
- `document.visibilityState` and `hidden` overridden to visible, with `visibilitychange` and `focus`
  dispatched, after each full load.
- **Monaco took input, and the difference from the session below is focus.** After a page load the
  first click leaves focus outside the editor, so a `Cmd+A` selects the page and typing goes
  nowhere. Clicking into the editor again, or clearing through the workspace's own **Clear**
  dialog, left `document.activeElement` on Monaco's `native-edit-context` element, and
  `computer.type` then entered each query whole. Each query was read back before it ran — from the
  rendered line for a short one, and by `Home`/`End` screenshots for a long one, because Monaco
  renders only the scrolled-into-view part of a long line.

| Row | Result |
|---|---|
| **FR-001 — a table build over a Parquet folder**, on `1c09d2e1` | **PASS.** `agriffith/conv0910_parquet/` (one 1.9 KB file) built as `spec245_probe_parquet`: *"Table "spec245_probe_parquet" is ready to query in "agriffith"."* |
| **FR-001 — a data-quality check over the same folder** | **PASS.** *"Data quality check on "agriffith/conv0910_parquet/" finished — open the report for details."* |
| **FR-005 positive control — the 200,000-row multi-line query saved as Parquet in full**, on 1.12 | **Refused, as the control requires.** *"Couldn't save the query results as Parquet: part of the results could not be read, so "spec245-pc-full.parquet" was not written. …replacing those line breaks in the query will…"* `REPORT` 17:07:12Z: 4,349 ms, 151 MB, cold. No file was written. |
| **The same, as view `agriffith.spec245_pc_view` in Data Explorer with `doc` hidden**, on 1.12 | **Refused** the same way, for `spec245-pc-view-idonly.parquet`. `REPORT` 17:08:44Z: 507 ms, 152 MB. |
| **The query saved as Parquet in full**, on `a1931c9a` | **PASS.** *"Saved 200,000 rows as Parquet to "spec245-live-full.parquet"."* `REPORT` 17:42:10Z: 11,309 ms, 190 MB. |
| **The query saved as JSON in full** | **PASS.** *"Saved 200,000 rows as JSON to "spec245-live-full.json"."* `REPORT` 17:42:12Z: 3,928 ms, 192 MB, on a second, cold instance. |
| **The view saved as Parquet with `doc` hidden** | **PASS.** *"Saved 200,000 rows as Parquet to "spec245-live-view-idonly.parquet"."* — 200,000 and not 200,002, which is what 1.12 wrote for this shape before the stopgap. `REPORT` 17:42:47Z: 1,686 ms, 192 MB. |
| **Every scalar type through Parquet and a table build** — the typed query saved into `spec245_typed/`, then **Create table** over it | **PASS.** *"Saved 1,000 rows as Parquet to "spec245-typed.parquet"."* (`REPORT` 17:44:57Z: 1,660 ms), then *"Table "spec245_typed" is ready to query in "agriffith"."* `SELECT * FROM agriffith.spec245_typed EXCEPT <the query>` returned **0 rows**, 18 KB scanned, and `<the query> EXCEPT SELECT * FROM agriffith.spec245_typed` returned **0 rows**, 18 KB scanned. The second is the positive control for the first: an empty or wrong table returns rows there. |
| **A data-quality check over `spec245_typed/`** | **PASS.** *"Data quality check on "agriffith/spec245_typed/" finished — open the report for details."* |
| **The largest Excel conversion the cell cap admits** (`e2e.md` §4.3, regenerated for 3,900,000 cells) | **PASS on both bounds.** *"Saved 975,000 rows as Excel to "spec245-at-cap.xlsx"."* `REPORT` 17:51:50Z: **Duration 58,685 ms** against 120 s, and **Max Memory Used 2,115 MB** against the model's 2,517. On polars 1.12 the 1,025,000-row input of the old cap read 2,410. |

**Left behind.** Tables `spec245_probe_parquet` and `spec245_typed`, view `spec245_pc_view`, the
folder `spec245_typed/` with `spec245-typed.parquet`, and in `agriffith/` the files
`spec245-live-full.parquet`, `spec245-live-full.json`, `spec245-live-view-idonly.parquet` and
`spec245-at-cap.xlsx`. The two data-quality reports stay under the space's report folder.

---

## Live-check session — 2026-09-21 (SPEC-243's chips and Open in Query, `e2e.md` §4.5 rows L to P)

**What was under test.** `main` at **`a40c26f7`** (#861). `Deploy SPA image` for that sha had
succeeded before the run. The table was `agriffith.explorer150`, with columns `id`, `region`, `owner`
and `qty`.

**Browser.** Andrew's Chrome through the Claude-in-Chrome extension, as **agriffith**, in a new tab
in the extension's group. It came up signed out. One click on the portal's **Sign in**, dispatched
from the page, signed it in on the Hosted UI cookie from Andrew's own sign-in minutes earlier. No
credential form was shown, and nothing was typed into one. The page reported `innerWidth` 1512
throughout, and `visibilityState` `hidden`.

**Instruments, each a way this run differed from a user's.**
- `document.visibilityState` and `hidden` overridden to visible, with `visibilitychange` and `focus`
  dispatched, so TanStack's polls kept running in the hidden tab. Re-applied after each reload.
- Clicks by coordinate or element reference did not land in the hidden tab. Buttons, menu items and
  the Generated SQL `<summary>` were activated with `.click()`, and the filter dialog's fields were
  set through the native value setter followed by an `input` event.
- `window.fetch` wrapped to record the SQL of every `POST /v1/queries`, which is the execution
  count. Re-installed after each reload.

**Readings.** They are the table in `owed.md`'s SPEC-243 section. Every statement recorded matched
the chips on screen, for example `WHERE ("owner" = 'Jones' AND "region" IN ('east', 'north',
'south', 'west'))` for row L's two chips.

**What could not run.** Monaco took no input: `computer.type`, `execCommand('insertText')` and a
synthetic `input` event each left the persisted buffer unchanged. For row P the window was resized
to 500 × 900, and Andrew saw it at that width in front and beside the Claude app. The page never
left `hidden`, `outerWidth` read 0 or 314, and `innerWidth` stayed 1512 through three reloads. A
same-origin `<iframe src="/explore">` harness was refused, since the portal will not be framed.

---

## Live-check session — 2026-09-16, later afternoon (#809: an ordinary partitioned create still reports created)

**What was under test.** `origin/main` at **`8f1ac932`** (#830), which carries #809 (`b90f508d`):
execute-ddl reads a table back after `CREATE … IF NOT EXISTS` and refuses `table_exists` unless the
catalog carries this run's LOCATION, partition keys and `projection.{key}.*` exactly as
`cpcommon.ddl.projection_properties` rendered them. Run at the supervisor session's request, for the
row in [`owed.md`](owed.md). `Deploy Lambdas` for `8f1ac932` had finished at 19:29Z, and the API's
`/healthz` reported `8f1ac93290ea142b8d6eb83933f48011251cc0e2` straight after the readings.

**Browser.** Andrew's Chrome through the Claude-in-Chrome extension, as **agriffith**, in a new tab
in the extension's group. It came up signed out; **one click on the portal's own Sign in button**
signed it in, because the Hosted UI session cookie from Andrew's sign-in about half an hour earlier
was still live. No credential form was shown, and nothing was typed into one. Viewport 1568 × 724.

**Instruments — each a way this run differed from a user's.**
- **Fixtures by deep link.** Two `id,amount` CSVs of three rows each were uploaded through the
  page's upload drawer after opening `/files?prefix=agriffith/<folder>/<key>=<value>/` directly, so
  the `key=value` folders came from the uploads' keys.
- **The creates did not go through the modal's button.** The new folders sat past the root listing's
  first pages, so each create was `POST /v1/enqueue/table-build`, sent in-page with the tab's own
  idToken, carrying the body `CreateTableButton` and `enqueueTableBuild` send: `space.prefix` is the
  selected folder, an integer `range` is stringified, a date key carries `format` and no interval.
- **Queries in-page** through `/v1/queries`, returning only rows.

**Readings.**

| Row | Result |
|---|---|
| Integer key: `live809int_0916b/year=2024/` and `year=2025/`, key `{name: year, type: integer, range: [2024, 2025]}`, table `live809_int_0916b` | *Table "live809_int_0916b" is ready to query in "agriffith".* `SELECT year, COUNT(*) … GROUP BY year` returned `2024, 3` and `2025, 3`. **Pass.** |
| Date key named `dt`: `live809date_0916b/dt=2025-01-01/` and `dt=2025-01-02/` | *Couldn't create table "live809_date_0916b": the partition keys aren't valid (check names, types, and ranges).* validate-authorize holds a key name to `CATALOG_IDENTIFIER_RE`, `^[a-z][a-z0-9_]{2,62}$`, so a two-letter name is refused before any DDL. The modal enforces the same rule on the field, so a user sees a field error rather than this notification; it appeared only because the create bypassed the modal. Not this check's defect, and the rule was left alone. |
| Date key named `day`: `live809day_0916b/day=2025-01-01/` and `day=2025-01-02/`, key `{name: day, type: date, range: [2025-01-01, 2025-01-02], format: yyyy-MM-dd}`, table `live809_date_0916b` | *Table "live809_date_0916b" is ready to query in "agriffith".* `SELECT day, COUNT(*) … GROUP BY day` returned `2025-01-01, 3` and `2025-01-02, 3`. **Pass.** |

**Not run.** `digits` on an integer key — still owed. `interval` or `intervalUnit` on a date key, which only a hand-built request can send — owed at lower priority.
The loser of two same-name creates. The admin logs were not read, since nothing was refused as
`table_exists`. Fixtures and both tables were left in place.

---

## Live-check session — 2026-09-16, afternoon (a CSV column named after a partition, `e2e.md` §4.4 and §4.6)

**What was under test.** `origin/main` at **`582e93b2`** (#829). `scripts/watch_ci.py --branch main`
had settled green on it: Deploy Lambda image, Deploy Lambdas and Deploy SPA image. The next merge,
#830 (`8f1ac932`), deployed from 19:21Z to 19:29Z while the later readings ran; it changes no runtime
code — a docstring, two tests and `api.md` — so nothing these requests reached behaved differently.

**Browser.** Andrew's Chrome through the Claude-in-Chrome extension, as **agriffith**, in a new tab
in the extension's group. It reached the Hosted UI form with the password filled; Andrew signed that
tab in himself, and nothing was typed into the form. Viewport **1512 × 732** CSS px, so the report's
Columns rendered as the desktop rows, not the phone cards.

**Instruments — each a way this run differed from a user's.**
- **Fixtures by path, not by folder dialog.** `yearcase.csv` and `yeartrail.csv`, generated with
  §2's recipe, were uploaded through the page's own upload drawer after opening
  `/files?prefix=agriffith/partrename0916/yearcase/year%3D2025/` (and `yeartrail/…`) directly, so
  the `key=value` folders came into being from the upload's key rather than from New folder.
- **Queries and the refresh sent from inside the page.** `fetch` to `api.dataquarry.app` with the
  tab's own idToken, returning only statuses and rows; the token never left the page. The two
  creates and the data-quality check went through the UI's own dialogs.
- **A refresh request built wrongly first.** One `POST /v1/enqueue/table-refresh` carried the key
  `year` in `partitionKeys` and was refused by notification (*"a refresh keeps the table's existing
  partition keys"*), which is the designed answer; the UI always sends `[]`. The second, with `[]`,
  is the reading below.

**Readings.**

| Row | Result |
|---|---|
| Build `partrename0916/yearcase/` (header `Year,id,region`), key `year` string `2025`, as `yearcase0916` | Ready notification: *Table "yearcase0916" is ready to query in "agriffith". A column named after a partition key keeps its values under a new name: "Year" is "year_in_file".* `SELECT year_in_file, id, region, year … ORDER BY id` returned, as the first three of its five rows, `2025, 1, south, 2025`, `2025, 2, east, 2025` and `2025, 3, west, 2025`; `SELECT * … LIMIT 1` listed `year_in_file, id, region, year`, which stood in for reading the rail. **Pass.** |
| Build `partrename0916/yeartrail/` (header `id,region,year`), same key, as `yeartrail0916` | Notification names `"year" is "year_in_file"`. `SELECT id, region, year_in_file, year` returned `1, south, 2025, 2025` as its first row. **Pass.** |
| Refresh `yearcase0916` with nothing changed | *Table "yearcase0916" is already up to date - no schema changes were found.* **Pass.** |
| Check `partrename0916/yearcase/` | Report `5383617a-dfe0-4f34-82df-ce100c5a2349`: **No issues found**, 5 rows, 1 file, no cross-file section. Above Columns: *Year is listed as year_in_file. The folder has a partition of the same name, and a CSV’s columns are read in order, so the file’s own column keeps its values under a new name.* Columns `year_in_file` BIGINT 0 0%, `id` BIGINT 0 0%, `region` TEXT 0 0%. **Pass.** |

**Not run.** The schema rail itself, for either table — so `yeartrail0916`'s column order was not read; `yeartrail/`'s data-quality check; and a JSON or Parquet folder's `omitted` line.

---

## Live-check session — 2026-09-13, evening (SPEC-231's four row-count rows in `e2e.md` §4.3)

**What was under test.** `origin/main` at **`430a1b7e`** (#741). `scripts/watch_ci.py --branch
main` had settled green on it, `Deploy SPA image` included. The discriminating observation that the
page was #741's: its first request after `SUCCEEDED` was `GET …/row-count`, which no earlier SPA
sends.

**Browser.** Andrew's Chrome through the Claude-in-Chrome extension, as **agriffith**, in a new tab.
The Hosted UI cookie had expired again (Cognito's tokens live in `sessionStorage`, which is per
tab). Andrew gave explicit permission in chat to click **Sign in** on the form Chrome's password
manager had filled, and nothing was typed into it. Rows per page were at the default, **100**.

**Instruments — each a way this run differed from a user's.**
- **Visibility overridden.** The tab's real `visibilityState` was `hidden`: Control_Chrome
  switched to it but cannot raise Chrome above other windows. TanStack pauses the workspace's status
  poll on a hidden page, so the tab's `document.visibilityState` and `document.hidden` were
  overridden to report visible, and a `visibilitychange` was dispatched. Monaco does not repaint on
  a hidden page, so each statement was read back from the workspace's persisted tab state
  (`sessionStorage`) before it was run, not from the editor's DOM.
- **A logging `fetch` wrapper,** which blocked nothing, recorded every `/v1/queries` call and each
  `…/row-count` answer. The status bar was read from `[role=status]`, and the pager label from the
  page text.

| `e2e.md` §4.3 row | Bar | Pager | `…/row-count` | `…/results?maxRows=1000` |
|---|---|---|---|---|
| The 10M-row `UNNEST` query | **"10,000,000 rows"** · 0 B · 7.9 s | `maxRows=100` only | 1 call → `{"rowCount": 10000000, "pending": false}` | **0** |
| `SELECT x FROM UNNEST(sequence(1, 12345)) AS t(x) WHERE x % 7 = 0` | **"1,763 rows"** | "Rows 1–100 of 1763"; after 17 × **Next**, "Rows 1701–1763 of 1763", Next disabled | 1 call → `1763` | **0** |
| `SHOW TABLES IN agriffith` | **"20 rows"** | "Rows 1–20 of 20" | 1 call → `{"rowCount": null, "pending": false}` | 1 (the walk) |
| `EXPLAIN SELECT x FROM UNNEST(sequence(1, 10)) AS t(x)` | **"20 rows"**, never 1 | "Rows 1–20 of 20" | 1 call → `{"rowCount": null, "pending": false}` | 1 (the walk) |

**Verdict: all four rows pass.** `owed.md`'s row-count defect is closed.

---

## Live-check session — 2026-09-13 (the shell remount, re-run after #732)

**Scope.** The re-run owed by the sweep's fifth defect: `RootLayout`'s `<ErrorBoundary
key={pathname}>` remounted the signed-in shell on every route change, aborting uploads and dropping
the in-flight file operations. #732 made the boundary reset by a `resetKey` prop, added a second
boundary inside the shell, and gave its crash panel a notice. What ran is `e2e.md` §4.2's
navigate-away row and its neighbours in the async switchover, and the new row for an upload that
survives a route change.

**Browser.** `origin/main` at **`3d1a7450`**, #732's merge, with `Deploy SPA image` green. The served
chunk `schema.partition-B3SkIsga.js` carries the notice's copy, *"Reloading cancels the"*, which exists
only after #732, so the page under test was #732's. Signed in as **agriffith** in Andrew's Chrome, in
the tab that was already signed in, driven through `Control_Chrome` (AppleScript `execute
javascript`). The Claude-in-Chrome extension could not reach that tab, since it now drives only
tabs in its own group, and a new tab would have opened signed out: Amplify's tokens are kept in
tab-scoped `sessionStorage` (`src/lib/amplify.ts`, `setKeyValueStorage`).

**Instruments — three ways this run differed from a user's, each stated.**
- **`Control_Chrome`'s JavaScript runs in an isolated world.** Patches on `XMLHttpRequest` and
  `fetch` recorded **nothing** while the upload plainly ran. Resource Timing and the DOM are shared
  across worlds, so every claim below rests on those two. An aborted request leaves no resource
  entry, so the upload's evidence is positive: parts still minted after the navigation, `PUT`s that
  finished 200, a `complete` that returned 200, and no `/upload/abort` entry at all.
- **Not foregrounded.** `visibilityState` read `hidden`. An override set from the isolated world
  never reached the page, so the app's notification poll stayed paused. The notification that
  settled the card was therefore brought in by **visiting `/notifications` by its header link**,
  not by the background poll. That visit was also a real route change, and the shell survived it.
- **A synthetic file and synthetic events.** A 524,288,000-byte zero-filled `File` was built in the
  page and handed to the app's own `input[aria-label="Choose files"]` through a `DataTransfer` and a
  `change` event, because the extension's `file_upload` caps a call at 10 MB. Clicks were `.click()`
  on the real controls; Escape was a synthetic `keydown`.

**The upload survives a route change — PASSES.** Times are page time.
- The upload reached **63%**, the drawer was closed with Escape, and the **Query** tab was clicked
  at **102.3 s**.
- **Two part `PUT`s were in flight then** — two run at once — and **both finished 200**: part 3
  (85.3 → 115.7 s) and part 4 (90.6 → 123.2 s). The fifth part was **minted at 115.7 s**, 13 s after
  leaving Files, and its `PUT` finished 200 at 130.1 s. `POST /v1/objects/upload/complete` returned
  **200** at 130.5 s. **No `/upload/abort` was sent.**
- On `/query`, read after the script's 4 s wait, the shell's wrapper (`div.flex.flex-1` under
  `RootLayout`'s column) was **the same DOM node** as before the click. On 2026-09-10 it was a new
  node.
- The upload **finished while the page was still on `/query`**. Back on `/files` by its tab, the
  queue listed `shellnav0913.bin`, **Uploaded**, 500.0 MB — so the row's *come back while it is still
  running* half, the drawer picking up a live upload again, was not observed.

**A folder move survives a route change — PASSES.** Two empty folders, `shellnav0913_src` and
`shellnav0913_dst`, were made for it.
- The move showed its card at once: *"Moving shellnav0913_src · Started just now · Running in the
  background"*. Move was ungated before it.
- On **`/query`** the card still read *Running in the background* — its own label said *Started 14
  sec ago* — and the shell was the same node.
- Back on **`/files`** the card was still there (*Started 18 sec ago*). About **19 s** after the move
  by the instrument's clock, selecting the folder `arcb_files` gave
  **Copy, Move, Delete and Archive all `aria-disabled="true"`**, each titled *"Another file operation
  is still running here. Wait for its notification, or dismiss it…"*. On 2026-09-10 all four were
  enabled after the round trip.
- On **`/notifications`, 104 s after the move**, the card read *"Finished — see your notifications
  for what happened"*, beside the row *"Moved 1 item to "shellnav0913_dst""*. That row read *1 min
  ago*, so the move had finished before this visit: only the Query round trip happened while it ran.
- Back on `/files`, the same selection had all four **enabled**, so the space was free again.
  *Refresh this folder*, pressed, showed `shellnav0913_src` gone from the root, with
  `shellnav0913_dst` still there. **Dismiss** removed the card.
- The shell's wrapper was the same DOM node through all four route changes.

**Left behind, for Andrew to delete by hand.** `shellnav0913.bin` (500 MB of zeros, at the root)
finished before it could be cancelled, and `shellnav0913_dst/` sits at the root with the empty
`shellnav0913_src/` inside it. Nothing was deleted from this session.

**Not run.**
- **400 px.** It needs the device toolbar, and the window was hidden.
- **Returning to Files while the upload is still running.** It finished on `/query`, so the drawer
  was never seen picking a live upload back up.
- **The listing after a real focus return.** Only the button half of *Refresh this folder* ran.
- **Whether *Check data quality* and *Send to…* stay enabled while the space is gated.**
- **The rest of the async-switchover table.** *Copy a folder into its own folder* and *Details on a
  folder the plane has just deleted* were untouched by this defect, and the second needs a delete.
- **The shell's crash panel and its notice.** No page can be made to throw in production; the
  suite drives them.

---

## Live-check session — 2026-09-13 (the log-sweep re-run, CLI only)

**Scope.** `owed.md`'s *log sweep is saturated* row, after #720 (the alarm's deploy grant) and #724
(the logs queue grouped per event, and the `logs-backlog` alarm). Deploy Lambdas pointed the fleet
at `1043d59f` on 2026-09-11 at 03:33Z. **Instruments:** read-only CLI alone — `AWS/SQS` metrics and
`describe-alarm-history` for `dat-prod-logs.fifo`, and the `service=observability` and `service=api`
day objects for 2026-09-11 to 2026-09-13. **No browser and no driven load:** the one portal tab was
signed out, so everything below is organic traffic.

- **The pre-deploy backlog drained in two hours.** It was still in the old per-service groups, so it
  drained at ten a wave: 5,398 messages at 03:34Z, 20 at 05:37Z. The alarm was created at 03:28Z
  and went `INSUFFICIENT_DATA` → `ALARM` on that backlog → `OK` at 05:31Z. It has not changed state
  since. The first scheduled sweep after the deploy (03:34Z) took **116** messages in its first wave,
  **86 of them from `service=observability` alone**, where the old grouping capped a wave at ten
  per service.
- **The load that could tell the fix from the defect was a scanner, not a person.** The working
  sessions since the deploy were light: the busiest ran 400–486 messages an hour against an idle
  floor of 211. The one burst above the old ceiling came on 2026-09-12: a probe request at
  01:13:59Z, then 431 more in the minute from 01:17:08Z (`GET /wp/v2/posts/999999` and its
  variants). Together they put **1,296 `service=api` events** on the queue, about 1,330 messages in
  that ten-minute tick. That is a fifth of 2026-09-10's worst tick of 6,594. Grouped by service, the
  API group could give up at most 500 a sweep, so the first sweep after it would have stopped on
  `wave-cap`. The first request's three events went in the 01:14Z sweep. The 01:24Z sweep took the
  1,293 left in **one run of three waves** (1,000, 337 and 10) in 3.6 s, with no stop reason, 980 of
  them API events appended in a single write.
- **The first full wave, measured.** 1,000 messages took about 2.5 s from one receive to the next
  (2,484 ms): 100 receive rounds in 1,071 ms (10.7 ms each), the 980-event API rewrite in 328 ms,
  98 delete batches in about 0.9 s, and a 90 ms observability rewrite. The plane page had derived
  5–7 s. So about 95 full waves fit in the budget, and the wave cap binds first, at about half of
  it, not where the reserve does.
- **Every run since has ended clean.** 356 sweeps found messages between 2026-09-11 05:40Z and
  2026-09-13 16:54Z, all on `1043d59f`. **None stopped with a reason**: 287 took one wave, 66 took
  two and 3 took three. So the chase a live session can drive, where each wave finds the last one's
  arrivals, has not happened on real traffic yet. `ApproximateAgeOfOldestMessage` peaked at 591 s
  in its worst hour, which is one tick. The scanner's last event (01:18:10Z) was written by the
  second wave at 01:24:37Z.
- **Idle volume fell.** Idle arrival is now 211 messages an hour, about 35 a tick, down from 73–80 a
  tick. `service=observability` wrote 1.19 MB on 2026-09-12, against 4–10 MB on an ordinary day
  since 2026-08-14 (16.0 MB on 2026-09-10). The sweep now drains its own events in one wave, not
  six.
- **Not run:** a tick at 2026-09-10's intensity. No sweep has taken a second full wave or chased a
  live session's arrivals. That day's session hours carried 10,371, 6,490 and 5,089 API events,
  and its worst tick queued 6,594 messages, five times the scanner's. `owed.md` carries it as its
  own row under *Needs the CLI*.

---

## Live-check session — 2026-09-13 (SPEC-231 FR-003: is the row count's first number final?)

**Scope.** FR-003, the measurement that gates SPEC-231's browser switch-over. The route
`GET /v1/queries/{id}/row-count` was polled through the window after `SUCCEEDED`, before any
browser code called it.

**What was under test.** `origin/main` at **`e75e60fa`** (#731). `scripts/watch_ci.py --branch
main` had settled green on it, `Deploy Lambdas` included. The first route answer, a `409` while
running and then a counted `200`, is behaviour only #731's code produces, which is the
discriminating observation that the route was live.

**Browser.** Andrew's Chrome through the Claude-in-Chrome extension, as **agriffith**, in a new tab.
The Hosted UI cookie had expired, and the credential form came up already filled by Chrome's
password manager. Andrew gave explicit permission in chat to click **Sign in**, and nothing was
typed into it. The first load of `/query` after the deploy failed on a stale chunk ("Failed to fetch
dynamically imported module …/QueryPage-….js"); the app's error boundary said to reload, and one
reload fixed it.

**Instruments — each a way this run differed from the spec's wording.**
- **The app's own bearer, captured.** `window.fetch` was wrapped so that the app's next API request
  supplied the Authorization header, reused for the polls. The same wrapper **blocked** every
  `…/results?maxRows=1000` request, so the old walk added no load. Each `POST /v1/queries` started
  a poll of `GET /v1/queries/{id}` and `GET /v1/queries/{id}/row-count` side by side, which ran
  until 10 s after the status first read `SUCCEEDED`.
- **Not foregrounded.** `visibilityState` read `hidden`. On the first run, `setTimeout(…, 200)` was
  throttled to 1 s (maximum gap 1,002 ms). Runs 2 and 3 used a timer-free loop that starts each
  poll when the last one resolves; median gaps were 256 ms and 275 ms, maximums 603 ms and 499 ms.
- **Run 3 was started from the page, not the Run button.** While the page is hidden, TanStack pauses
  the workspace's own status poll, so the UI still showed run 2 as running and offered no Run button.
  Run 3's `POST /v1/queries` was sent from the page with the same session, through the same wrapper.
  It is the request the Run button sends.

| Execution | Statement | `SUCCEEDED` seen at | Before it | Polls after | After it | Pending after | Numbers returned |
|---|---|---|---|---|---|---|---|
| `df8c983f` | 10M `UNNEST` generator | 8,642 ms | `409` only | 11 | all `200` | 0 | **10,000,000** only |
| `7093d745` | 2M `UNNEST` generator (`sequence(1,2000)` × `sequence(1,1000)`) | 2,207 ms | `409` only | 36 | all `200` | 0 | **2,000,000** only |
| `ffc542c0` | `WITH t AS (…12345…) SELECT x FROM t WHERE x % 7 = 0` | 339 ms | `409` only | 36 | all `200` | 0 | **1,763** only |

**Verdict: FR-003 passes on all four criteria.**
- The number was already present on the first poll that saw `SUCCEEDED`, in every run, and it never
  changed afterwards.
- It equalled the count known by construction.
- No answer after `SUCCEEDED` was anything but a `200`.

**What this did not exercise:** the re-ask path. No answer was ever `pending`, so
`ROW_COUNT_PENDING_DELAYS_MS` is covered by its tests and by AWS's documentation that the
statistics can lag, not by a live lag.

---

## Live-check session — 2026-09-11 (the top-bar band, re-run after #725)

**Scope.** The re-run owed by the sweep's top-bar defect, which #725 fixed together with the Files
selection toolbar's overflow that the header's had hidden. `/files` throughout, because the toolbar
is there.

**Browser.** `origin/main` at **`c02f7996`**. `Deploy SPA image` was green, and the served
stylesheet `index-B285Y5xH.css` carries `.tablet\:truncate` and `.desktop\:\!px-3`, rules that
exist only after #725, so the page under test was #725's. Signed in as **agriffith** in Andrew's
Chrome through the Claude-in-Chrome extension, in a new tab, which the warm Hosted UI cookie signed
in with one click — no credential form was shown. The listing held 33 rows.

**Instruments — two ways this run differed from the row's wording, each stated.**
- **Not foregrounded.** `visibilityState` read `hidden` throughout: `Control_Chrome` was not in this
  session and a computer-use grant for Chrome could not be obtained. (`Control_Chrome` appeared when
  the session resumed on 2026-09-13, by which time the Hosted UI cookie had expired and a new tab
  reached the password form, which is Andrew's to submit.) Each width was instead set with
  `resize_window` followed by a **reload**, and the viewport was proven at every width — `innerWidth`
  equal to the requested width, `(min-width: W px)` true and `(min-width: W+1 px)` false. Without the
  reload the hidden tab took two resizes and then stuck at 930 through four more, which is
  `e2e.md` §1's stale-viewport trap in a new shape, caught only because every reading printed
  `innerWidth`. That a hidden tab lays out on demand, so geometry reads true once the viewport does,
  is inference — sound for this check, which reads only synchronous geometry, and none of the
  components under test measures with a `ResizeObserver` or a frame callback. What waits on a frame
  it cannot show: a screenshot of the tab timed out.
- **The scrollbar was forced.** This Mac showed overlay scrollbars at the time — `clientWidth` equal
  to `innerWidth` on a page that scrolls — where the sweep had a classic 15 px one. Each width in the
  band was read with `html{overflow-y:scroll}` and `::-webkit-scrollbar{width:15px}` injected, which
  gives the sweep's `innerWidth − 15`; 900, 930 and 959 were read natively as well.

| `innerWidth` | `clientWidth` (forced / native) | `scrollWidth` | Account button's right edge | Tabs | Selection toolbar |
|---|---|---|---|---|---|
| **900** | 885 / 900 | equal, both | 871.0 / 886.0, no username | one line each, no icons | six labels on one line, no glyphs, Delete inside the bar |
| **930** | 915 / 930 | equal, both | 901.0 / 916.0 | as above | as above |
| **959** | 944 / 959 | equal, both | 930.0 / 945.0 | as above | as above |
| 1024 | 1009 | equal | 995.0 | as above | as above |
| 1299 | 1284 | equal | 1270.0 | as above | as above |
| 1300 | 1285 | equal | 1271.0, username back at 47.7 px | five icons back | glyphs back beside the labels |
| 1512 | 1497 | equal | 1483.0 | as at 1300 | as at 1300 |
| 899 / 768 | 884 / 753 | equal | 870.0 / 739.0 | hamburger, tab strip hidden | glyph-only, Delete inside the bar |

No element of the header reached past `clientWidth` at any width. The account button's edge sits
14 px inside `clientWidth` at every width — the header's `px-4`, not spare room. The font in use was
not recorded; the verdict holds under either, since the fallback leaves more room than Inter (21 px
against 14, the register's `tablet` band entry). The before-picture is the sweep's own: 945 px of
page in an 885 px `clientWidth` at 900. **375 was not run live** — it is below Chrome's minimum
window width and needs the DevTools device toolbar; before #725's push it was measured in harnesses
only, and it stays owed with the 400 px pass.

**Left behind.** Nothing. The run resized, reloaded and read; nothing was selected or written.

---

## Live-check session — 2026-09-10, third sitting (two sweep defects re-run after #719, and the row-limit separator)

**Scope.** The re-runs owed by the two sweep defects #719 fixed — the overwrite cancel and the
relative listing prefix — and, as corroboration at the sweep's exact shape, the Excel row-limit
separator #718 fixed. That last row was closed by SPEC-230's own re-run, the second sitting below.

**Browser.** `origin/main` at **`04c9c481`**. `Deploy SPA image` was green, and the served bundle
carries `startPrefix`, an identifier that exists at `04c9c481` and nowhere at `c4ea4413`, so the
page under test was #719's. `Deploy Lambdas` was still rolling during the API probes and finished
green at 02:02Z; that the API function had already switched is shown by the probes themselves (see
the relative prefix below). Signed in as **agriffith** in Andrew's Chrome through the
Claude-in-Chrome extension, in a new tab which the warm Hosted UI cookie signed in with one click —
no credential form was shown. `innerWidth` read 900.

**Instruments.** `e2e.md` §1's `visibilityState` override before every wait. The API probes were
in-page `fetch`es carrying the tab's own idToken, returning statuses, codes and keys only.

- **The overwrite cancel — PASS.** A Parquet save named `explorer150_conv` into
  `conv0910_parquet/`, which already holds `explorer150_conv.parquet`, raised *Overwrite
  "explorer150_conv.parquet"?*. Cancel reopened the dialog with the name
  `explorer150_conv.parquet`, format Parquet, Save to *My files* and the picker at
  `My Files / conv0910_parquet` — where the sweep got `query-results-…`, CSV and the root. The
  dialog was then cancelled; the file's `lastModified` stayed at 19:37:54Z. *My files* is also the
  dialog's default, so this sitting does not show the space restore; that half rests on #719's
  shared-space integration test.
- **The row-limit separator — PASS.** `SELECT a, b FROM UNNEST(sequence(1, 1049)) AS t(a) CROSS
  JOIN UNNEST(sequence(1, 1000)) AS u(b)` (0 B scanned), saved as Excel to `rowlimit0910`, was
  refused with *"…the results have 1,049,000 rows, which is more than a spreadsheet can hold, so
  "rowlimit0910.xlsx" was not written…"*. #719 did not change the results-conversion code.
- **The relative prefix — PASS.** A fixture folder `agriffith/agriffith/inner/` was made with the
  portal's *New folder*, which navigated into the self-named folder without trouble. Straight to
  `GET /v1/objects`: `prefix=agriffith/agriffith/` answered **200** listing exactly
  `agriffith/agriffith/inner/`; `prefix=agriffith/` answered **200** with the root, which holds
  `agriffith/agriffith/` and not `inner/`; the relative `arcb_files/` and `inner/` both answered
  **403 `AccessDenied`**, *"prefix is not inside the space root"*. The two 200s would pass on the
  old code too; the 403s are what tell the two apart, because the code at `c4ea4413` re-rooted a
  relative prefix and answered 200. The function had already switched when the first probe ran, so
  there is no before-picture from this session — the sweep's reading of the code is the before.

**Left behind.** The fixture folder `agriffith/agriffith/inner/`, kept rather than deleted, since a
delete here is permanent. One failure notification for `rowlimit0910.xlsx`, for which nothing was
written; the overwrite check wrote nothing.

---

## Live-check session — 2026-09-10, second sitting (SPEC-230's three Excel rows in `e2e.md` §4.3)

The day's sweep is the next section; a pointer elsewhere to "the 2026-09-10 section" means that one.

**Browser and CLI.** `origin/main` at **`c4ea4413`** (#718), and the converter running the image
tagged with that commit. Signed in as **agriffith** in Andrew's own Chrome through the
Claude-in-Chrome extension, at 900 px, which none of these checks depends on. CLI identity
`arn:aws:iam::696000197480:user/tofu-deploy-user`, **reads only**: `filter-log-events` on the
converter's and notify-failure's log groups, `get-function`, and a `head-object` on each output,
which this identity is refused. **No AWS write was issued from the CLI**; the portal's own routes
wrote two files (see *Left behind*). Log times are UTC, which was already 11 September.

**Instruments.** `e2e.md` §1's `visibilityState` override after every full load. Each query was
typed through the extension and read back from the editor's rendered lines before it ran. Whether a
file was written was read from the Files listing, because of that refusal.

| Row | Result |
|---|---|
| **The Excel cell limit**, the query that ran the converter out of time, saved as Excel | **PASS.** Submitted 01:04:44; the converter downloaded 62,914,590 bytes and logged `refused excel_cell_limit` at 01:04:55, eleven seconds after the submit. `REPORT`: **3,093 ms, 251 MB**, on a cold start. The notification, verbatim: *"Couldn't save the query results as Excel: the results have 1,048,575 rows and 15 columns (15,728,625 cells), which is more than the 4,100,000 cells an Excel file can be made from here, so "spec230-cell-limit.xlsx" was not written. Please save them as Parquet instead, or narrow the query."* notify-failure logged `reason=excel_cell_limit`, and no `.xlsx` was written. |
| **The same query saved as Parquet** | **PASS.** *"Saved 1,048,575 rows as Parquet to "spec230-cell-limit.parquet"."* `REPORT`: 2,152 ms, 521 MB, and 13,492 bytes written. |
| **The largest Excel conversion the cell cap admits** | **PASS on both bounds.** *"Saved 1,025,000 rows as Excel to "spec230-at-cap.xlsx"."* The download was 65,600,020 bytes, the fixture's figure to the byte. `REPORT`: **Duration 61,412 ms** against 120 s, and **Max Memory Used 2,410 MB** against the model's 2,518. The workbook is 28,374,149 bytes, listed as 27.1 MB. |
| **The Excel row limit** | **PASS.** *"Couldn't save the query results as Excel: the results have 1,100,000 rows, which is more than a spreadsheet can hold, so "spec230-row-limit.xlsx" was not written. Please save them as Parquet instead, or narrow the query."* — with the separators the day's sweep, below, found missing. The converter downloaded 4,400,004 bytes and refused in **305 ms at 159 MB**, on a second instance, because the at-cap conversion still held the first. No `.xlsx` was written. |

**The at-cap reading was above the band the spec predicted, and inside the model.** The spec
expected 2,150 to 2,250, from the local peak of 2,078 to 2,163 MiB plus the 65 to 84 MiB gap
measured at the 490,000 × 4 shape. Production read 2,410, which is 247 to 332 MiB over the local
peak: production's peak was 11 to 16% above the local one here, against 7 to 10% there. So the gap
is not a fixed runtime cost, and an offset measured on one input does not predict another. The two
readings differ in shape as well as size, so they cannot say which of the two moved it. The corpus
guard's own figure for this input — the baseline plus the local per-cell cost — is 2,284.8, which
is 125 MiB under the reading, so a green guard is not production headroom.

The model held because each of its terms is an envelope over all 23 shapes, set by shapes other
than this one. It charges this shape 580 bytes a cell (480, plus a quarter of the 400-byte row)
against the 520 measured locally, and its 250 MiB baseline sits above the fixed cost the
490,000-row run implied. If that fixed cost carries over, production spent 563 to 574 bytes a cell
here — 8 to 10% over local and only 1 to 3% under the model's 580 — and the baseline supplies the
rest of the 108 MiB margin. Two readings cannot separate the fixed cost from the per-cell one, so
that split is an inference, not a measurement. The 15% reserve below 3,008 MB is untouched. This
input is where the model peaks, so it is the reading that bears on the cap; how production scales
the other shapes' cost is unmeasured. `rccommon.config`'s baseline had described the gap as a fixed
cost and now does not, and what this means for a re-derivation is under Traps in
`lambdas/info/planes/results-conversion.md`. The time agreed with the spec: 61.4 s is 3.8
times the local 16 s, against the 4.0 measured at 490,000 × 4.

**Where this went.** `owed.md`'s two defects-table rows for the Excel cap and the missing separator
are closed. The SPEC-222 throughput row names this `REPORT` line as the reading that closes it, but
that row belongs to the session recording the throughput measurements, so it is left open for that
session, with the reading here. For whoever closes it: the at-cap conversion ran at 1.07 MB of CSV
a second, right at that row's "roughly 1 MB/s" trigger, but that is the byte-rate check SPEC-230
retired, and the per-cell time held at 61.4 s of 120. The `Runtime.OutOfMemory` row stays owed,
because the cap exists to make that case unreachable.

### Left behind — created by this session, not deleted

Permanently deleting data is left to Andrew: `agriffith/spec230-at-cap.xlsx` (27.1 MB) and
`agriffith/spec230-cell-limit.parquet` (13.2 KB). Neither refusal wrote anything.

---

## Live-check session — 2026-09-10 (every owed row one signed-in session and the read-only CLI could reach, archive excluded)

**Scope.** Andrew asked for every owed live check except the archive plane's, which he has
verified end to end. This session ran what a signed-in browser and a read-only CLI can reach and
recorded the rest with the reason it could not run. **Five defects were found and are listed at the
end**, with where each one went; none was fixed in this session.

**Browser and CLI.** `origin/main` at **`13bb7a30`**; the Lambda image in service stamped
`version: d9d8ce8e90c7…` on every record read today. Signed in as **agriffith** in Andrew's own
Chrome through the Claude-in-Chrome extension, at **1512 px** for most checks and at **900, 899, 768
and 700 px** for the width checks — the tab was foregrounded with `Control_Chrome`'s `switch_to_tab`
after every resize, per `e2e.md` §1's stale-viewport trap, and every width reading below was taken
foregrounded. CLI identity `arn:aws:iam::696000197480:user/tofu-deploy-user`, **reads only**:
`simulate-principal-policy`, admin-bucket `get-object`/`ls`, CloudWatch `filter-log-events`,
Step Functions history, SQS attributes, and `gh`. **No AWS write was issued from the CLI.** The
portal's own routes wrote plenty — see *Left behind*.

**Instruments, each a way this run differed from a user's.** `e2e.md` §1's `visibilityState`
override after every full load; a `fetch`/XHR recorder (method, path, status, part sizes,
`xhr.upload` progress, `ETag` readability); a capture of every `/v1/enqueue/*` request and response;
an in-page helper that calls the API with **the page's own bearer, read inside the page and never
returned**; `window.open`/anchor capture for download URLs, read back in-page; a
`securitypolicyviolation` listener; an in-page `.xlsx` reader (zip central directory plus
`DecompressionStream`), so no file was downloaded; a 100 ms progress-bar sampler; and **one
client-side fault injection**, stated where it was used. Andrew approved writing into
`another_shared_space` through the question tool. The harness's classifier refused two actions: a
bulk read of `shared-spaces/*.json`, which holds other users' membership, and corrupting
`query-history.json`.

### Sign-in and the deep link — a cold-cookie fresh sign-in, NOT a private window

A new tab arrived signed out (tokens are tab-scoped). Opening `/query?db=agriffith` bounced to the
landing page and stored `portal.returnPath = /query?db=agriffith`. **The Hosted UI cookie was cold,
so Sign in reached the password screen** — unlike 2026-08-31. Cognito's `/login` rendered with
`redirect_uri=https://portal.dataquarry.app` and no `redirect_mismatch`, which is the narrowed
callback list accepting the container origin. Andrew clicked Sign in on the autofilled form; the
page made **one** `fetch` to the Hosted UI's `oauth2/` endpoint (**200**) and landed on
**`/query?db=agriffith`**, with `portal.returnPath` consumed. Console capture started after that
load, so this run says nothing about CSP reports during sign-in. **What a private window adds is a
cold HTTP cache and empty storage, and that part stays owed.**

### Presigned bytes against the narrowed bucket CORS — both buckets, Chromium

- **User space.** Uploading `cors_check_20260910.csv` (1,788,890 B) through the drawer's own
  `<input type=file>`: `POST /v1/objects/upload` 200, then an XHR `PUT` to
  `dat-prod-user-space.s3.us-east-1.amazonaws.com` **200** with the **`ETag` header readable
  cross-origin**, progress `[55, 100]`, no CSP violation. Download: `POST /v1/objects/download-url`
  200 gave a SigV4 URL (`X-Amz-Algorithm` present), and an in-page `fetch` of it returned
  `type: "cors"`, **200, 1,788,890 bytes, 60,000 lines**, first and last lines matching the upload.
- **Shared space**, after Andrew's go-ahead: the same pair against `another_shared_space` on
  `dat-prod-shared-space`, **200** and ETag readable on the `PUT`; the read-back was the same
  1,788,890 bytes.
- The drawer states **"Up to 5 GB per file"**, so the `>5 GiB` metadata row cannot be staged by a
  browser upload at all.

### Per-user isolation through the API — SPEC-197 FR-014, re-confirmed

`GET /v1/objects` on the caller's own personal space returned **200** (23 items). Another real
user's personal space and a nonexistent user's both returned **403 `AccessDenied`** with the same
detail, *"personal space is not the caller's"*, so the refusal is no existence oracle. A nonexistent
shared space returned **403**, *"no membership for that space"*, which the route raises before any
S3 call.

### Results conversion — SPEC-221, -222 and -223

**Fixture.** `docs/testing/fixtures/explorer-fixture-150.csv` was uploaded to `agriffith/explorer150/`
and built into table `agriffith.explorer150` (`table-build` 200, "Table "explorer150" is ready to
query in "agriffith".").

- **The dialog.** It offers Format `CSV`, `Parquet`, `JSON`, `Excel` in that order with CSV as the
  default, the button reads **Save here** for CSV and **Convert and save** otherwise, and Save to
  lists My files plus nine spaces. **The Data Explorer's dialog is identical** in title, intro,
  labels, options, default name pattern and buttons, whether opened from Options or from the button
  under the grid.
- **The front door.** `GET /v1/objects/exists` 200 is followed by `POST /v1/enqueue/results-conversion`
  **200**, which echoes the request id. The body carries a root-relative `prefix`, `onConflict:
  refuse`, and no actor or identity. The dialog closes and the toast reads *"Converting to Parquet —
  you’ll get a notification when explorer150_conv.parquet is ready."* (curly apostrophe). CSV
  instead goes through `POST /v1/objects/copy` from `system_settings/athenaresults/<exec>.csv`, with
  no enqueue; its toast is *"Saved to agriffith/conv0910_other/explorer150_conv.csv"* plus a *View
  in Files* link.
- **One notification per conversion**, reading *"Saved 150 rows as Parquet to
  "explorer150_conv.parquet"."* and the same for JSON and Excel. The message itself is the link.
  Following the Parquet one landed on `/files?prefix=agriffith/conv0910_parquet/` with the file
  **already listed**, after one fresh listing call.
- **Read back.** Tables built over the Parquet and JSON folders both return **`count(*)` = 150**,
  with 9 `O'Brien` rows in the Parquet one. The JSON is **150 lines, each of which parses on its
  own**, and it is not an array. The `.xlsx` parsed in-page to **151 rows, `A1:D151`**, 0 formula
  cells, every cell a shared string. The Explorer's three conversions reported 150 rows too, not the
  page's 100, and started **zero** queries; its `.xlsx` likewise had 151 rows. Its CSV save went
  through `POST /v1/objects/copy` from its own execution's result file, with the same *Saved to …*
  toast and zero query starts. The `.xlsx` files were read by that in-page parser, not opened in a
  spreadsheet application, which can refuse what a zip reader accepts.
- **Formula probe**, which is the discriminating one. The values `'=1+1'`, `'+2'`, `'-3'`,
  `'@SUM(1)'`, `'=HYPERLINK(…)'`, a leading tab and a leading CR were converted to `.xlsx`. The
  workbook has **0 `<f>` elements** and every value is a string cell; the CR is stored as
  `_x000D_`.
- **Shared-space destination**, the highest-value row. A Parquet save into
  `another_shared_space/reports0910/` sent `prefix: "reports0910/"` and landed at
  `another_shared_space/reports0910/explorer150_shared.parquet`. The space root lists only
  `reports0910/` and the CORS fixture, so **no doubled folder exists**. The notification link begins
  `?space=another_shared_space&prefix=…` and lands in that space with the file listed.
- **Overwrite confirm.** A second Parquet save to the same name raised *"Overwrite
  “explorer150_conv.parquet”? — A file named “explorer150_conv.parquet” already exists in that
  folder. Saving will replace it."* after the exists pre-flight, with **zero** enqueues. Confirming
  sent exactly one enqueue with `onConflict: "overwrite"` (200). **Cancel returns to a dialog that
  has reset to its defaults**: name `query-results-…`, CSV, and the My Files root. That is
  `useSaveResults.cancelOverwrite`'s `setOpen(true)` remounting the dialog, which holds that state.
- **`destination_occupied` as a real race**, sent through the API so the browser's pre-flight was
  skipped. `validate-authorize` validated the request, `describe-results` ran, and `convert` logged
  *"downloading 4185 byte(s)"* and then **"refused destination_occupied"**. So the refusal came from
  the conditional write, not from an up-front check. The inbox read *"…a file called
  "explorer150_conv.parquet" is already in that folder, so nothing was saved. Please choose another
  name, or save again and choose to replace it."* and the object's `lastModified` stayed at
  19:10:18Z. The `overwrite` twin converted and moved it to **19:30:19Z**.
- **`validate-authorize`'s five refusals against real Athena.** Each got a 200 at the door and
  **one** notification in the actor's inbox:
  - `forbidden` (destination: another user's personal space) → *"You don't have access to save
    results there."*
  - `protected_location` (`system_settings/athenaresults/`)
  - `execution_not_found` (a made-up id)
  - `execution_not_finished` (a real one-billion-row count, *"execution is RUNNING"*)
  - `no_result_set` (`SHOW TABLES`, *"statement type is 'UTILITY'"*)
- **The existence-oracle half, via the operator's workgroup list.** The ledger names this as a
  valid vehicle. A SUCCEEDED execution whose results sit under **another user's** prefix got
  `execution_not_found` (*"the execution's output is not under the actor's results"*).
  `describe-results` and `convert` were never invoked. The user-facing sentence is
  **byte-identical** to the made-up id's.
- **Decimal `Precision`/`Scale`.** The portal's results route types all four columns of
  `CAST(… AS DECIMAL(10,3))`, `DECIMAL(5,1)`, `DECIMAL(38,2)` and `DECIMAL(4,0)` as bare `decimal`.
  The Parquet conversion succeeded, which `athena_type_of` would refuse without a precision, and a
  table built over the file reads **`decimal(10,3)`, `decimal(5,1)`, `decimal(38,2)`, `decimal(4,0)`**
  exactly. The first three prove the scale was populated; `decimal(4,0)` alone could not, because
  the function reads a missing scale as 0.
- **The Excel row limit, with no fixture.** `UNNEST(sequence(1,1049)) CROSS JOIN
  UNNEST(sequence(1,1000))` generates 1,049,000 rows while scanning 0 bytes. Its `.xlsx` refusal
  read *"Couldn't save the query results as Excel: the results have 1049000 rows, which is more than
  a spreadsheet can hold, so "rowlimit_1049k.xlsx" was not written. Please save them as Parquet
  instead, or narrow the query."*, and the same result saved as Parquet (*"Saved 1,049,000 rows…"*),
  so the suggestion is honest. **The refusal prints the count without a thousands separator; the
  success message prints it with one.**
- **Converter throughput on amd64.** A 490,000 × 4 result took 19,566 ms with a peak of 933 MB. The
  input was 16,119,678 B, computed on the same model that later matched `describe-results` exactly
  at 62,914,590 B. That is about **0.82 MB/s**. For memory, the function's earlier high-water mark
  was 147 MB, so the conversion added about 786 MB: **~49 bytes of peak memory per CSV byte with that
  baseline subtracted, and 57.9 without it**, against the 32.45 that `EXCEL_MEMORY_EXPANSION`
  assumes. Both read Lambda's MB as 10⁶ bytes; if it means MiB, each is about 5% higher. 0.82 MB/s is below the ledger's own "roughly 1 MB/s" trigger for bringing the cap down,
  but timing on its own is safe: 600 s leaves 540 s usable, and 64 MiB would take about 82 s.
  **Memory is not — see the first defect.** Earlier small conversions: Parquet cold 4,764 ms (init
  1,235 ms), JSON 199 ms, `.xlsx` 908 ms and 191 ms.

### Feedback — SPEC-211's CLI half, all six rows

**The ledger's blocker was false.** The laptop identity reads `dat-prod-athena-admin`, which
`sessions.md` already recorded on 2026-08-15.
- `feedback/2026/09/01.json` has keys `{date, entries, version}` with `version: 1`, and holds **3
  entries in one object**, in `submittedAt` order: 20:21:12, 20:22:16, 20:22:52. Each has `username:
  agriffith`, which came from the token because the browser sent none.
- The writer's records show `entries` going 1 → 2 → 3 on the same key.
- The API's span carries `message_group_id: "2026-09-01"` and the writer's key is
  `feedback/2026/09/01.json`: two languages, one date.
- The writer records carry `message_chars` 97, 98 and 120, and **no message text**. A grep for
  `live check` finds 0 hits in both day-01 logs and 3 in the object itself, as a positive control.
- `POST /v1/feedback` with 4,001 characters → **400 `InvalidRequest`**, *"the feedback message is
  4001 characters, over the 4000-character limit"*. `feedback/2026/09/10.json` already existed at
  19:00:17Z, written by someone else, and the refused probe did not touch it.
- The feedback DLQ reads 0/0/0 with 14-day retention, so the zero covers 09-01.

### The enqueue paths — SPEC-200 §G.1–§G.4

- **§G.1.** Row 2: a UI mark-read sent `markRead` (200), and the row stayed read after a full page
  load. Row 3: tables appeared in the rail. Row 4: a UI refresh produced *"Table "explorer150" is
  already up to date - no schema changes were found."* Row 5: `another_shared_space`'s catalog
  gained `explorer150_g2`. Row 6: the data-quality notification's link opened the report
  (`agriffith/explorer150`, 150 rows, *No issues found*). Row 7: a UI send landed at
  `another_shared_space/shared_files/agriffith/cors_check_20260910.csv`. Row 10: folder copies
  landed (below). **Row 1, creating a shared space, was not run**: Andrew chose not to create a
  throwaway space.
- **§G.2.** Sending the same `requestId` twice produced **one** execution on results-conversion and
  on file-ops, with the SQS dedup id equal to the body's id.
  - **Table-share, which has no request id, across a genuine token refresh.** Submit 1 went at
    20:55:02.002Z on the old token, which expired at 20:55:10. A Files refresh gesture made Amplify
    issue a new token at 20:55:14. Submit 2 went at 20:55:25.071Z on the new token. Both fell in
    epoch-minute bucket 29817895, and **one** execution resulted.
  - A first attempt 2.7 minutes apart produced two executions. That is designed:
    `fifo._dedup_table_share` hashes a clock-aligned 60-second bucket, so a genuine double-submit
    that straddles a minute boundary also becomes two.
- **§G.3.** The first `span.end` per route in `logs/service=api/` covers `sharedSpace`,
  `dataQuality`, `fileSend` and `notifications` on day 10 and `fileOps` on day 08. Each carries
  `route_id`, `queue`, `actor`, `message_group_id`, `body_request_id`, `dedup_id`, `body_bytes`, and
  `env`/`version` at the top level. `body_request_id` is `null` on `notifications` by design, because
  that body has no id. None contains a JWT shape, an email, any of the six presigned-URL tokens, a
  path-like value or a recipient field. **Later the same evening**, once the sweep had caught up to
  19:24Z, the same reading of the day-10 partition covered `tableBuild.create` (all 3 records, queue
  `table-builder`) and `resultsConversion.enqueue` (all 8 accepted records up to then), with the same fields and the same
  absences. **Table-share is pending**: its records, from 19:52Z on, were still behind the sweep.
- **§G.4.** No `Authorization` → **401 `SessionExpired`**. A body with `actor`, `identity` and
  `idToken` → **400 `InvalidRequest`**. A 4,000-item, 380,302-byte file-ops body → **413
  `PayloadTooLarge`**, *"the request is too large to enqueue"*, which is the whole-message bound.
  **Zero sends**: no results-conversion or file-ops execution carries any of those three body ids,
  and the same listing over a wider window returns the six executions known to be in it, as a
  positive control. The Pipes start one execution per message, so zero executions means zero sends.

### File operations and file-send — SPEC-165, -187, -188, -189, -191

`fixtures/file-ops-plane.sh` cannot run as written: it reads the token from `localStorage` and uses
`aws sqs send-message`. Every body below went through a signed-in `POST /v1/enqueue/{plane}`
instead.
- **Fixture.** `agriffith/fileops_big0910/` holds **1,200** one-line files, handed to the portal's own
  file input as in-page `File` objects. That made 1,200 `PUT`s, all 200, in about 2 minutes 55
  seconds, and the API lists 1,200 over 49 pages.
- **SPEC-165, with zero writes.** A file-send of the folder to a nonexistent space gave
  **`InspectSource` `objectCount` 1200** and `totalBytes` 4,893, the exact byte sum. The copy plan
  holds 1,200 unique keys and no marker. The unknown-space refusal alone came back `SUCCEEDED`, with
  the recipient annotated **`invalid: "unknown_space"`** and no `AccessDenied` traceback.
- **SPEC-188.** Copying the folder produced a `plan.json` with **`objectCount` 1201**: 1,200 files
  plus the zero-byte folder object, which is what the prefix really holds. It lists 1,201 unique
  `srcKey`s, and `transfer-results` reports `failed: 0`.
- **SPEC-187 FR-009.** The large copy (A) and a one-file copy (B) were sent in one `Promise.all` and
  started 127 ms apart. A held the lock from 16:03:17 to 16:03:56 local and moved 1,201 objects in a
  17-second Map run. B's history reads **`WaitForLock → AcquireLock` twice**, it operated only
  after A released, and both executions `SUCCEEDED`. `acquire-lock` logged *"holding 1 space lock(s) after 1 attempt(s)"* for A and
  *"after 3 attempt(s)"* for B, with no steal.
- **SPEC-189, the source modified between copy and delete.** An in-page loop polled the
  *destination* `f0001.txt` until it existed (T0+15.4 s), then overwrote the *source* `f0001.txt`
  through the no-lock upload route (T0+15.7 s). The item ended **`duplicate` / `source_changed`**.
  The source kept only `f0001.txt`, with the new bytes; the destination holds all 1,200 files with
  the old `"1\n"`; and the other 1,199 source objects were deleted.
- **A clean move of more than 1,000 objects** ended `moved`, with 1,201 handled and 0 failed. The
  source and its parent are empty, and 151 Map batches all `SUCCEEDED`, covering 1,201 items, equal
  to the manifest.
- **SPEC-187 §3–5.** §3, another user's source: `forbidden`, execution `FAILED`, and **one**
  notification in the **actor's** inbox, *"You don't have access to delete those files."* §4, four
  protected folders plus one ordinary folder in a single delete: each protected folder refused **per
  item** (`source_folder_undeletable` ×3, `settings_folder_not_a_source`), the ordinary one deleted,
  and the run `SUCCEEDED`. §5, a delete of the whole space: aimed at `another_shared_space/`, not
  the personal root, so a broken guard would have cost only test files; it was refused
  `space_root_not_an_item` with *"a whole space can't be worked on in one go"*.
- **SPEC-187 §8 and §8b.** A cross-space copy logged *"holding 2 space lock(s)"*. The shared lock
  sorts first (`114a…` before `c781…`). A background CLI loop read both lock objects about once a
  second while a large copy held the personal lock. During that 30-second wait **the shared lock was
  free in every sample**, then both were held by the waiter at 20:17:54, and both were free at
  20:17:57. The `acquire-lock` log settles what a once-a-second sampler cannot: at 20:17:23 the
  waiter (`e8a06e3c`) logged *space lock acquired* for the shared space, *space lock refused* for
  the personal one and **_space lock released_ for the shared one** within 66 ms. The earlier
  cross-space copy (`c4ed47d8`), blocked by three short personal-space requests, did the same on
  three attempts. The *released* record is written only after the conditional release succeeds, so
  the first lock was taken and let go, not merely never taken. (The `released_partial: 1` beside it
  counts locks held, and would read 1 with the release removed, so it is not the proof.)
  - **The script's §8b recipe is vacuous for this pair.** It wedges the shared lock, but that lock
    sorts first, so a request that loses it holds nothing and the personal lock reads free whatever
    the code does. The recipe now says to wedge the lock that sorts second.
- **SPEC-191, notifications, from `notifications.json`.**
  - **One notification per request**, e.g. *"Moved 1 item to "fileops_clean0910"."* and *"Copied 1
    item to …"*, linking to the destination. The payload carries `requestId`, `operation`, `source`
    and `destination`.
  - The partial copy: *"Copied 1 of 2 items to "conv0910_json". 1 needs your attention:
    "explorer150_conv.csv" - something is already in the way there. … Sending it again with
    overwrite turned on replaces what is there, and that cannot be undone."* Its payload includes
    `conflicts`.
  - The capped message: *"Deleted 1 of 5 items. 4 need your attention: … And 1 other not listed
    here."*
  - The delete links to its parent, `?prefix=agriffith/`.
  - **`?space=` comes first** on a shared destination, and clicking it lands in that space.
  - A folder named **`q?a&b=c#0910`** gets a link with `%3F`, `%26`, `%3D` and `%23`, and clicking
    it lands in exactly that folder.
  - **§22 fails**: both whole-request refusals carry **`payload: null`**. See the second defect.
- **§13 cannot be staged through the portal.** Uploading a nested `DO_NOT_DELETE.txt` gets **403**,
  *"folder markers may not be removed or replaced"*, and a copy of `saved_queries/` planned only
  `arcb.sql`, because copies skip markers.

### Table builder and data quality — SPEC-157, SPEC-108

- **SPEC-157.** Two `table-refresh` POSTs were sent in one `Promise.all`. A took the lock at 04.124,
  released it at 05.854 and `SUCCEEDED`. B was refused 44 ms behind: *"refresh_already_running: a refresh of
  table 'explorer150' in database 'agriffith' is already running"*. B's no-etag release was a no-op,
  and A's compare-and-swap release logged no lost-CAS warning.
- **SPEC-108.** The 150-row check looped only once, so it proved nothing. A check on
  `agriffith/dq_big0910.csv` (10,000,000 rows, about 1 GB) did the job: `StartProfileQuery` was
  followed by **`WaitForQuery CheckQuery` three times**, then `ByteScan AssembleReport
  DropTempTables`, and the run `SUCCEEDED`.
- **The data-quality cap, observed live.** A check on the 1,200-file folder was refused with
  **`too_many_files: 1200 objects exceeds DQ_MAX_OBJECTS=1000`**.

### IAM simulations — the deployed roles, one resource per call

- **The file-ops execution role**, identically on both buckets:
  - denied (`explicitDeny`): deleting under `system_settings/athenaresults/`, deleting a nested
    `DO_NOT_DELETE.txt`, putting under `user_settings/`, and putting under `system_settings/archive/`;
  - allowed: the ordinary controls.
  - **The script's `{root}athenaresults/` deny row is stale**. That path is an ordinary folder since
    SPEC-220's narrowing, so `allowed` is correct.
- **Cross-user isolation on the portal role, as `alice`.** Put, delete and get on `bob/` are
  `implicitDeny`, and on `alice/` are `allowed`. List is `allowed` only for `alice/`; `bob/`, `bo`,
  no prefix and an empty prefix are all `implicitDeny`.
- **The API role's membership-index grant.** `memberships/*` get and list are `allowed`, with
  `s3:prefix` supplied as context. `feedback/` and a prefix-less list are `implicitDeny`.
- **The shared-space catalog, IAM half.** With the `marketing` slot tag: `GetDatabase` and
  `GetTables` on `marketing` are `allowed` and on `finance` `implicitDeny`. `DeleteDatabase` and
  `UpdateDatabase` are `implicitDeny` on both `marketing` and `alice`. `DeleteTable` on
  `marketing/t1` is `allowed` and on `finance/t1` `implicitDeny`.
- **The notifications queue.** The portal role gets `implicitDeny`, against an `allowed` control on
  its own prefix; the API role gets `allowed`. The API route refuses `{action: "create"}` with
  **400** and accepts a `markRead` control with **200**.

### Observability

- **The error-size reservation.** Every real `Cause` from today's nine failed results-conversion
  executions is **ASCII**. The `TerminalError` causes run 749–926 characters and JSON-escape at a
  ratio of **1.070–1.075**; the timeout's cause is 140 characters at **1.071**. The fleet reserves
  **2.0**.
- **The Pipes record model.** Real records carry **`AWSTraceHeader`** (95 characters:
  `Root;Parent;Sampled;Lineage`), which `test_request_size_chain.py::_record` omits. Real
  `eventSourceARN` runs to 76 characters, where the model allows 57. The model's over-sized other
  fields still net out above today's records.
- All 56 of today's results-conversion records carry `env: prod` and a real `version`.
- **Cold starts on real messages**: `convert` (init 1,076 ms), `notify-failure` ×5 (635–780 ms) and
  `describe-results` (899 ms) all imported and ran.
- **The CORS preflight.** The portal's origin gets exactly one `access-control-allow-origin`, methods
  without `HEAD`, and no credentials header. A foreign origin gets 200 with **no**
  `access-control-allow-origin`.
- **ZAP against the container origin**, from the scheduled Security run 34121971677 on 2026-09-07:
  FAIL-NEW 0, WARN-NEW 9, PASS 61. Every warning's alert ID matches a disposition in
  `security-baseline.md` — among them 10055 (CSP `style-src 'unsafe-inline'`) and 90004 (COEP),
  both accepted by decision — and 10036 (`Server` version) passes. 10050 and the Sec-Fetch
  Mode/Site/User variants have cleared.
- **The log sweep is saturated.** Every run since at least 19:35Z *"stopped on wave-cap; 1102–1627
  message(s) over 50 wave(s), the queue may still be yielding"*. `dat-prod-logs.fifo` held 17,134
  messages at 20:43Z. `logs/service=api/` was written at 20:35Z but covers only up to **18:46Z**.
  Retention is 14 days, so nothing is lost, and nothing alarms. The sweep runs every 10 minutes, so
  that is a drain ceiling of 6,612–9,762 messages an hour.

### Width and target geometry — the live app, Chromium

- **The save-results dialog across the band.** At 900 px and at 1512 px the three fields are equal
  widths and stacked, and the button is **31.5 px** tall for both labels. At 899 and 768 px the
  dialog was opened from the Explorer, because below 900 px the Query page shows only Saved and
  History; it is stacked there too, at 31.5 px, with no page overflow. **375 px was not run.**
- **The top bar overflows** from 900 px up to about 960 px of `innerWidth`, the scrollbar taking 15
  px of each. At 900 px the page is 945 px wide in an 885
  px viewport, and the header in a 925 px viewport at 940 px; it clears at 960 px. The account
  button's username label turns on at the `tablet:` breakpoint and nothing shrinks, so longer
  usernames widen the band.
- **The undersized-target register.**
  - **`StripingControl`** (the Colours dialog's *Band rows by*): with 20 columns its 13×13 boxes wrap
    into four rows at **19.5 px**, so **it fails (−4.5 px)**, like CalcPanel. With 4 columns it sits on one row with
    +18.51 px slack.
  - `AdvancedCopyDialog` (opened, so the positive control held): three 13×13 boxes 25 px apart, **+1
    px**, exempt by one pixel.
  - `TableShareDialog`: radios at +30.75 px, exempt.
  - `RefreshTableDialog`: a 14×14 checkbox at +175.74 px, exempt.
  - `FileListRowMobile` at 700 px: 14×14 row checkboxes at a 49 px pitch, worst slack +7.25 px,
    exempt. Two apparent failures were rows **behind** the
    fixed mobile action bar, which a hit-test confirmed; scrolled to the end, the last row is
    reachable.
  - **A wrapped breadcrumb** (seven levels at 700 px): two lines at 27.5 px, every crumb 24 px tall,
    long crumbs capped at 160 px. It conforms.
  - The Explorer's tab strip, with two tabs open: each close ✕ is exactly 24×24, 111.6 px apart,
    and the tabs are 24.5 px tall with a 3.5 px gap. `QueryTabStrip` was not measured.

### Uploads and the in-progress surface — SPEC-216, SPEC-190

- **Multipart.** The part size is **112,500,000 B**, which is also the threshold. A 240,000,000-byte
  file was uploaded in 3 parts:
  - Each part was **minted just before its own `PUT`**, never all up front.
  - Every successful part had a readable `ETag`, and one `COMPLETE` returned 200.
  - **Fault injection**, client-side: part 2's first `PUT` was stopped at 25.2% and the app's own
    `'error'` listeners fired. An abort alone would have taken the cancel path. The part was
    **re-minted and re-sent once**, 112,500,000 B, not the whole file.
  - The **aggregate bar** was sampled 223 times: 100 distinct values from 0 to 100 and **zero
    decreases**.
  - The object is 240,000,000 B, uploaded in about 17 s. At about 14 MB/s the 5 GB cap takes roughly
    6 minutes, so **"past the 900 s window" cannot be reached on this uplink**.
- **SPEC-190, a UI folder move.**
  - **One** API call and zero AWS calls, the card *"Moving fileops_holdlock0910 · Started just now ·
    Running in the background…"*, and the listing unchanged.
  - While it ran, a **folder** selection disabled Copy, Move, Delete and Archive with *"Another file
    operation is still running here…"*. A single-**file** selection disabled only Archive, because a
    single file's copy, move and delete take the synchronous no-lock path.
  - The card settled to *"Finished — see your notifications…"*.
  - **The card does not survive navigation.** See the fifth defect.

### Defects found — each is tracked in `owed.md`'s defects table until its re-run passes

1. **The Excel cap admits inputs the converter cannot finish.** A 60 MiB result of 1,048,575 rows ×
   15 one-character columns passed both the size cap and the row limit. `convert` ran **600,000 ms,
   `Max Memory Used: 3008 MB`, `Status: timeout`**, and the user got *"Couldn't save the query
   results as Excel: something went wrong."* ten minutes later.
2. **File-ops refusals at validation carried no `requestId`.** `validate-authorize`'s failure
   handler built its notification event by hand, as `{actor, operation}`, and left the request id
   out, so both whole-request refusals (`forbidden` and `space_root_not_an_item`) arrived with
   `payload: null`. The emitter's own test handed it an event that had the id, so it could not see
   what its caller omitted. Results-conversion had the complementary gap: `destination_occupied`
   and the timeout arrived with no payload at all. **Both were fixed the same day in #716**; the
   live re-run of script §22 is owed once that deploys.
3. **The Query workspace's row-count walk is unbounded.** The code assumes *"GetQueryResults calls
   are free"*, but each page is now a billed API call. A 10-million-row result walked at about 1.6
   calls a second, which would be roughly 10,000 calls; it stopped at 124 when the page was left.
4. **A top-bar overflow band from 900 px up to about 960 px** (`innerWidth`), widening with
   username length.
5. **Navigation remounts the signed-in shell.** `RootLayout`'s `<ErrorBoundary key={pathname}>`
   remounts everything beneath it on every route change. The shell's wrapper node is new after a
   route change, and both providers reset.
   - **Leaving Files aborts uploads in progress.** Two part `PUT`s at 13% and 37% were aborted
     126 ms after a Query click, with the drawer already closed; Escape alone was shown not to
     abort. `POST /v1/objects/upload/abort` returned 200, which is SPEC-216 FR-004's navigation
     variant.
   - **The in-progress card and the space's submit gate are lost.**

Smaller, and in the same table: the save dialog resets when an overwrite is cancelled; the
row-limit count has no thousands separator; a relative listing prefix equal to the space name reads
as the root, because `protected.contained_prefix` treats any prefix starting with the root as
absolute; and the log sweep is saturated (see *Observability*). The Pipes record model's gap is
tracked in its own `owed.md` row.

### Not run, and why

- **Excluded by Andrew's scope: every archive and restore row**, including SPEC-168's `PutObject`
  into one's own `archive/` prefix, which a read-only simulation could have reached.
- **Needs Andrew's hands.** The private-window sign-in; 375 and 400 px, which need the device
  toolbar; the no-flash theme check, which needs a foreground tab; and a real token with a flipped
  bit.
- **Needs a second account.** Every row in that section.
- **Needs a shared space created or deleted.** SPEC-205 FR-004/006, SPEC-053/054, SPEC-061, the
  catalog-unsafe name, and §G.1 row 1. Andrew chose to use the existing space instead.
- **The classifier refused.** Corrupting `query-history.json` (SPEC-159).
- **Production writes, which need CI or an operator.** Every row in that group.
- **Pending the log-sweep lag.** §G.3's table-share record.

### Left behind — created by this session, not deleted

Permanently deleting data is left to Andrew. Keep `agriffith/explorer150/`, the table
`agriffith.explorer150` and `agriffith/fileops_big0910/` as reusable fixtures. Delete these:
- **In `agriffith/`:** `cors_check_20260910.csv`, `conv0910_parquet/`, `conv0910_json/`,
  `conv0910_other/` (which includes `fileops_holdlock0910/`), `fileops_clean0910/`,
  `fileops_moved0910/`, `marked0910/`, `decimal0910/`, `q?a&b=c#0910/`, `mp_240MB_0910.bin`,
  `navprobe_0910b.bin`, `dq_big0910.csv` (about 1 GB), and the `sub0910/level_…` chain inside the
  long `aaaa…` folder.
- **Tables and views:** `agriffith.conv0910_parquet`, `agriffith.conv0910_json`,
  `agriffith.decimal0910`, and the view `agriffith.wide0910`.
- **In `another_shared_space`:** `cors_check_20260910.csv`, `reports0910/`,
  `shared_files/agriffith/`, and the tables `explorer150_g2` and `explorer150_g2b`.

The checks' own moves and deletes touched only copies this session had made.

---

## Live-check session — 2026-09-09, second sitting (SPEC-227 FR-002 half (b), and §4.11's read-only rows at both widths)

**Browser and CLI.** `main` at **`d49ba809`**, green — `Deploy SPA image` and `Deploy Lambda image`
on that commit, `Deploy Infrastructure` and `Deploy Lambdas` last run and green on `a1fd6264`
beneath it. Signed in as **agriffith** in Andrew's own Chrome through the Claude-in-Chrome
extension, at **1512x788** and again at **606x732**. CLI identity
`arn:aws:iam::696000197480:user/tofu-deploy-user`, reads only — **this session issued no AWS write
of its own.** (The control-plane run it drove wrote objects of its own; see *Left behind* at the
end, which is the honest version of that sentence.)

**The one API call below was issued with `fetch` from the signed-in page's own JS context**, using
the session's own bearer token; the token was never read out of the browser. Everything else is a
read: Step Functions history, two of the admin bucket's log objects, and the portal's own UI.

### SPEC-227 FR-002 half (b) — the negative, and the recorded limit is REAL

**The row said this half needed a hand-crafted envelope onto the archive queue, and it does not.**
The row reasoned that the portal cannot produce an unregistered space because the UI offers none —
true of the UI, and not true of the API beneath it. `lambdas/api/routes/enqueue.py` reads no
membership by design ("every authorization question belongs to the plane's own validate-authorize
verb"), the route contract types `space.kind` as a literal and `space.name` as a free string, and
the FIFO group id is derived from the body rather than resolved. So a signed-in `POST
/v1/enqueue/archive` naming a space that does not exist reaches the plane intact — **no assumed
role, no `sqs:SendMessage`, and no queue write at all**, which is what made this runnable from a
session whose production AWS writes the harness refuses.

**No object under `s3://dat-prod-athena-admin/shared-spaces/` is named `spec227_no_such_space`** —
that absence is the load-bearing fact and it keeps; the registry's population is not quoted, because
it grows every time anyone creates a space. The POST answered **200** with `{"requestId":
"579de943-7bba-4606-ac93-d1c33eceb346"}`; execution
**`301a88ae-8d9c-5d28-ad49-ebb505467882`** ran 12:17:34.148 to 12:17:37.291 EDT and **FAILED**.

**The envelope is the trap's opposite, and that is the whole point of the run.** Its body carries
exactly five top-level keys — `identity`, `mode`, `requestId`, `source`, `traceparent` — with
`identity` a nested block (`actor: agriffith`, `delegated_by: null`, `assurance: interactive`) and
**no token anywhere**. So this is not the no-identity-block envelope the row warns about, which
would have produced the same SHAPE while proving nothing.

**Check the reason, not the shape — and the reason the row names does not exist on this plane.** The
refusal is `TerminalError` / **`forbidden: 'agriffith' is not a member of 'spec227_no_such_space'`**,
raised by `arcommon.authz.authorize_source`. It is **not** `unauthorized`, which is what the
no-identity-block envelope would have given. It is also not `unknown_space`: **archive has no such
code**, deliberately — `arcommon/messages.py` records that a shared space that does not exist fails
as `forbidden` precisely so that "no such space" and "you are not a member" stay indistinguishable,
because the difference is an existence oracle over other people's spaces. The discriminator this
half actually turns on is therefore **`unauthorized` versus `forbidden`**, and the owed row saying
`unknown_space` was wrong about this plane.

The execution took the pre-identity catch: `ValidateAuthorize` → **`ValidateFailureSeed`** →
`RecordFailure` → `NotifyFailure` → `Failed` (`ArchiveFailed`). Both Pass states' real output was
read back: `traceparent: null`, `requestId: null`, `mode: null`, `actor: null`, with `raw` holding
the forwarded SQS batch. That is the mechanism, observed rather than inferred.

**The two traces.** Read from the day's log objects, and **the sweep is per SERVICE, so a count is
meaningless until the partitions it spans are named** — a first draft of this paragraph said "two
records" of a trace that has four:

| Partition | Span | trace_id | span_id | parent_span_id | request id |
|---|---|---|---|---|---|
| `service=api` | `request` (2 records) | `336d82e07059767422be1e24311389f3` | `8f52805494b02b63` | **null** — it is the root | `fields.body_request_id` is the run's; `fields.request_id` is the gateway's `DcH4vjxOoAMEP6g=` |
| `service=archive` | `validate-authorize` (`span.start` INFO, `span.end` ERROR) | same | `de08ab514e4a6ab5` | `8f52805494b02b63` | `fields.request_id` is the run's |
| `service=archive` | `notify-failure` (3 records) | `8a06aa9a8fb26ed08c24770137c9a8ef` | `1fde01515da25e83` | **null** | **no request id in any field** |

So the run's trace is **four** records over two partitions and `notify-failure`'s is **three** in one,
and nothing joins them. Those are per-run figures on runs that have ended, so they hold; the DAY
objects they were read out of keep growing and no count of those is quoted here.

**The propagation is visible end to end, which is more than the row asked for.** The API's own span
`8f52805494b02b63` is the trace's root, it is the span id inside the envelope's `traceparent`, and it
is `validate-authorize`'s `parent_span_id`. `notify-failure` is on a different trace with a null
parent. **Say "the run's request id" carefully:** only the archive records carry it in
`fields.request_id`; the API's two carry it as `body_request_id` and reserve `request_id` for the
gateway's own.

**So the limit SPEC-227 recorded is real, and half (b) confirms it rather than falsifying it.**
*(Superseded by SPEC-228: the measurements in this entry stand as what the fleet did on 2026-09-09,
and they are what the repair was derived from — but the limit itself is closed. `RecordFailure` now
carries the forwarded envelope from `$$.Execution.Input`, so this failure joins the run's trace and
recovers the caller's request id. The ASL half of the reasoning — that the value is reachable
nowhere an intrinsic may look — still stands.)*

**The failure correlates on nothing at all — measured, and the register disagrees.** Those three
`notify-failure` records carry no `request_id` field, so the fallback join is not available either.
The mechanism: the seed supplies `requestId: null`, and on the ASL door `ar_notify_failure` recovers
only the **actor** out of `raw` — never a request id, and **not the mode either**, which it reads off
the state where the seed put null (`_mode_from_raw_request` exists but is reached only from the
EventBridge `TIMED_OUT` door, which never passes through this seed). **A draft of this paragraph went
on to derive a consequence and got it wrong** — that a pre-identity restore failure is therefore
worded as an archive. It is not, for a REFUSAL: `notify-failure` suppresses a `TerminalError` and
words nothing, and the sentence the user reads comes from `validate-authorize`'s own `emit_failure`,
which seeds its mode from the untrusted body precisely so a refusal is worded as the operation the
user asked for. The measured fact is the one above and stops there.
Corroborated on the ASL side, which is a source
read rather than a second measurement: seven of the eight planes' `ValidateFailureSeed` supply
`requestId: null` and `table-share` supplies none at all. **SPEC-228 FR-001 already says this**
("today a pre-identity failure correlates on nothing at all — neither a trace nor the join key"), so
the finding here is the production confirmation and the fact that
`docs/decisions/control-planes.md` still claimed `fields.request_id` stays as the join key. That
clause is corrected in this PR; the spec was right and the register was stale.

**The user was told, and the suppression is correct rather than a lost notification.** The newest
entry in agriffith's inbox reads *"You don't have access to archive those files."* — no link, no
archive id, and no hint that the space does not exist. It was written by `validate-authorize`
itself: its `except TerminalError` calls `notify.emit_failure` before re-raising, which is why its
decorator is `notify_terminal=False`. That is what `notify-failure`'s
*"suppressed a duplicate of the verb's own failure notification"* (`reason: "forbidden"`,
`notified: false`) is talking about, and it means this class of failure is invisible in the trace
without being invisible to the user.

### §4.11's read-only rows around the restored archive folder, at both widths

`agriffith/system_settings/archive/f0465c23-60c2-4a6f-b622-c5ca10e5ffc7/` holds `receipt.txt` at
**414 B**. It was 359 B when the archive wrote it; what grew it is the two restore lines being
filled, and **which write filled which** is not something this sitting measured —
`MarkRestoreRequested` ran hours before the completion rewrite. Every reason string below is the
button's `title`, read off the DOM, and it is the same sentence in all six places: *"The archive
folder is read-only — it holds your archive receipts. You can open and download them, but not change
them."* — the banner's text too. **No `AccessDenied` appears anywhere.**

| Control | 1512x788 | 606x732 |
|---|---|---|
| Banner | present | present |
| **New folder**, **Upload** | present, disabled, that reason | present in the bottom action bar, disabled, that reason |
| **Move**, **Delete** (receipt selected) | present, disabled, that reason | present as icons, disabled, that reason |
| **Archive** | **absent from the DOM** | **absent from the DOM** |
| Check data quality, Send to, Copy | enabled | enabled |
| **Details** | opens a side panel | opens a **sheet** — a different mount |
| **Download** | works | works |
| **Rename** (in Details) | present, disabled, that reason | present, disabled, that reason |

**The control is what makes "Archive is gone" mean anything.** In `agriffith/spec220_archive_fixture/`
— an ordinary folder, restored earlier today and holding `header-only.csv` at its original 10 B —
`Archive selected items` is **present** at both widths: disabled with nothing ticked, **enabled**
with one file ticked, beside Move and Delete enabled and New folder and Upload carrying no title at
all. Absent in one folder and present-and-enabled in the other, at the same width, in the same
session.

**Download was checked by its effect, not by its affordance.** Clicking it wrote
`~/Downloads/receipt (1).txt` at 1512 and `receipt (2).txt` at 606, **414 bytes each**, both reading
`Restore requested: 2026-09-09 11:14:39 UTC` and `Restored to: s3://dat-prod-user-space/agriffith/`.
That independently corroborates this morning's receipt finding through a different instrument — the
browser's own download rather than an S3 read.

**Why both widths were worth the trouble.** At 606 the app mounts a different toolbar: a bottom
action bar carrying Restore Archived Data, New folder and Upload, an icon-only selection row, and
Details as a sheet. A desktop-only pass would have asserted nothing about any of them.

### The narrow width needed two things, and the log records only one of them

`resize_window` reported success and **the window really had resized** — `app_list_windows` showed
its bounds at `w: 606` — while the page went on reporting `innerWidth: 1512` and `outerWidth` of `0`
or a half-scaled number. This file already records that symptom and says the fix is to
bring the WINDOW to the foreground. **That is not the whole fix, and the missing half is the
TAB.** In order: minimized, stale; un-minimized by hand, **still** `innerWidth: 1512`;
`Control_Chrome`'s `switch_to_tab` on the tab id, and the viewport became 606x732 with **both**
compiled breakpoints reading `false` and `scrollWidth === innerWidth`. So `switch_to_tab` is
demonstrably necessary and is the one call to reach for. **Whether un-minimizing was ALSO
necessary is not settled here** — `switch_to_tab` was never tried against the minimized window,
so it may do both. Do not read the sequence as two required steps.

Two consequences worth keeping. A session that resizes and reads a stale `innerWidth` should check
`app_list_windows` before concluding the resize failed — the window and the tab disagree, and the
tab is the one lying. And **400px remains unreachable**: the window bounds confirm Chrome's macOS
floor of 606 again. 606 is the same CSS branch as 400 on this app — only `tablet:` and `desktop:`
are compiled and both are false there — so the rows above are a real narrow-branch pass, while the
overflow half of the 400px pass stays owed as it was.

**Left behind:** `receipt (1).txt` and `receipt (2).txt` in `~/Downloads`, and the refused archive's
notification in agriffith's inbox. **No fixture was created or removed, and this session issued no
AWS write of its own** — but "nothing was written to S3" would be false, and a first draft said it,
then a second draft said "two objects" and "five log records" and was also wrong. This ledger is
where a later reader looks to know what production state a sitting moved, so here is the whole of
it, measured:

| Object | What the run put there |
|---|---|
| `dat-prod-user-space/agriffith/user_settings/notifications.json` | the refusal notification — a get-then-put **rewrite of an existing inbox object**, not a new one |
| `logs/service=api/…/data.jsonl` | 2 records |
| `logs/service=archive/…/data.jsonl` | 5 records |
| `logs/service=notifications/…/data.jsonl` | 3 records |

**The notifications plane is the partition both earlier drafts forgot, and it carries the fact
worth having:** the notification the user actually reads was written on a **third** trace,
`dea0c455a12dc150a66d2356d086983d` — neither the run's nor `notify-failure`'s. Its `write` record
reads `recipient: agriffith`, `action: create`, `notifications: 107`, and 107 is what the inbox
showed, which is what ties that record to this run rather than to a neighbour in the same second.
The archive refusal itself touches no bucket; everything above is the plumbing around it.

---

## Live-check session — 2026-09-09 (SPEC-220 FR-004, and the owed rows discharged alongside it)

**Browser and CLI.** `main` at **`ac23ac45`**, every deploy workflow green on it. Signed in as
**agriffith** in Andrew's own Chrome profile through the Claude-in-Chrome extension, 1568x782,
light theme. CLI identity `arn:aws:iam::696000197480:user/tofu-deploy-user`.

**Two instruments, and both are ways this run differed from a user's.** The API calls below were
issued with `fetch` **from the signed-in page's own JS context**, using the session's own bearer
token — the token was never read out of the browser, and the responses were scrubbed before being
read. And `tofu-deploy-user` is **not** the deploy role (`dat-deploy-role` is GitHub-OIDC-only), so
it cannot read the space buckets — the user-space bucket policy answers `explicit deny` — and Lake
Formation filters `glue:GetDatabases` to `[]` for it. Every S3-and-catalog fact below therefore came
through the portal's API, not the CLI. The **admin** bucket it can read, which is what made the
structured-log rows reachable at all.

### SPEC-220 FR-004 — the live checks between the write switch and `finish`

Migration record **34234219110** (`copy`, 788 keys, 0 conflicts). **`finish` was NOT run.**

| Row | Result |
|---|---|
| Glue `LOCATION` unchanged | **Discharged (pre-`finish`).** All three real shared tables read `{space}/shared_tables/{table}`; across the **14** located tables in every database the session can see, **zero** point at `system_settings/`, `athenaresults/` or `archive/`. Zero catalog writes: the migration builds no Glue client at all. Owed: the same read after `finish`. |
| Archive ids | **Discharged** — the restore completed later the same day; see the archive section and its completion below. |
| First-segment rules | **Discharged.** `system_settings/athenaresults/…` refused, ordinary folder ran. |
| Query results at the new home | **Discharged.** |
| Attribute preservation | **Discharged for what the population carries**, three columns vacuous — see below. |
| Both archive homes refuse a write | **Discharged**, IAM and route halves, each with a control. |

**Query results.** `SELECT 1;` from the Query workspace, execution
`d069d840-e991-4cd4-a731-540f01927654`, SUCCEEDED 07:18:14 EDT. `batch-get-query-execution`
OutputLocation `s3://dat-prod-user-space/agriffith/system_settings/athenaresults/d069d840-….csv`.
It renders in the browser on page 8 of that folder, 12 B, dated Sep 9 among Sep 8 migrated files.
*Save results to my files* wrote `agriffith/query-results-20260909-0718.csv` — the save read a
**post-switch** execution's CSV at its new location. **Every other post-switch execution in the
workgroup does the same for its own owner** — `pxie` and `atalapatra`, real users, not fixtures.

**First-segment rules, discriminated by the execution INPUT rather than by timing.** Only one
refusal notification appeared and its "53 sec ago" was ambiguous between the two submissions, so
both were read out of the state machine:

| Execution | `location` in the SQS body | Outcome |
|---|---|---|
| `4666ef72-0f02-5ad7-b6ad-8c694ca31231` | `agriffith/system_settings/athenaresults/d069d840-….csv` | **FAILED** |
| `7cda642e-5da4-5acb-8e5d-07351e6b7a2e` | `agriffith/spec-222-athena-types.csv` | **SUCCEEDED** 07:24:07 |

The reason came from `RecordFailure`, not from the exit status:
`forbidden: 'system_settings' is a reserved prefix and cannot be checked`. It names the **first
segment**, not `athenaresults`. The user-visible notification is *"You don't have access to check
data quality there."*

**Both archive homes refuse a write.** IAM, from the operator CLI identity against
`dat-portal-user-role`, bucket `dat-prod-user-space`, context
`aws:PrincipalTag/username=alice`, **one resource per call**:

| Action | Key | Decision |
|---|---|---|
| `s3:PutObject` | `alice/archive/x` | **explicitDeny** |
| `s3:PutObject` | `alice/system_settings/archive/x` | **explicitDeny** |
| `s3:PutObject` | `alice/notes.txt` — control | allowed |
| `s3:DeleteObject` | both archive keys | **explicitDeny** |

Route, from the signed-in session — `PUT /v1/objects/content`:

| Key | Status | Body |
|---|---|---|
| `agriffith/archive/spec220probe.txt` | **403** | `{"error":{"code":"AccessDenied","detail":"archived locations are not writable"}}` |
| `agriffith/system_settings/archive/spec220probe.txt` | **403** | identical code **and** detail |
| `agriffith/spec220_route_control.txt` — control | **200** | wrote; deleted again afterwards |

The controls are what make both halves mean anything: without them a blanket refusal and a
key-specific one look identical. Together they are the proof the FR wanted — reverting the switch at
this point leaves nothing unprotected, because the **old** home still refuses too.

**Attribute preservation — and three of its five columns are vacuous for a reason worth stating.**
Two independent samples agree: `verify` run 34234773116 (40 keys, every bucket and space) and, this
session, `GET /v1/objects/metadata` on 12 old/new pairs read through the app. All match.

| Column | Verdict |
|---|---|
| content type | **Preserved and it VARIES** (`application/octet-stream` vs `binary/octet-stream`) — real evidence |
| size | Preserved |
| storage class | Every object in both moving prefixes is `STANDARD` |
| user metadata | Empty on every sampled object, both samples |
| tags | Empty on every sampled object |

The last three are vacuous because the **population is uniform**, not because the check was skipped.
The `StorageClass` / `MetadataDirective=COPY` / `TaggingDirective=COPY` mechanism is covered only by
FR-002's fake-asserted unit test; production holds no object that could redden it.

### The archive and restore, run under §4.11's approval gate

Fixture `agriffith/spec220_archive_fixture/` created this session with one copied file
(`header-only.csv`, 10 B). The confirm dialog named the folder **relative to the space root**, said
removed-from-this-space and "several hours", carried **no** "can't be undone", and focus was on
**Cancel**. Archive finished in ~16 s: **`f0465c23-60c2-4a6f-b622-c5ca10e5ffc7`**, the fixture gone
from the root.

- **The notification's href is `/files?prefix=agriffith/system_settings/archive/f0465c23-…/`** — the
  new home, not the space root. The 21-hour-older archive `ff8c833a-…` links there too.
- Following it: `receipt.txt` 359 B, read-only banner, **Archive absent** from the toolbar, New
  folder and Upload greyed.
- Restore dialog, nonsense id: *"That doesn't look like an archive id. Ids look like
  3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93."*, and the submit control stayed **enabled**.

**Submitted twice, 25 s apart (11:14:39 and 11:15:04 UTC).** Two executions with **distinct**
request ids — `589e1b90-…` and `7728c043-…` — so the FIFO dedup did not collapse them, and both
target the same receipt key `agriffith/system_settings/archive/f0465c23-…/receipt.txt`. **One
`RestoreObject` bill**, read from `/aws/lambda/dat-prod-archive-initiate-restore`:

```
11:14:48  requested retrieval of 2 object(s) in this batch
11:15:07  retrieval of …/header-only.csv needs nothing further
          (RestoreAlreadyInProgress … Object restore is already in progress)
11:15:07  retrieval of …/spec220_archive_fixture/ needs nothing further (RestoreAlreadyInProgress …)
```

The vault root is unchanged at `personal/agriffith/archive/{uuid}/` — fact 2 did not move.

**The receipt at the new key was rewritten THREE times, and the last one closes the row.** Each run's
`MarkRestoreRequested` wrote it in submission order — 11:14:45 for the winner, 11:15:06 for the
loser — and then the winner's completion `UpdateReceipt` wrote it again at 14:25:18. Mid-flight it
carried `Restore requested: 2026-09-09 11:15:04 UTC` — the **second**
submission's timestamp — with `Restored to: -` empty. On completion it reads:

```
Restore requested: 2026-09-09 11:14:39 UTC
Restored to:       s3://dat-prod-user-space/agriffith/
```

Two things there. `Restored to` is **filled**, at
`agriffith/system_settings/archive/{uuid}/receipt.txt` — the completion rewrite at the new key,
which is the last piece FR-004's archive row was waiting on. And **`Restore requested` CHANGED**:
the winner had written its own timestamp first, the LOSER overwrote it, and the winner's completion
put it back. A reader who captured that field while both runs were in flight recorded the losing
run's time with no way to know.

The `restore-progress.json` key is request-stable, so each submission wrote its own: the **winner's**
`restore-progress.json` ended at `pollCount: 38`, `completedThrough: 2/2` (the loser's stopped at 37
and 0). The fixture is back
at `agriffith/spec220_archive_fixture/header-only.csv` at its original 10 bytes — matching the
restore plan's `destKey` exactly.

**The two submissions ended differently, and the loser is useful.** `a764630d-…` (the first)
**SUCCEEDED**; `f53a9960-…` (the second) **FAILED** after `PollRestore`, running
`RequestFailureSeed` → `RecordFailure` → `NotifyFailure` → `Failed` with `ArchiveFailed` — because
the winner's `DeleteArchived` had already emptied the vault, so `PollRestore` 404'd on the key it was
tracking. Worth naming: without it a later reader cannot tell a concurrency artefact from a
reproducible verb failure. That is a
real **archive-plane post-identity failure**, which is exactly the shape SPEC-227 FR-002's half (a)
asks for — arrived at without needing the deliberate occupied-destination run that row proposes.
**And it settles half (a) — the read is recorded here rather than left as an instruction.** In
`logs/service=archive/year=2026/month=09/day=09/`, that run's `notify-failure` records sit on trace
`4176296ab3e0910e5adcf75520db8f87` with `parent_span_id` `6a790f3dafd1a9fb` — the **same trace and
the same parent** as its own `validate-authorize` records — logging *"suppressed a duplicate of the
verb's own failure notification"*, reason `archive_object_unreadable`. Every one of the run's records
carries that single trace.

**It is not a lucky stand-in for the run the row proposed.** The deployed archive ASL routes 20 of
its 24 `Catch` transitions to the same `RequestFailureSeed`, `CheckDestinationClear`'s among them —
so the deliberate occupied-destination restore would have entered the identical state. That makes
the discharge a proof rather than a judgement call.

### The restored object's attributes, checked after the restore landed

**`owed.md`'s `head-object` row is discharged — and half of its stated blocker was never true.**
The bucket half is real and current: `tofu-deploy-user` gets `403` on `head-object` against
`dat-prod-user-space` and an explicit-deny `AccessDenied` on `dat-prod-archive`. **The other half —
"the UI cannot show a storage class" — has been false since 2026-06-15**, when SPEC-017 shipped the
Details drawer: `MetadataPanel.tsx` renders a `Storage class` field, and the API contract says in so
many words that `storageClass` is returned *because* that panel renders it. The row was written on
2026-08-14, two months later. **It sat owed partly on a UI limitation that did not exist**, which is
the cheaper lesson here than anything about Glacier: a blocker is a claim, and it goes stale like
any other.

And "no `head-object`" is not right either — `routes/objects_head.py` calls `head_object`. What
changed is the **principal**: the route makes the call server-side under a role that can reach the
bucket, where the operator CLI identity cannot.

The control is `agriffith/header-only.csv`, the **never-archived** object this fixture was copied
from, so the comparison is against an independent reference rather than the restored file against
itself:

| | control (never archived) | restored |
|---|---|---|
| storage class | `STANDARD` | **`STANDARD`** |
| content type | `text/csv` | **`text/csv`** |
| size | 10 | **10** |
| last modified | 2026-08-06T01:11:48Z | **2026-09-09T14:25:14Z** |

ETag, raw bytes and SHA-256 all equal.

**What each column is actually worth, because three of the four are weaker than they look.**

- **`lastModified` is the one that does real work.** The restored object carries the copy-back's
  timestamp, hours after the archive; the control keeps its original upload. That is the only
  first-party evidence here that the file was *rewritten* rather than never removed — the other
  three columns are all equally consistent with an object that never left. Corroborated: the archive
  execution ran `DeleteSource`, and the fixture was gone from the root listing.
- **`STANDARD` excludes a real and silent failure**, which the archive ASL names on
  `CopyBackObjects`: an item copied without an explicit STANDARD *"lands back in GLACIER and expires
  to unreadable a few days later, having looked like a success throughout."* That is what the
  reading buys. It does **not** establish what the vault held — `GLACIER`-stays-`GLACIER` on the
  archived object is still listed as not observable at all, and nothing here changes that. An
  earlier draft of this entry argued it did, from the `"storageClass": "GLACIER"` on the transfer
  manifest; that field is `arcommon.config.ARCHIVE_STORAGE_CLASS`, a constant stamped on every
  archive run, so it records what the plane was *told* to write and would read the same if S3 had
  stored the object anywhere.
- **Read the route's defaults before trusting either string.** `storageClass` is
  `head.get("StorageClass") or "STANDARD"` and `contentType` falls back to
  `application/octet-stream`, so `STANDARD` means "S3 reported no class". It still bites, because S3
  reports `GLACIER` explicitly.
- **`text/csv` excludes nothing on this fixture.** `MULTIPART_COPY_THRESHOLD` is 5 GiB, so 10 bytes
  took the single-copy path, where `MetadataDirective` is S3's own default anyway. The content-type
  loss lives on the multipart path, and the `>5 GiB` row one line below says a fixture under the
  threshold "passes forever". An earlier draft called this discriminating; it is not.

### Closed later the same day, after two PRs landed

**The table-builder timeout defect, fixed and confirmed live.** The gap this session found — a
plane with a state-machine ceiling and no EventBridge door — was closed in two PRs (the deploy-role
grant first, on the register's rule, then the rule and the handler's detail-type door). Re-measured
against the account afterwards: the rule is **ENABLED**, `TIMED_OUT` only, no `FAILED`, scoped to
its own machine and targeting `dat-prod-table-builder-notify-failure`, and **all six orchestrators
with a `TimeoutSeconds` now carry one** while the two without a ceiling correctly carry none.

**Three things the landing itself taught, none of which a test would have said.**

The `Deploy Infrastructure` failure on the first push read `checkov-plan.json missing` — three
steps downstream of the truth. The real failure was `Assert the planned Lambda fleet`, which skipped
the Checkov steps; `Summarize` then ran under `if: always()` and failed on the absent file. **Read
the first failing STEP, not the last error line.**

That fixture caught a change a review had called a nit: a `notify-failure` timeout raised 15 s → 60 s
"for consistency" with the five sibling doors. It was reverted rather than declared, because the reason the
siblings sit at 60 does not transfer — three of them read the execution input back with
`DescribeExecution` **when EventBridge drops an oversized one** — a conditional AWS call with its own
retries — which this door skips by design. **"The siblings do it" is not a measurement.**

And `git diff origin/main` showed **788 deletions** including two of a peer's new spec files, purely
because `main` had moved under the branch. The three-dot diff showed the real change: 10 files, 7
deletions — and the merged commit is 9 files and 6, the difference being the revert above. **A two-dot diff against a moving branch reads a peer's additions as your deletions.**

### Owed rows discharged alongside, none of them SPEC-220's

**SPEC-225 FR-005 — a real run's records carry ONE `trace_id`, in production.** Three runs driven
from the portal — one archive, two restores — read out of
`logs/service=archive/year=2026/month=09/day=09/`:

| Run | requestId | trace_id | records (final) |
|---|---|---|---|
| archive | `f0465c23-…` | `563c95688e4f0d0a68c4e248f79075ca` | 33 |
| restore #1 — succeeded | `589e1b90-…` | `084afa307f1c5931a58f39330ad114ca` | 159 |
| restore #2 — failed | `7728c043-…` | `4176296ab3e0910e5adcf75520db8f87` | 139 |

These per-run counts are **final** — each run has ended, so they no longer move, and they are the
cheapest way for a later reader to confirm they are looking at the same population. What does keep
growing is the DAY's object, which is why nothing below is stated as a day-scoped total.

**Zero** request ids carry more than one `trace_id`. **Three runs, three different trace ids** —
which is the warm-container half: the two restores ran 25 s apart, so the containers were certainly
warm, and neither stayed in the first run's trace. **Every `span.start` belonging to those three runs carries a non-null `parent_span_id`; every record carrying NO request id is a deploy-time cold-start probe, and every one of those has a null parent.** That split is the load-bearing part, and stating it as two POPULATIONS rather than as a pair of counts is deliberate — an earlier draft of this entry pinned 66 and 73, which the restores had already outgrown before the entry was written, and which every deploy since has grown further. The archive run's trace id is the
one in its own SQS `traceparent`, so it was minted at the API and propagated in. **The file-send half
holds too** — three runs driven below, each one trace, zero null parents, the largest 65 records
across 8 Distributed-Map children — so the row is settled on both planes the recipe names.

**SPEC-225 FR-003 AC-1 — `ItemBatcher.BatchInput` reaches the child of an `ItemReader`-fed
Distributed Map, `Items` unchanged beside it.** Discharged without the throwaway state machine, as
the row predicted. The deployed archive orchestrator has **three** Distributed Maps —
`TransferObjects`, `RetrieveObjects`, `CopyBackObjects` — each `ItemReader`-fed with
`ItemBatcher.BatchInput` carrying `traceparent.$` and `requestId.$`. A child execution's **actual
input**, read back from the archive run:

```json
{"BatchInput":{"requestId":"f0465c23-…","traceparent":"00-563c95688e4f0d0a68c4e248f79075ca-be39d1932b67fee8-01"},
 "Items":[{"srcBucket":"dat-prod-user-space","srcKey":"agriffith/spec220_archive_fixture/", … ,"storageClass":"GLACIER"},
          {"srcBucket":"dat-prod-user-space","srcKey":"agriffith/spec220_archive_fixture/header-only.csv", … }]}
```

`BatchInput` and `Items` are both present, the items are the manifest rows untouched, and **the
items carry no traceparent of their own** — which is what makes this sound rather than circumstantial:
`BatchInput` is the only channel the child's trace could have arrived by. Corroborated at runtime on
two different Maps, since `copy-objects` and `initiate-restore` records both carry their run's trace
id and a non-null parent span.

**SPEC-170 — the restore plan agrees with the receipt.**
`s3://dat-prod-athena-admin/archive/589e1b90-…/restore-plan.json` exists, `objectCount: 2`,
`totalBytes: 10`, and the receipt reads `Files archived: 2`. Both `destKey`s are the original paths
(`agriffith/spec220_archive_fixture/` and `…/header-only.csv`).

**The `TIMED_OUT` door — the pattern half, and it found a hole.** **Superseded later the same day:
the hole is closed and all six planes with a ceiling now carry a rule — see "Closed later the same
day" above. What follows is the state as measured at the time.** Production runs **eight**
orchestrators. Five — `archive`, `file-ops`, `file-send`, `results-conversion`, `table-share` —
each carry an `…-orchestrator-timed-out` rule, all **ENABLED**, all with `detail.status` exactly
`["TIMED_OUT"]`, **no `FAILED` anywhere in the pattern**, each scoped to its own
`stateMachineArn` and targeting that plane's `notify-failure`. `data-quality` and `shared-space`
set no `TimeoutSeconds`, so they cannot emit `TIMED_OUT` and correctly have none. **`table-builder`
sets `TimeoutSeconds: 3600`, ships `dat-prod-table-builder-notify-failure`, and has NO rule** —
confirmed twice, no rule in the account names it in its event pattern and
`infra/modules/table-builder/` defines none. A state-machine timeout cannot be caught by a `Catch`,
so EventBridge is the only door and that plane has none: an hour-long build that times out
notifies nobody. Raised as a defect row in [`owed.md`](owed.md), not filed as coverage.

**The synthetic-event half is still owed, and my first write-up of WHY it was owed was wrong.** I
recorded that it needs a real ID token the session cannot extract. It does not: since SPEC-201
(`ff3a76b6`, 2026-08-30) `cpactor.trusted_actor` reads only the nested `identity` block and
imports no JWT code, and §2.5's payload still carrying a flat `actor` token is stale — a run built
from it would be refused `unauthorized` and read as a broken door. `events:PutEvents` on the
default bus measured **`allowed`** for this CLI identity. What actually blocks it is that the
harness refuses an agent session's production AWS writes, and `put-events` is one — measured, not
assumed. The recipe in §2.5 has been rewritten to build the payload in Python and to say this.

**SPEC-196 §E.9 — the twelve-row IAM simulation, run rather than inherited.** All twelve rows of
SPEC-196's table against `dat-portal-user-role`, one resource per call, every denial paired with
its `allowed` control: GetObject alice/bob; ListBucket with `s3:prefix` alice/bob; DeleteObject on
an ordinary key versus `DO_NOT_DELETE.txt`; PutObject on `alice/archive/`; `glue:GetTable` on
database alice/bob; and the three shared-space slot-tag rows including **slot tags absent** to
`implicitDeny`. **Twelve expected verdicts, twelve matches, zero mismatches.** Four extra rows
beyond the table: shared-space `DO_NOT_DELETE.txt` **explicitDeny** with an ordinary shared key
**allowed** as its control, and `system_settings/archive/` and shared
`system_settings/athenaresults/` both **explicitDeny** — which is SPEC-220's new home refusing on
the shared side too. That also discharges the `DO_NOT_DELETE.txt` row, personal and shared.

**A correction I had to make to my own first pass at this file.** I initially struck §E.9 on the
strength of its section intro, which says SPEC-202 FR-010 discharged it on 2026-08-31. The intro
is not evidence: the ported Arc B log covers GetObject/PutObject alice-versus-bob and nothing
else, so the strike retired a twelve-row check on about two rows — while `DO_NOT_DELETE`, which
IS row 6 of those twelve, sat a few lines above still marked open. I had spot-checked that the
intro said it, not that the evidence covered it. Running the twelve is what actually settled it.

**The file-send plane's nightly ERROR records are the cold-start probe, not breakage.**
`logs/service=file-send/` carries, every day, a run of `validate-authorize` `span.start` /
`span.end` pairs at **ERROR** level in the same millisecond, with no `request_id` and a null
`parent_span_id` — 7 on day 09, 7 on day 07, 10 on day 08, 15 on day 06. Today's **7** is exactly
the number of `Deploy Lambdas` runs on `main` today, and the shape matches the probe's discharged
2026-09-02 result ("six `validate-authorize` verbs refusing with `TerminalError`"). Recorded because
ERROR-level records on a plane with no user traffic look like a live defect and are not one.

**The file-send half of the trace row, and the fan-out row.** That plane had **no real run** in the
logs bucket for days 06–09, so three were driven. The log sweep is on a ten-minute schedule, so each
needed a wait.

| # | requestId | Recipients | Outcome |
|---|---|---|---|
| 1 | `456ae6a8-…` | `agriffith_three` | **`recipient conflict`**, transfer skipped — the recipient already held the file. 18 records, **one** `trace_id` `522a88ce…` (the one in its own SQS `traceparent`), 6 `span.start`, **zero** null parents. **No Map child at all**, so no `batch copied`. |
| 2 | `e2fbb066-…` | `agriffith_three` + space `dwb_testing_all` | Copied, trace `fb345885…`. Map run `total: 2`, and `MaxItemsPerBatch: 8` put both items in **one** child. |
| 3 | `1de4a077-…` | same two | `arcb_files/` — the copy plan counted **29 objects** (the browser lists 23 files; that listing is not recursive and the plan is). Map run **`total: 58, succeeded: 58`** = 29 × 2, across **8 children**. |

Run 3 is the fan-out: **exactly 8 `batch copied` events for 8 child executions**, item counts
`8+8+8+8+8+8+8+2 = 58` — the Map's own total — each with a distinct `span_id` under **one shared
`parent_span_id`** `f037c2da…`, so the fan-out reads as a span tree rather than a count. 65 records,
one `trace_id` `25dc566d…`, 25 `span.start`, **zero** null parents.

**Two traps worth writing down.** First, runs 1 and 2 would each have "passed" the fan-out row while measuring nothing: one file to one recipient is 1 item → 1 child → 1 event and the 1:1 holds trivially, while a conflict produces 0 children and 0 events, which also "matches". It needs **more than `MaxItemsPerBatch` (8) transfer items** before it can fail. Second, **size that from the OBJECT count, not from the browser's**: this folder shows 23 files in the UI and the copy plan counted 29 keys, because the rendered listing is not recursive. Sizing a fixture from the UI number lands you under the batch size in the direction that measures nothing.

**A re-measurement that turned out to measure nothing, which is worth recording as such.** §1's *Accepted exposure* row records a complete stale Cognito token set for `agriffith_three` in `localStorage`, observed 2026-09-01. Today `localStorage` on `https://portal.dataquarry.app` holds **exactly one** key, `CognitoIdentityServiceProvider.<app-client-id>.oauthSignIn` — the key count settles that no token key is hiding. **But it is not the same subject.** `localStorage` is per origin: the 2026-09-01 reading was on `d1kbh4bnvh1je8.cloudfront.net` in Chromium via an agent browser; today's is `portal.dataquarry.app` in Andrew's own Chrome — and that same origin already read exactly this way on 2026-08-31. So nothing changed and nothing was retired. The CloudFront distribution was destroyed 2026-09-02, so the origin holding the set cannot be loaded again: it is **unreachable, not demonstrably cleared**. Recorded because a reading that looks like good news and is really an origin mismatch is exactly how a dated claim gets retired for the wrong reason.

**One observation against SPEC-227 FR-002's recorded limit, on the wrong plane to settle it.** The
refused data-quality check above (`d3c33db9-…`) is a **post**-identity failure — actor verified, the
*location* refused. Its `validate-authorize` records sit on the run's trace `69f4847b…`; its
`notify-failure` ran 3 s later on a **different** trace `2333f306…` with a **null**
`parent_span_id`, logging *"no requestId on the failed request"* and *"no verified actor; nothing to
notify"*. That is the shape the register attributes to **pre**-identity failures. **It is not a
user-visible defect** — the refusal notification was written 1 s earlier by the notifications
`write` verb on its own trace `1c485086…` (0.9 s before `notify-failure` ran), so the lost `notify-failure` notification is not user-visible **here**. Note the two facts are independent: `notify-failure` skipped because the seed handed it no actor, **not** because it detected an existing notification — had the seed carried one it would have sent a second. It is
recorded because SPEC-227's row is about **archive**, and if archive does the same the register's
"pre-identity" wording is too narrow. **ANSWERED in the second sitting above: archive does do the
same, the wording was too narrow, and the register now defines "pre-identity" as the CATCH shape —
which makes this data-quality run an ordinary instance of the class rather than the anomaly this
paragraph took it for.** **Superseded later the same day — half (a) is discharged; see the restore-completion section
above.** What this paragraph proposed (a restore into an occupied destination, failing at
`CheckDestinationClear` before any billable retrieval) was never needed: the losing restore supplied
the same state through the same seed.

**Left behind in agriffith's space:** `query-results-20260909-0718.csv` (the evidence for the save
row) and archive `f0465c23-…` with its receipt folder; the restore will put
`spec220_archive_fixture/` back at the space root. The route-layer control object was deleted.

---

## Live-check session — 2026-09-02 (SPEC-202's post-merge-2 CLI pass, and the arc's close)

**CLI only, no browser.** Run against the deployed account from the repo worktree with the
`tofu-deploy-user` credentials, `main` at **`a546f2e4`** (SPEC-202 merge 2) and then at
**`95fddf14`** (the deploy role's grant retirement). Every workflow that ran on each sha concluded
success; **Publish Config ran on `a546f2e4` only** — its `paths:` filter matches none of the grant
retirement's files, and "did not run" is not "green". **No instruments** — every
assertion below is a `curl` or an `aws` read, which is why the browser half of the arc's §12 is
still owed rather than discharged here.

**The retirement, proved positively rather than as an absence from a plan:**

| Check | Result |
|---|---|
| `cloudfront get-distribution --id E63PRJKNACLDP` | **`NoSuchDistribution`** — the id was captured before merge 1 precisely because its Terraform output does not survive |
| `s3api head-bucket` on the static bucket | **404**. `list-buckets` returns four app buckets (user-space, shared-space, admin, archive) plus artifacts, archive-audit and state |
| `cognito-identity list-identity-pools` | **`[]`** |
| `describe-user-pool-client` callback and logout lists | each exactly `http://localhost:5173` and `https://portal.dataquarry.app`. The CloudFront entry is gone from both |
| `apigatewayv2 get-api` CORS | `allow_origins` = `["https://portal.dataquarry.app"]`, `allow_credentials` **false**, `allow_headers` carries `x-request-id` |
| `get-bucket-cors` on user-space and shared-space | `localhost:5173` and `spa_origin` only, on both |
| `curl -sSI https://portal.dataquarry.app/` | CSP (enforcing, not report-only), HSTS `max-age=31536000; includeSubDomains` with **no** `preload`, `X-Frame-Options: DENY`, nosniff, `Referrer-Policy`, `Permissions-Policy`, COOP, CORP, and `Server: nginx` — the three divergences as designed. `connect-src` = `'self'`, `cognito-idp`, the Hosted UI host, both S3 buckets, `api.dataquarry.app`; **no** `cognito-identity.`, `athena.`, `glue.` or `sqs.` |
| `curl -sS …/config.json` | **eleven** keys and **no `cognitoIdentityPoolId`**. Eleven rather than the arc's ten because `maxUploadBytes` arrived with SPEC-216 afterwards — a count in a spec is dated the day it is written |
| `iam get-role-policy` on the deploy role, after #614 applied | **22 statements**; `S3StaticBucket` and `CloudFront` both absent (24 before) |
| The notifications writer's `NOTIFICATIONS_UNTRUSTED_SENDER_ID` | equals the live portal role's unique id (`AROA2EDGYGNUCQJ24WOYE`) — non-empty, so SPEC-206's `create` boundary is configured, and it needed nothing from this spec |

**One finding, and it is about a claim rather than the deployment.** `CLAUDE.md` carried an
obligation saying SPEC-202 "re-points SPEC-206's `SenderId` boundary, which still names the portal
role it retires". **SPEC-202 does not retire the portal role** — it retires the Identity Pool, and
the role is *reused* by the API, which is the whole reason no permission policy had to change. The
boundary needed no re-pointing, and the deployed value confirms it. The obligation was written from
a premise that reads "the credential path is retired" as "the role is retired".

**Not run, and not passed:** everything needing a browser — the fresh sign-in against the narrowed
lists above all, and a real presigned upload and download, which is the only check that can detect
the bucket-CORS narrowing. Those and the five checks merge 2 was waived on are rows in
[`owed.md`](owed.md) → *SPEC-202*.

---

## Arc B's execution log — ported 2026-09-02 from the arc script's §15 (runs of 2026-08-30, 08-31 and 09-01)

**Every `§` in this entry is the DELETED arc script's numbering**, not `e2e.md`'s — its §5 is the
ported surface, where `e2e.md`'s §5 is cleanup. Read a section number here as a pointer into
`git show 95fddf14:docs/testing/arc-b-api-container-e2e.md`.

**Ported, not re-run.** These are the arc's own dated results, moved here verbatim in substance when
`arc-b-api-container-e2e.md` was deleted at the arc's close. They were observed by the sessions that
ran them on the dates given; nothing below was re-observed on 2026-09-02. The full original text,
with every step's wording, is `git show 95fddf14:docs/testing/arc-b-api-container-e2e.md`.

**Two ids were captured before merge 1, because their Terraform outputs do not survive it:**
identity pool `us-east-1:b937244c-1632-420d-81af-49838df20233`, distribution `E63PRJKNACLDP`
(both 2026-08-30).

### Pre-merge-1 (2026-08-30, CLI)

| Check | Result |
|---|---|
| SPEC-193's three additive allowlist changes are live | **PASS.** Callback and logout lists each carried `http://localhost:5173`, the CloudFront domain and `https://portal.dataquarry.app`; CloudFront's `connect-src` named the API; the API's CORS listed both origins. Verification only — nothing was added. |
| The deployed trust policy | **PASS.** `dat-portal-user-role` carried **two** statements: the federated one, and `TheApiMayActAsAUser` admitting the API role with `sts:AssumeRole` + `sts:TagSession` and an eleven-key `sts:TagKeys` ceiling. SPEC-196's statement applied, so merge 1 would leave the role assumable. |
| FR-002 AC3 — the container's `appUrl` | **PASS.** Task definition `dat-prod-spa:48` set `CONFIG_appUrl=https://portal.dataquarry.app`. A container naming CloudFront here sends every sign-in to the other origin. |
| FR-008 — the `connect-src` before-state | Recorded: ten terms, including `cognito-identity.`, `athena.`, `glue.` and `sqs.`. Merge 1 takes those four. |
| FR-008 AC4 — `Server` absent | **Contradiction, not a failure.** The origin returns `server: nginx`; nginx cannot strip it without a third-party module. SPEC-194's first recorded divergence, and the criterion was written before the container was measured — the spec was corrected, not the deployment. |

### Post-merge-1 (2026-08-31)

| Check | Result |
|---|---|
| `describe-identity-pool` on the recorded id | **PASS — `ResourceNotFoundException`.** A positive absence, not "gone from the plan". |
| `get-role`, one trust statement | **PASS.** Exactly `TheApiMayActAsAUser`; no `Federated` principal remains. |
| **FR-010 — the portal role, simulated against the DEPLOYED role** | **PASS.** `s3:GetObject` and `s3:PutObject` on `alice/` **allowed**; the same two on `bob/` **implicitDeny**. Every denial paired with an `allowed` control on the same bucket, so an ungranted action is distinguishable from a mistyped ARN. The retired browser grants stay retired: `sqs:SendMessage` and `athena:StartQueryExecution` both `implicitDeny`. **No row changed from SPEC-196's pre-retirement table.** |
| FR-010 — the API execution role | **PASS.** `sts:AssumeRole` on the portal role **allowed** (the control); `s3:GetObject` on a user-space key **implicitDeny** — the one worth the trouble, since a stray direct grant would make every route work while silently bypassing the tag. |
| FR-010 — the SPA task role | **PASS, asserted by ABSENCE.** `list-attached-role-policies` and `list-role-policies` both `[]`. Not by simulation: a role with no policies returns `implicitDeny` for everything with no control available, and an unpaired `implicitDeny` presented as a pass is the failure the rest of FR-010 exists to avoid. |
| FR-008 — the deployed `connect-src` | **PASS.** Exactly `'self'`, `cognito-idp`, the Hosted UI host, both S3 endpoints, `api_origin`. `athena.`, `glue.`, `sqs.` and `cognito-identity.` gone; both Cognito hosts remain, which is its own criterion. |
| FR-008 — the header set | **PASS (headers).** CSP (never `-Report-Only`), HSTS `max-age=31536000; includeSubDomains`, `X-Frame-Options: DENY`, nosniff, `Referrer-Policy`, `Permissions-Policy` all present; `server: nginx` present as the recorded divergence. **A header name is not evidence of enforcement** — that is the next row. |
| FR-004 — the runtime document | **PASS.** Ten keys and no `cognitoIdentityPoolId`; running image tag `85ea5457…` = `main`. (Eleven keys since SPEC-216 added `maxUploadBytes`.) |
| **The CSP is enforcing, with a negative control** (Chromium) | **PASS.** A `fetch` to `athena.us-east-1.amazonaws.com` raised a positive `securitypolicyviolation`, `effectiveDirective: "connect-src"`, `disposition: "enforce"`; `/config.json` returned **200 in the same run**. **The method is measured, not assumed:** CDP evaluation is exempt from `script-src`, NOT from `connect-src` — SPEC-140's prescription over-generalised from a `script-src` measurement, and this is the correction. |
| **FR-008 — four absences and two presences, in one run** (Chromium) | **PASS.** Blocked: `cognito-identity.`, `athena.`, `glue.`, `sqs.` — four violations, no more and no fewer, every one `connect-src`/`enforce`. Allowed: `cognito-idp.`, the Hosted UI host, `api.dataquarry.app`, the user-space S3 endpoint. The two Cognito presences are the criterion whose omission broke fresh sign-in for a day. |
| **The rollback rehearsal** (Chromium, post-merge-1 and pre-merge-2) | **PASS.** The CloudFront domain loaded the app and completed a real cross-origin API call: `GET /healthz` → 200, `version` = `85ea5457…` = `main`; same ten config keys, no `cognitoIdentityPoolId`, `appUrl` its own origin. **A CloudFront-served HEAD bundle talking to the API — it does NOT restore browser-direct AWS**, because that code was gone from HEAD and so was the pool. Run in the only window where it was both meaningful and possible. |
| §3 (fresh sign-in) and §6 (deep link, clocks) | **NOT RUN.** Needed a sign-in in a clean profile, or a token-clock change nobody had asked for. |
| §6 — deep link while signed out, first half | **PARTIAL.** `/query?db=demo` while signed out lands on `/` and stores `portal.returnPath`. The half that matters — landing back on it **after** sign-in — is unrun, and so is the private-browsing repeat. Recorded as partial because a working capture and a failing restore look identical from here. |
| §9 — the breakpoints, desktop only | **PARTIAL.** At 1512px both compiled breakpoints resolve. **400px unrun**: not reachable by window resize on macOS. Safari's half was **retired at its premise** on 2026-09-01 — the audience has no Safari — rather than left owed. |

### Post-merge-1 (2026-09-01, Chromium) — the ported surface and the planes

| Check | Result |
|---|---|
| **§5 steps 1–4, 9 — the object surface** | **PASS.** Counted in-page (`fetch` + XHR wrapped) because the extension's network reader drops requests. Listing page = **1** call; details = 1 `metadata`; folder create = 1 `PUT /v1/objects/content`; copy = 1 `POST /objects/copy`; single delete = 1 `DELETE`. A 12 MiB upload = **one `PUT` over XHR**, with **51 progress samples, first at 1.6%** — a `fetch` upload emits none, which is the silent loss that row exists to catch. Download: SigV4, `response-content-disposition` `attachment` naming the file, **12,582,912 bytes**, exact. Free name = `name (4).txt` from **one** `/free-name` call, not 4 and not 999. |
| §5 step 1 — the collision path | **PASS.** Moving a copy back onto its original is refused **server-side** (`POST /v1/objects/move` → 409), surfaced as "1 item(s) already exist at the destination" with Overwrite all / Cancel, and Cancel reports **"Moved 0 items."** rather than a false success. |
| **§5 step 5 — saved queries** | **PASS.** Personal save, edit and re-save are **one `PUT` each**. Saving into a shared space issued **two** `PUT`s: the `.sql` plus `ensureSavedQueriesFolder`'s marker, written `overwrite: false` once per space per session with `Conflict` as its success case. Checked, not assumed. |
| **§5 step 6 — the NULL clause is filed against the wrong surface** | **PASS on rows; clause reassigned.** 10 rows, and the `sql` on the wire is byte-identical to the editor. NULL and `''` render identically in the **Query** grid, deliberately; the API distinguishes them correctly on the wire. The criterion belongs to step 7, where `CellValue.tsx` renders italic `NULL` vs `(empty)`. Nearly written up as an app defect; it was a script defect. |
| **§5 step 7 — Data Explorer** | **PASS.** Opening the table = 1 execution. Paging past row 100 = **0 new executions** and the billing line unchanged. The `O'Brien` filter is a new execution, and the generated SQL is `WHERE "name" = 'O''Brien'` — quote **doubled**, the Trino/DML escaper, with double-quoted identifiers. The wrong escaper here is a predicate that silently matches nothing. |
| **§5 step 8 — Lake Formation still filters, with a paired control** | **PASS.** As the member, the rail lists only their own database and the one space they belong to. A rail can be filtered client-side, so the query was run: `SELECT * FROM agriffith.arcb_report` → **Failed, "You don't have permission to run that query"**, terminal, with **no `/results` fetch** and **no re-login**. Control, same user and minute: `agriffith_three.employees` → **Succeeded, 2 rows, 112 B**. One database denied and another allowed through the same route, so the grant is on the **assumed** role. |
| §5 step 10 — membership propagation | **PARTIAL.** The member added shows **Pending** on the owner's roster, and after a fresh sign-in the space appears, lists files and the cloned table queries. The **pre-refresh refusal was not observed** and cannot be from one browser: switching accounts mints a token that already carries the membership, so the refusal and the fix are indistinguishable. |
| **§8 — seven of the eight planes, each through the API** | **PASS (7/8).** One `POST /v1/enqueue/{plane}` per gesture and **no browser `sqs:SendMessage` anywhere**: shared-space, notifications, table-build, table-share, data-quality, file-send, file-ops. Every one produced its notification. File-send told the sender once ("Sent \"arcb_send\" (4 files)" — the count includes the nested file, so the walk recursed) and the recipient once, with the four files really under `shared_files/agriffith/arcb_send/`, `nested/` intact. Table-share cloned **150 rows** into the recipient's database and they can query it. |
| **§8 — the links, and two rows that carry none** | **PASS with a finding.** Links resolve for file-ops, file-send and data-quality (the report renders 150 rows, 1 file, 0 duplicates, `name` 20.0% null-or-blank, with the space taken **from the route**). **table-build and table-share carry no `link` at all**, against the section's "with a link" — deliberate in `tbcommon/notify.py`, which does pass one for the `columns_removed` failure. Still open: either those planes gain a link or the clause goes. |
| §8 — the archive row | **NOT RUN.** The only irreversible gesture in the section: a restore is 3–5 billed, uncancellable hours. Held for an explicit go-ahead. |
| §9 — 400px | **PARTIAL.** `resize_window` reports success at 400×800 while the page reports `innerWidth: 606` — macOS clamps the window. It is **not inert** (both breakpoints correctly flip to `false`), it simply cannot reach 400. At 606: hamburger nav, `scrollWidth === innerWidth`, no horizontal overflow. Only `tablet:` and `desktop:` are compiled, so 400 and 606 are the **same CSS branch**; what stays unproven is overflow at the narrower width. |
| **The pre-merge-2 waiver** | **WAIVED by user decision — not run, and not passed:** §3, §6, §8's archive row, §9's 400px and §5 step 10's first half. Merge 2 was taken with these open. **The one that gates that merge specifically is §3** — merge 2 narrows the Cognito lists, §3 is the only check that exercises them, and a broken fresh sign-in is invisible to every signed-in session. §12 re-runs it after the irreversible step instead of before it, which is the risk accepted. The rest are arc-completeness: merge 2 touches none of their machinery. |

---

## Live-check session — 2026-09-01 (SPEC-210 dark mode, SPEC-211 feedback, SPEC-209 divider, and the undersized-target register)

Run against deployed prod (`d1kbh4bnvh1je8.cloudfront.net`) signed in as **`agriffith`** in
**Chromium** via the agent's browser, at **1512px** desktop width and **700px** for the drawer
rows. `main` at **`8a3992b4`**, with Deploy App / Deploy SPA image / Deploy Lambdas all green for
that sha, and `api.dataquarry.app/healthz` reporting `8a3992b4` — see the healthz finding below,
because that agreement is itself a correction to `e2e.md`.

**Instruments:** `document.visibilityState` pinned `visible`; the `fetch` wrapper counting `/v1/`
calls by method and path, extended once to capture the feedback **response** body; and a
purpose-built SC 2.5.8 measurer (below) used for every target-size number here.

**The target-size measurer, because every number below depends on it.** It collects each visible,
enabled, on-screen interactive element, then for every target under 24×24 finds the neighbour with
the least slack, applying the two halves of the spacing exception separately: against a neighbour
that is itself ≥24 the test is a 12px radius from the target's centre not reaching that
neighbour's **box**; against a neighbour that is **also** undersized it is centre-to-centre ≥24.
It carries one guard that changed a result: an `elementFromPoint` hit test, so an element lying
**behind** an overlay is not counted as a crowding neighbour. Without it the Colours panel
reported a violation against the `Generated SQL` row underneath it — see *Findings*.

### SPEC-210 — dark mode

| Check | Result |
|---|---|
| `/theme-init.js`, the pre-paint initialiser, **on the deployed origin** | **200**, `Cache-Control: no-cache`, `text/javascript`, 1391 bytes. It is **external** (not inline), render-blocking (no `defer`/`async`), in `<head>`, **script index 0**, ahead of the module script at index 1, and **no `<script>` in the production document has a body**. That last one is the half only a deployed page can prove: an inline initialiser works in dev and is refused by `script-src 'self'`. No console errors and no CSP refusal on load. Storage key is `portal-theme`. |
| A hard-reloaded deep link arrives dark | `/query` reloaded with **Dark** stored: `data-theme="dark"` and `rgb(13, 16, 20)` already applied. |
| **No flash of light before the first paint** | **NOT RUN, and not runnable from this tab** — see *Findings*. |
| The switch and where it lives | Desktop: the half-circle **Change theme** button is in the header, the menu marks the current choice with `aria-checked` on a `menuitemradio`. At **700px signed in** the header button is **gone** and the three choices are in the ☰ drawer, in a `role="group"` labelled *Theme*, marking the current choice with **`aria-pressed="true"`** rather than `aria-checked` — a different but valid pattern, and the current choice is conveyed either way. Signed **out** at 700px the header button is back, as designed. |
| **Monaco keeps its place** (the half `SqlEditor.test.tsx` cannot assert) | **Discharged.** 25 lines typed, cursor put mid-line on line 21, editor scrolled. Switching Dark → Light moved the editor's own class `vs-dark` → `vs`, and: the editor **DOM node is identical** (not re-created), `lines-content` scroll offset **`-146px` → `-146px`**, cursor **top 412px / left 77px** unchanged, rendered text identical, 18 lines both sides. The cursor's computed `visibility` went `visible` → `hidden`, which is **blur, not a lost cursor**: refocusing the edit context *without clicking* restored it at exactly 412px/77px with the scroll still `-146px`. |
| Target size, the three numbers §4.16 step 7 names | Header theme button **28×28**; each drawer option **24.5×(51.9–67.4)**, the half-pixel margin the ledger flagged; and the theme **menu row 175×32** — the one the static sweep is structurally blind to, since it has no height class. All three clear 24. |
| Surfaces in dark | Landing page signed out (indigo call-to-action strip unchanged by the theme, as intended), Files list, Query workspace with Monaco, Data Explorer grid, the Columns drawer, the Send to… and Give feedback dialogs, the ☰ drawer. Nothing washed out. Contrast measured on the dark landing page: secondary **Sign in** 8.5:1 and 15.2:1, white-on-indigo call to action 5.06:1. |

**Not reached:** step 3 (System follows the OS) needs the macOS Appearance toggle flipped by hand;
step 6's shadow judgement is a visual call left to a human eye.

### SPEC-211 — Give feedback, the whole browser half of §4.17

Every row of §4.17's browser table ran and passed.

| Check | Result |
|---|---|
| Placement | **Give feedback** at x=1252, immediately right of **Help for this page** at x=1214. At 700px it is **gone from the header** and present in the ☰ drawer **below** the Theme group. |
| Opening state | No category preselected (`select.value === ""`), message empty, Send **disabled**, and the line *"The page you were on (/query) is included with your message."* Four categories: `bug`, `idea`, `question`, `other`. Textarea `maxLength` is **4000**. |
| The disabled gate | Category chosen + empty message → still disabled. Message of **two spaces** → **still disabled**, so the trim is real. A real message → enabled. |
| Enter inside the message | Inserts a **newline** (2 lines), dialog stays open, and **no `POST /v1/feedback` is issued**. |
| Enter from the focused category select | **Submits.** |
| The request | Exactly **one** `POST /v1/feedback`. Body carries `category`, `message`, `route` and **no username of any kind** — the delegated-actor claim, observed. |
| The response | **200**, body **39 bytes**, exactly one key: `{"submittedAt": "2026-09-01T20:22:52Z"}`, ISO-8601. |
| The toast, and reopening | Dialog closes, toast reads *"Thanks — your feedback has been sent."* Reopened: category reset to none, message **empty**, Send disabled. |
| `route` is where the dialog was **opened** | Opened on `/query`, navigated to `/files` with it open (the dialog survived the nav and kept naming `/query`), then sent: the body carried **`"route": "/query"`**, not `/files`. |

**Three submissions were made today, deliberately, to leave the CLI half a fixture it can read in
one command:** `bug` from `/query`, `idea` opened on `/query` and sent from `/files`, and `other`
from `/files` at **`2026-09-01T20:22:52Z`**. All three carry *"Please ignore"* and name themselves
as live checks. Whoever runs `aws s3 cp "s3://$ADMIN_BUCKET/feedback/2026/09/01.json" -` now has
the three-in-one-object, in-order assertion available without staging anything.

### SPEC-209 — the editor/results divider, the non-drag pointer path

| Check | Result |
|---|---|
| The ▲/▼ buttons step the split, **by click only** | `aria-valuenow` **50 → 55 → 60** on two clicks of *Give the editor more room*, then **60 → 55** on one click of *Give the results more room*. The layout moved with it — the Monaco element measured **298 → 328 → 358 → 328 px** — so this asserts the effect, not the affordance. Range is `aria-valuemin` 16 / `aria-valuemax` 75. |
| Both buttons are at least 24×24 | **Exactly 24×24**, not 24.5 — the absolute `h-[24px] w-[24px]` pin holding, which is what a restyle back to `h-7` would break. |
| The split sticks | Persisted to `sessionStorage` as `s3portal.query.editorSplit.agriffith`, username-scoped. |

### The undersized-target register — the first broad measurement pass

**Two entries are confirmed SC 2.5.8 failures.** Both are pairs of *mutually* undersized targets,
so the verdict does not depend on the contested enclosing-target reading at all.

| Surface | Measured | Verdict |
|---|---|---|
| **Data Explorer column header** | Every column pairs a `Column options` trigger at **18.55 × 21** with a `Resize column` handle at **10.5 × 39**, centres **9.32px** apart where 24 is required — **14.68px short, on all four columns**. The enclosing `<th>` is 347.01 × 40, so it is not itself undersized, but both children are, which is what makes the spacing exception unavailable. | **FAILS** |
| **CalcPanel aggregate checkboxes** | Ten `13 × 13` checkboxes; the aggregate list (*Count, Count distinct, Count nulls, Sum, Average, Minimum, …*) is stacked at exactly **19.5px** vertical pitch, all at the same x. **4.5px short**, nine adjacent pairs. | **FAILS** |
| **Data Explorer tab-strip close** | The ✕ is a **21 × 21** `span`, `tabindex="-1"` by design, **inside** a `role="tab"` measuring 112.52 × 24.5. Its centre lies inside the enclosing target's box, so the exception cannot apply. Confirms the ledger's own reading, now with numbers. | **overlap confirmed** (design decision, deliberately left alone) |
| `OrderFilterDialog` | Eight `13 × 13` checkboxes, **56px** row pitch. | exempt, **+24.41** slack |
| `RowColoursDialog` (Colours) | Five `13 × 13`, worst pair 63.59px apart. | exempt, **+39.59** |
| `GroupingPanel` | Two `13 × 13`. | exempt, **+6.50** |
| `TransformersDialog` | **Zero** undersized targets in its default state. | clear |
| Columns drawer | Move-earlier / move-later **32.16 × 28**, close **28 × 28**. | clear |
| `FileListTable` header + rows | Row select checkboxes **14 × 14** at **42px** vertical pitch; *Select all* **14 × 14**. The binding neighbour turns out to be the **adjacent row's checkbox**, not the enclosing row link — the half that was previously computed rather than measured. | exempt, **+18** (rows), **+34.5** (select all) |
| `SelectionToolbar` | *Check quality / Send to… / Archive / Copy / Move / Delete* all **28px** tall, ≥75 wide. | clear |
| `SendFilesDialog` | Two `14 × 14` radios (*Users* / *Shared spaces*) **69.1px** apart, verified by direct measurement as well as by the sweep. | exempt |
| `Chip` remove ✕ | **Exactly 24 × 24** on both chips, **153.71px** apart on one row. With the 31.75px wrapped-row figure from the earlier session, both axes are now measured. | clear, pin holding |
| Breadcrumb trail (`FileBrowser`) | `agriffith` **47.65 × 18** and `arcb_files` **58.84 × 18**, centres **68.44px** apart on one line. | exempt **horizontally** — see note |

**The breadcrumb entry needs restating rather than deciding.** The trail's buttons are 18px tall,
but on a single line they sit 68.44px apart, so the horizontal axis is not in question at all. The
ledger's 22.56px figure is the **wrapped** trail's line pitch, so only a trail long enough to wrap
puts the Inline-exception judgement in play. This run could not produce one: the deepest path
available was three crumbs.

**Not measured, and why:** `AdvancedCopyDialog` — *Copy…* carries `aria-disabled="true"` without a
cell selection, and an early probe recorded it as "0 undersized" when the dialog had simply never
opened; `StripingControl`, not separately locatable from the Options menu; `Toast` and
`TableActionsMenu`; `RefreshTableDialog` and `TableShareDialog`; `FileListRowMobile`, which needs a
width below 900px on a surface this pass reached only on `/query`.

### Findings

**1. The no-flash check cannot be discharged from the agent's browser tab, and that is a better
answer than "not yet run".** The MCP tab is backgrounded, so Chrome never paints it:
`performance.getEntriesByType('paint')` returns an **empty array** after load, and on one run
reported first-paint at **12,512 ms**. There is no frame sequence to observe and no timing to
compare against, so the perceptual half needs a foreground tab — a human watching, or a screen
recording. Everything *structural* about the initialiser is discharged above; it is only the
"was there a white frame" half that is out of reach. Recorded in `owed.md` with this reason.

**2. `e2e.md`'s healthz note is wrong today, in the direction that causes the false alarm it was
written to prevent.** It says the sha "is the last commit that changed `lambdas/api/`, **not**
HEAD". The last commit touching `lambdas/api/` is `7c9345a6`, but healthz reports **`8a3992b4`**,
which is HEAD — because `8a3992b4` changed `lambdas/control-plane-common/cpcommon/config.py`, a
**layer the API packages**, so the deploy did not skip the function. A reader following the note as
written expects `7c9345a6`, sees `8a3992b4`, and concludes the API is mis-deployed. Corrected in
place: the sha is the last commit that changed the function **or any layer it packages**, which is
usually HEAD.

**3. `resize_window` is not inert — a backgrounded tab reports a stale viewport.** The trap table
says the call "reports success and changes nothing", and mid-session it looked exactly that way:
two resizes reported success while `innerWidth` stayed 1512 and `outerWidth` read **0**. The window
had in fact resized both times; the *tab* could not see it until it was brought to the foreground,
at which point `innerWidth` read **700** and the 900px media query flipped correctly. So sub-900px
checks are reachable after all — this session ran the drawer rows at 700px — and the real rule is
narrower than the trap table's: **assert on `matchMedia`, and do not trust a reading taken while
the tab is backgrounded.** The 400px floor (Chrome's 606px minimum window) is unaffected and still
needs the device toolbar.

**4. An overlay panel makes elements behind it look like crowding neighbours.** Before the hit-test
guard, the Colours panel measured one SC 2.5.8 violation against the `Generated SQL` disclosure row
sitting underneath it. With `elementFromPoint` filtering to what is actually on top, Colours has
**zero** candidates. Any future target-size sweep needs this guard or it will invent violations on
every surface that overlays another.

**5. A panel that never opened is indistinguishable from a clean result.** *Copy…* and *Value*
first reported "0 undersized", which read as a pass; *Copy…* is `aria-disabled` without a
selection and its dialog had never appeared. The Columns drawer reported 0 as well and **was**
genuine — confirmed by a screenshot and by measuring its controls at 28–32px. Take a positive
control before recording any zero.

**6. A stale pre-migration token set is still sitting in `localStorage`.** `localStorage` holds a
complete Cognito set — `idToken`, `accessToken`, `refreshToken`, `clockDrift`, `oauthMetadata`,
`LastAuthUser` — for **`agriffith_three`**, left behind by the 2026-08-27 move to `sessionStorage`.
It is inert: the app reads `sessionStorage`, a fresh tab renders signed out with those keys
present, and this session signed in as `agriffith` alongside them without interference. But nothing
clears them, so a refresh token for another principal persists in browser storage indefinitely.
Raised rather than fixed — the disposition is Andrew's.

### Fixtures created

Three feedback submissions on 2026-09-01 (above), readable only with admin-bucket credentials.
Nothing else was created; the *Send to…* dialog was **cancelled**, not sent, and no file, table or
space was added, moved or deleted.

## Live-check session — 2026-08-30 (SPEC-201 step one: the planes stop verifying tokens, §H.1–H.3)

Run against **`https://portal.dataquarry.app`**, the deployed load balancer, signed in as
**`agriffith`** in **Chromium** at desktop width. `main` at **`ff3a76b6`** — confirmed as the
running build by `api.dataquarry.app/healthz`, which reported that exact sha, so the planes under
test were the ones this spec changed.

**Instruments:** `document.visibilityState` pinned `visible` (a hidden window pauses polling and a
healthy request reads as hung); the browser's own network panel for the enqueue status codes.
Nothing else — every action below was taken through the UI as a user would.

**This is a Chromium pass and therefore corroborates rather than discharges** anything
browser-specific; Safari is the browser in use. Nothing here is browser-specific — the claims are
about what the control planes did — so that is recorded rather than limiting.

### §H.1 — one real request per plane, all eight, each producing its normal notification

Every plane reached its normal terminal state. Quoting the notifications, which are the plane's own
words rather than my summary:

| Plane | What was done | What came back |
|---|---|---|
| file-ops | Copied folder `dq-smoke` into `arcb_live` | *Copied 1 item to "arcb_live".* |
| data-quality | Quality check on `agriffith/dq-smoke` | *Data quality check on "agriffith/dq-smoke" finished — open the report for details.* |
| table-builder (create) | Built `spec201_live` from `agriffith/dq151a` | *Table "spec201_live" is ready to query in "agriffith".* |
| table-builder (refresh) | Refreshed it | *Table "spec201_live" is already up to date - no schema changes were found.* |
| file-send | Sent `beta.csv` to `agriffith_three` | *Sent "beta.csv" (1 file) to user "agriffith_three".* |
| shared-space (create) | Created `spec201_live_check` | *Creating shared workspace…* then *Your shared workspace "spec201_live_check" is ready.* |
| shared-space (delete, owner-only) | Deleted it as cleanup | *Deleting shared workspace…* then *You deleted the shared workspace "spec201_live_check".* |
| table-share | Shared `spec201_live` to `agriffith_three` | *Shared "spec201_live" to user "agriffith_three" as "spec201_live".* |
| archive | Archived `arcb_live/dq-smoke` — the copy made above, so nothing pre-existing was swept | *Archived 4 files (773 B). … Archive id: `7150f49c-e375-44d3-8aa6-e546af9ffa0b`* |

Ten verbs across all eight planes. Each was the first invocation of that function since the deploy,
so each was a **cold start** — which is the half no offline gate can reach: this change removed an
import and two required environment variables from a dozen functions at once, and a shared layer's
import-time failure shows only at cold start.

Two corroborating observations, not asked for and worth keeping: the table built above was
immediately **queryable** (5 rows, 35 B scanned) through the Data Explorer, so the catalog and
Athena paths still work under the changed identity; and `spec201_live_check` appeared in the
database rail, so the shared space was **fully provisioned** — Glue database and Lake Formation
grants — not merely recorded.

### §H.3 — notifications, both branches, in one pass

**The user branch:** marking one notification read from the UI dropped the unread count 4 → 3 and
rewrote the inbox. That path carries the identity block and is refused without one.

**The `create` branch:** every row in the table above. Each was written by a control plane's own
execution role, with a body `username`, **no actor and no token**. This is the branch a
`trusted_actor` hoisted above `_resolve_username`'s test silently kills, and the failure would be
invisible — the producers notify best-effort, so the work completes and the user is simply never
told. Both branches in one pass, which is the only way either is evidence.

### §H.2 — partially run, and the half that ran is the one that mattered most

**Sending to a user that does not exist** returned *Couldn't send to user "nosuchuser_spec201":
there is no user with that name.*

That is the recipient-existence check — `cpcommon.cognito.user_exists` → `admin_get_user` — and it
is the riskiest line in this change. `COGNITO_USER_POOL_ID` stopped being a fleet-wide required
variable here and became a **lazy `config.require`** read on the three planes that resolve a user;
a lazily-required variable that is missing raises **mid-request**, not at cold start, so a wrong
Terraform mapping would have surfaced exactly here and nowhere earlier. It came back as a clean,
correctly-worded refusal naming the user.

**The rest of §H.2 is OWED**: a non-member's space, a foreign prefix and an out-of-root key all
need a **second account**, since the point is that the API writes a genuine verified
`identity.actor` for somebody who is not authorized, and a hand-crafted body cannot reach the queue.

### Not run

§H.4 (the staged pre-cutover message) and §H.5 (`assurance` refused live with an `interactive`
neighbour) both hand-enqueue onto a request queue. After SPEC-200 only the **API's execution role**
holds `sqs:SendMessage` there — a laptop identity has no grant, which is the isolation working —
so both stay owed with the recipe recorded.

### §H.6 — after step two, run the same way

`main` at **`73812e06`**, confirmed by `healthz` before starting, so the API under test was the one
that had stopped sending a token. Four verbs, chosen to cover **both** envelope shapes, because the
field that disappeared was not the same on every plane:

| Plane | Old token field | What came back |
|---|---|---|
| file-ops | flat `actor` | *Copied 1 item to "test_folder".* |
| file-send | flat `actor` | *Couldn't send to user "agriffith_three": they already have something called "header-only.csv" from you, and nothing was overwritten.* |
| table-builder (refresh) | `idToken` | *Table "spec201_live" is already up to date - no schema changes were found.* |
| notifications (mark read) | `idToken` | Unread count 15 → 14, inbox rewritten |

The file-send row is a **refusal, and the right one** — the per-recipient collision guard, reached
and worded correctly on an envelope carrying no token at all. A plane that had still been reading
one would not have got that far.

Both notification branches again: the mark-read above is the user path, and every other row's
notification is the `create` path, written by an execution role.

**Not repeated after step two:** shared-space, data-quality, table-share and archive. Each ran on
step one and each takes the identical `trusted_actor` call; what step two changed is the message
BODY, and that is shared across all eight, so the four above cover both shapes it comes in. Saying
this plainly rather than implying all eight ran twice.

### §H.7 — NOT RUN

The exposure check needs a message to actually dead-letter, which needs the Pipe's *delivery* to
fail rather than the execution — see the amended §H.4. Owed.

---

## Live-check session — 2026-08-27 (the auth boundary and the identity layer, §D and §E)

Run against **`https://api.dataquarry.app`**, `main` at `951e6a8a`, signed in as **`agriffith_three`**
in **Chrome** (desktop). Instruments: `curl` from the laptop, in-page `fetch` from the deployed
CloudFront origin, and the log objects under `logs/service=api/year=2026/month=08/day=27/`.

**Why now rather than at SPEC-202.** SPEC-197 FR-014 deletes both probe routes, and conditions each
deletion on the verification that route exists for having been run. The arc's 2026-08-27 decision had
moved all live verification to SPEC-202 — which would have deleted the only instruments that can
observe the boundary and the isolation model before either was ever observed. Settled with Andrew:
run §D and §E first, then delete. **This section is what made that deletion legitimate.**

### Passed

| Check | Result |
|---|---|
| §E.0 — the claims are in the token | `cognito:username` and `custom:shared_space_1` both present; RS256, `kid` present, issuer `…/us-east-1_zOlWYrE9K` |
| §D.1 — the happy path | `200 {"username": "agriffith_three"}` — the username, not the `sub` |
| §D.2 — four refusals | no-token / access-token / flipped-payload / foreign-key all **401**, all four bodies `sha256 aebffec4…9261` (one digest, four times), `www-authenticate: Bearer` on all four, body exactly `{"error": "unauthorized", "code": "SessionExpired"}`. A wrong *scheme* (`Basic`) answers identically. |
| §E.1 / §E.2 (username half) / §E.3 | `GET /_identity/self` → `{"username": "agriffith_three", "spaceCount": 1, "ownPrefixListable": true, "foreignPrefixListable": false}` |
| §E.7 — a real `env` and build sha | `env: "prod"` on all 44 of the day's records; `version` a real commit sha, never `0.0.0` |
| The field rule, on real traffic | Across the whole day's records: zero emails, zero `@`, zero `Bearer`, zero `eyJ` |
| CORS negative control | `Origin: https://example.invalid` → **no** `access-control-allow-origin`. Both real origins are echoed, so nothing has been narrowed. |

`ownPrefixListable: true` is the observation that proves the `username` tag was stamped: the portal
role grants `s3:ListBucket` **only** under `"s3:prefix": ["${aws:PrincipalTag/username}/", …]`, so it
is unreachable without it. `foreignPrefixListable: false` is AWS refusing — the isolation model
working, and the negative control that a probe asserting only its own prefix would pass with the
model deleted.

### Failed — and it is fixed in SPEC-197

**Every bearer-carrying request from a browser was impossible.** `infra/modules/api/apigateway.tf`
declares only `$default`, which matches `OPTIONS`; AWS auto-answers a preflight only when no route
matches, so preflights reached the Lambda and were refused deny-by-default:

```
OPTIONS /_auth/whoami  →  401  {"error": "unauthorized", "code": "SessionExpired"}
```

Browsers require a 2xx preflight, so every such `fetch` failed as an opaque `TypeError`. Isolated
from the page: `fetch(API + '/healthz')` (simple, no preflight) → **200**; the same URL with an
`authorization` header → **threw**. So CSP, DNS, TLS and the origin echo were all fine and only the
preflight was wrong — which is exactly the failure mode that reads to a user as "the API is down".

Invisible to every offline test and to `curl`. **SPEC-197 answers `OPTIONS` in the router, before
authentication**, and a browser is the only instrument that can confirm it — recorded as owed below.

### Still owed after this session

- **D.3 — a genuinely expired token.** Needs the app client's ID-token validity temporarily cut to
  its 5-minute minimum and then restored; not run.
- **D.5 in Safari.** Chrome only, and Safari is the browser in use.
- **D.6 — the token-segment scrub against a real refusal.** The flipped-payload call was made; the
  records for that window had not yet been swept when the session ended.
- **§E.2's slot half.** `agriffith_three` belongs to **one** shared space, and `spaceCount` is
  counted from the token's claims — it reads the same with every slot tag dropped. → SPEC-198.
- **§E.4, §E.5, §E.8, §E.9** — untouched by this session.
- **The preflight fix, live.** Only a browser can confirm it.

---

## Live-check session — 2026-08-27 (the SPA container, SPEC-194)

Run against **`https://portal.dataquarry.app`**, the deployed load balancer, immediately after
`Deploy SPA image` reported `desired=1 running=1 rollout=COMPLETED` on the revision it registered
(`main` at `783275d1`, task definition `dat-prod-spa:6`, 20 configuration keys carried).

**The instrument was `curl`, not a browser, and that is the whole limit of this session.** Every
assertion below is about bytes on the wire. **Nothing here discharges a rendering, a script
execution or a sign-in** — which is exactly why §C.1 (fresh sign-in from a private window), §C.2
(the CSP's negative control) and §C.3 (Safari) remain owed rather than being marked off by it.

**Everything checked passed. Nothing was found broken.**

| What | Result |
|---|---|
| The full security header set on **five** response classes — the shell, a deep link, a hashed asset, the honest 404 and `/config.json` | CSP, HSTS, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP and CORP present on every one. **This is the ALB assertion**: nothing between the container and the client adds or strips a header |
| HSTS | `max-age=31536000; includeSubDomains`, **no `preload`** |
| `Cross-Origin-Embedder-Policy` | absent on every response, by decision |
| `Server` | exactly `nginx`, no version |
| Cache classes | `/` and a deep link `no-cache`; `/assets/<hashed>` `public, max-age=31536000, immutable`; `/config.json` and `/healthz` `no-store` |
| `GET /config.json` | 200 / `application/json` / `no-store`, **21 keys** (`version` + the 20 classified), `version: 1` |
| `GET /healthz` | 200 / `text/plain`, body exactly `ok` |
| `GET /assets/index-DEADBEEF.js` | **404**, `application/javascript`, body `not found` — the honest 404, not the shell |
| A hashed asset with `Accept-Encoding: gzip` | `content-encoding: gzip` + `vary: Accept-Encoding` |
| The same asset with `Accept-Encoding: br` | **no** `content-encoding` — the accepted brotli residual |
| The served `connect-src` | all **ten** terms, including the two whose loss a signed-in tester cannot see: the `cognito-idp` endpoint and the Hosted UI domain |

**Not exercised, and not to be read as passing:** any file operation. Bucket CORS admits the
CloudFront origin and localhost only, so the browser's direct S3 calls fail preflight from this
origin until the presigned-bytes spec widens it. Expected, and stated so it is not diagnosed as a
container defect.

## Live-check session — 2026-08-24 (runtime configuration, SPEC-192)

Run against deployed prod (`d1kbh4bnvh1je8.cloudfront.net`) in **Chromium via the agent's browser
tooling**, not Safari and not a user's profile — so this corroborates rendering and cannot discharge
it. Two loads: one after the document was published and read nobody (`main` at `1af1f8bb`), one after
the switchover (`main` at `9a3568de`).

**Everything checked passed.** Nothing was found broken.

### What was run

| Check | Result |
|---|---|
| `GET /config.json` headers | **200**, `content-type: application/json`, `cache-control: no-store`, `x-cache: Miss from cloudfront`, `server: CloudFront` (the S3 banner stripped) |
| Security headers on that path | CSP, HSTS and `x-content-type-options` all present — the response-headers policy really is attached to the new cache behaviour, which is per-behaviour and not inherited |
| Document contents | `version: 1`, all 20 classified keys present, only `apiBaseUrl` empty (correct — no API yet) |
| Edge caching | A second request is **still** `x-cache: Miss from cloudfront`, so `Managed-CachingDisabled` is live |
| After the switchover: fetch count | **Exactly one** `config.json` request per page load — `performance.getEntriesByType('resource')`, 77 ms in, 54 ms duration. The two entries in the network log were two page loads, not a double fetch |
| After the switchover: console | **Zero** errors |
| After the switchover: the values are in USE | **No configuration alert and zero `[role=alert]` nodes.** That is the observable: had the document's four Cognito values not reached `Amplify.configure()`, `isAmplifyConfigured()` would be false and `Header` would render one |
| App shell | `/` returns 200 `text/html`; the landing page renders in full |

### Not run, and still owed

The staged **hard-failure** and **unparseable** paths, the **promotion** check, and a **fresh sign-in
from a private window** — the first three need a deliberately broken or changed document published to
the bucket, the fourth needs a real Hosted UI round trip. All four were written up as the arc
script's §A.1–A.4 (deleted when Arc B closed — see the note at the top of [`owed.md`](owed.md) §1)
and are carried in [`owed.md`](owed.md).

---

## Live-check session — 2026-08-16 (Data Explorer §2 + copy/export, SPEC-179/183, partitioned refresh, saved queries)

Run against deployed prod (`d1kbh4bnvh1je8.cloudfront.net`, `main` at `94c892b`) as
`agriffith_three`, in **Chrome at 1512×786**. Safari waived for behavioural checks by the
2026-08-15 user decision, now recorded at `e2e.md` §4.15; the CSS list is untouched here.

**Nothing was found broken.** Every check below passed. The two findings at the foot are about the
*instrument*, not the app — and one of them would have let a future session record a pass it never
ran.

### The upload constraint is gone, and it is what unblocked most of this

The script said *"Andrew has to do the upload"* because a laptop IAM user cannot write
`dat-prod-user-space`. That is still true of the CLI, but it is **not** a limit on a live-check
session: the Chrome extension's `file_upload` puts a local file straight into the portal's own
`<input type=file>`, so the upload goes through the **portal role** like any other. Everything
below that needed a fixture — the 150-row table, the partitioned table, the added-column file —
was uploaded that way.

### Data Explorer (`e2e.md`)

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
outside. **Filtered but not ordered** — step 1 asks for both, and the 24-byte delta is the proof it
was the `WHERE` alone. What step 5 exists to test is the cross-bucket destination, which is
unaffected; the ordering half is covered by SPEC-183's round-trip row, discharged 2026-08-15.

Two incidentals from that: the Save dialog **pre-fills the last name used** and the field is not
selected on focus, so a straight `type` appends (this produced
`explorer-shared-destexplorer-shared-filtered.sql`, renamed afterwards) — and the rename itself
confirms the SPEC-173 pairing, that a `.sql` file **inside** `saved_queries/` is ordinary while the
folder is not.

#### SPEC-185 copy and export

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

#### SPEC-185 Help

PASS, all three steps. The **Data Explorer** section carries **five** guides. The filtering guide's
callout reads *"Careful. Every apply runs a real query against Athena and scans data, which is what
it costs."* Nothing in the section mentions a chart, a graph, cell editing, named filters or a
References panel, and the save guide states plainly that a saved exploration opens in the Query tab
as SQL rather than back in the Explorer.

### Table Builder — the partitioned refresh variant (`e2e.md`)

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

### Saved queries — the client-side refusal (`e2e.md` §4.7), the owed SHARED half

PASS, byte-exact, with its control. In `livecheck_186` (whose `saved_queries/` folder the SPEC-183
step-5 save had just created):

- Delete — `aria-disabled="true"`, `disabled` **false**, `tabIndex 0`,
  `Saved queries live in this folder, so it can’t be deleted.`
- Move — same, `Saved queries live in this folder, so it can’t be moved or renamed.`
- Clicking Delete opened **zero** dialogs and **zero** alertdialogs, and — with `window.fetch`
  patched to record every request by method and path — issued **zero requests of any kind**. That
  is step 3's third clause, *"no request is sent"*, observed for the shared case directly rather
  than inherited. **The 2026-08-14 trace still stands for what it established** — that the portal
  issues zero `DeleteObject` against the marker, which is the premise `e2e.md` is
  built on. What it cannot carry is the **FR-002 affordance**, because it watched the older
  behaviour where the refusal arrived only after the confirm.
- **Control:** an ordinary `marker_control` folder beside it showed both controls with no
  `aria-disabled` and no reason, its confirm opened (*"…and everything inside it? … This can't be
  undone."*), and it deleted cleanly.

The 2026-08-15 personal half stands; check 2 (the bucket-policy Deny, CLI-only) is still owed.

### Findings — both about the instrument

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

### Still owed after this session

- The **400px** pass and the **Safari** CSS list (`e2e.md`).
- SPEC-179's shared-space pass as a **non-owner member**, and SPEC-186 FR-008's
  add → acknowledge → roster re-run — both need a second account.
- `owed.md` §2.1 (the `DO_NOT_DELETE.txt` Deny, CLI + portal-role credentials).
- SPEC-157's refresh lock, SPEC-149's `Description`/comment preservation read-back (needs the
  verification role, deliberately not created), and `SaveQueryDialog`'s "nowhere to save" width.
- The whole **archive/restore** arc (`e2e.md`). Deliberately not attempted here:
  archiving removes files from a space and a restore is a 3–5 hour **billed, uncancellable**
  Glacier retrieval, which is not a call to make unattended.

### Fixtures created (deletable once the remaining checks are run)

`agriffith_three`: `explorer150/` + table `explorer150`, view `explorer150_nulls`, `partfix/`
(`year=2025/`, `year=2026/`) + table `partfix`, `explorer-export.csv`,
`saved_queries/workspace-direction.sql`.
`livecheck_186`: `explorer-export-shared.csv`, `saved_queries/explorer-shared-dest.sql` and
`saved_queries/explorer-shared-filtered.sql`.

---

## Live-check session — 2026-08-15 (Data Explorer arc, SPEC-186 dialogs, saved queries)

Run against deployed prod (`d1kbh4bnvh1je8.cloudfront.net`, `main` at `88caf54`) as
`agriffith_three`, in **Chrome at 1400×730**. Safari waived by user decision — see the amendment at
`e2e.md` §4.15.

> **The date.** The session ran on the evening of **2026-08-14 US Eastern**, which is
> **2026-08-15 UTC**. Everything is dated 2026-08-15 here and in the script, matching the UTC
> timestamps on the deploys and log records cited below. Where the script says a thing was
> "measured 2026-08-15", that is this session.

### SPEC-186 FR-005 — `env` and `version` on log records

Read from `s3://dat-prod-athena-admin/logs/service={s}/…/data.jsonl` with the laptop IAM identity
(the admin bucket is readable; the user-space and archive buckets are not).

- **809 post-deploy records** (timestamp > `2026-08-14T20:50Z`) across **four** services —
  `dlq-drain`, `observability`, `notifications`, `auth` — with **zero** carrying an empty `env`,
  an empty `version`, or `version: "0.0.0"`.
- `env` is `"prod"`; `version` is `88caf54e0571580c5ffc9647fef4331855983708`, **equal to HEAD on
  `main`** at the time of the run — so the stamp names the app commit, not a stale or infra one.
- **The boundary is the deploy.** In `logs/service=observability/…/day=14/data.jsonl` the latest
  `version: "0.0.0"` record is `18:44:35Z` and the earliest real-sha record is `18:54:34Z` — the
  SPEC-186 Deploy Lambdas run. Shas observed in order: `0.0.0` → `7d59ca10…` (SPEC-186's own merge)
  → `88caf54e…`.
- CloudTrail on `dat-prod-archive-audit` reports **`IsLogging: true`**, which is the precondition
  the archive script's negative assertion rests on.

**Scope limit, stated because the count invites over-reading:** only those four services have
emitted since the deploy. The other five (`table-builder`, `table-share`, `shared-space`,
`data-quality`, `user-directory`) are idle, so the mechanism is proven and they are **unobserved**,
not verified. Every record in their most recent partitions predates the deploy and legitimately
lacks the fields.

### How executions were counted

**The network panel could not carry these assertions.** `read_network_requests` reports URL,
method and status only — every Athena call is a `POST` to the same host, so it cannot separate
`StartQueryExecution` from `GetQueryExecution`/`GetQueryResults`. Executions were counted by
patching `window.fetch` and reading the **`x-amz-target`** header, with request bodies captured via
`Request.clone().text()` to compare `QueryString` against the disclosed SQL.

**Two instrument traps, both hit and both worth knowing:**

- `read_network_requests` **silently stops capturing after a page navigation**. It reported zero
  Athena *and* zero `cloudfront` requests for a freshly loaded page. A negative from it is
  worthless without a positive control — the same shape as the archive script's trail-is-off
  warning. Every negative below was taken with a positive control in the same window.
- A patched `window.fetch` **does not survive a full page load**. Client-side nav (nav-tab clicks,
  `pushState` + `popstate`) preserves it; `navigate` does not.

### Data Explorer (`e2e.md`)

Fixture `explorer_fixture`: 30 rows, columns `id/region/owner/qty` all **string** (CSV ⇒ all-string
as decided), three `O'Brien` rows, one empty `qty` rendering as *(empty)*.

| Check | Executions | Result |
|---|---|---|
| Open the table | 1 | PASS |
| §1 apply is a new execution + new figure | 1 | PASS — 568 B → 1.1 KB, rows 1–7 |
| §3 cache hit — clear the filter | **0** | PASS — "Loaded from an earlier run in this tab — nothing more scanned", total held |
| §3 cache hit — re-apply the same filter | **0** | PASS — total held |
| §4 `O'Brien` against the real engine | 1 | PASS — rows 1–3, `WHERE "owner" = 'O''Brien'` |
| §5 failed apply | 1 (+retry) | PASS — mapped banner, previous rows kept, toolbar kept |
| §5 history Back | **0** | PASS |
| §5 Forward onto the failed step | **0** | PASS — exact wording + *Run it anyway* |
| SPEC-182 grouping | 1 | PASS — rows 1–4; south 8 / west 7 / east 8 / north 7 |
| SPEC-182 step 4 byte-identity | — | PASS — `identical: true` |
| SPEC-182 percentage absent from SQL, header says `(THIS PAGE)` | — | PASS |
| SPEC-182 Calc | **0** | PASS — across 3 function toggles and 2 reselections |
| SPEC-182 step 6 leaving grouping drops the sort | 1 | PASS — no `ORDER BY "count_all"` |
| SPEC-183 save | 1 PUT | PASS — after a HEAD on the exact key; no sidecar |
| SPEC-183 round trip | — | PASS — reopens with filters + ORDER BY, not a bare `SELECT *` |
| SPEC-179 deep-link refusal | **0** Glue, **0** Athena | PASS — only one S3 read of the user's own space list |

The grouped counts match the fixture exactly, which is what makes the GROUP BY result meaningful
rather than merely present.

### SPEC-186 FR-007 — dialog widths

Root font-size is **14px**, so `max-w-md` (28rem) is **392px** — a checker expecting 448px would
read every pass as a fail. All measured at a 1400px viewport with `max-w-md` present rather than
lost to `w-full`:

CreateFolderDialog, RestoreArchiveDialog, RenameDialog, CreateSharedConnectionDialog,
SaveQueryDialog (normal), CreateViewDialog, FilterValueDialog, AddMembersDialog — **8 of 9 at
392px, PASS**.

**Owed:** `SaveQueryDialog`'s second instance (the "There's nowhere to save this query" state),
which needs the personal space to be unavailable and cannot be staged from the UI.

**Beware:** `Drawer` also carries `role="dialog"`. Measuring `querySelector('[role="dialog"]')`
with a drawer open returns the **drawer** (440px, no `max-w-md`), not the modal. Select by title.

**These are RENDERING assertions, so Chrome corroborates them and Safari is still owed** — the
waiver at the head of the script covers behaviour, and a resolved `max-width` and a clipped listbox
are layout. They are recorded here as measured-in-Chrome, not as discharging the Safari pass.

#### The narrow pass was at 606px, and it is NOT the 400px pass

**Chrome's minimum window width on macOS is 606px**, and the Claude-in-Chrome extension refuses
page-zoom shortcuts (`page zoom keyboard shortcuts are not supported`), so neither route reaches
400px. What was actually observed at **606×657**:

- The below-`tablet` layout is genuinely active — hamburger nav, and the file toolbar
  (Restore Archived Data / New folder / Upload) reflowed to a stacked bar at the foot.
- `CreateFolderDialog`: **392px** wide, centred at left 107 / right 499, `fitsHoriz: true`, and
  `document.documentElement.scrollWidth === clientWidth` (no horizontal page scroll).

Nothing else on the script's CSS list was exercised at this width — no sticky pinned column, no
header-menu clipping, no sheet-vs-panel, no Calc/Grouping stacking, no toolbar wrap, no colour-rule
row wrap, no band boundary, no truncating-cell anchor, no header-drag. **The 400px pass is owed in
full.** Use DevTools device toolbar (⌘⇧M), which changes the viewport the page actually sees.

### SPEC-186 FR-003 — suggestion listbox containment

| Surface | `listbox.bottom` vs `dialog.bottom` | Cap | Result |
|---|---|---|---|
| Add members | 527 = 527, overhang **0px** | 113px | PASS |
| Share table / **Users** | −61px (headroom) | 114.25px | PASS |
| Share table / **Shared spaces** | −135px (headroom) | 114.25px | PASS |

Every cap is a measurement, not the old fixed `max-h-60` (240px); all three scroll, and arrow-key
navigation scrolls the active option into view (`scrollTop` 0 → 81.5) while containment holds.

**Do not misread the visible count.** Three of eight options are visible — the same number the
SPEC-158 failure reported — but the cause is now the opposite: then it overhung the panel by 97px,
now it is capped to fit. The Shared-spaces list offered exactly one option (`livecheck_186`, the
user's own space), which is SPEC-158's "no published directory of spaces" working.

### Saved queries — the client-side refusal (`e2e.md` §4.7), personal half

PASS, byte-exact. Delete and Move both `aria-disabled="true"` with `disabled` **false** and
`tabIndex 0`, so the reason is in the tab order:

- Delete — `Saved queries live in this folder, so it can’t be deleted.`
- Move — `Saved queries live in this folder, so it can’t be moved or renamed.`

Clicking Delete opened **zero** dialogs and **zero** alertdialogs; the folder survived. The control
passed too: an ordinary folder shows both controls enabled with no reason, so the refusal is
specific rather than a generic failure.

**Owed:** the shared half, and check 2 (the bucket-policy Deny, CLI-only).

### Findings

1. **`EXPLORATION_PAGE_SIZE` is 100, so the script's ">25 rows" fixture cannot page.** Both pagers
   render disabled at 30 rows and §2 is unrunnable. Script corrected to ask for 150.
2. **The suspended state is per-mount.** Leaving `/explore` and returning loses the `useRef` set in
   `useExplorationQuery`, so the failed statement is re-submitted and the error banner shows
   instead of "Nothing has been run". **Accepted, not fixed** (user decision) — the promise is
   scoped to history navigation, and persisting the set would add a second writer to the tab's
   `sessionStorage` key that SPEC-181 deliberately kept to one.

   **The "nothing is billed" half of that rationale is narrower than it looks, and the difference
   matters.** For the case staged here — `qty >>> 5`, a parse error — Athena rejects the statement
   **at `StartQueryExecution`**, so no execution is created and nothing is billed; the retry is
   itself the proof it was rejected at submit. But `DataExplorerWorkspace` calls `noteFailure` on
   **any** `exploration.error`, which includes `useExploration`'s `executionFailure` — a **FAILED
   or CANCELLED poll**. Those *did* create an execution, and `useExploration.ts`'s own comment
   records that a CANCELLED query **is** billed for what it scanned before it stopped. SPEC-178's
   Trino type-error case (`WHERE "qty" > '5'` against a bigint) is exactly that shape. So a
   re-submit after a route change is free for the syntax-error class and **not free in general**.
   That does not change the decision — the re-run happens once and the user is watching — but a
   future revisit should weigh the post-submit class, not the parse-error one.
3. **A failing apply issues TWO `StartQueryExecution` calls ~1.1 s apart.** This is `retry: 1` in
   `lib/queryClient.ts`, **not** a double-subscribe. Established by applying once with **no**
   navigation and watching it stop at exactly two and stay there for 20 s — an initial diagnosis
   blaming two subscribers was wrong and was withdrawn. It also proves Athena rejects this SQL at
   submit rather than failing it later, so no execution is created.
4. **Create view refuses through a toast**, not `Button.disabledReason` — the button reports
   `aria-disabled: null` and is genuinely enabled. Worth knowing when auditing FR-002 affordances.
   `Button.disabledReason` *is* in use on the file toolbar and the Explorer toolbar
   ("There are no filters, expressions, sorts or grouping to clear.", "Select some cells first.").

### Also created during this session

`livecheck_186` (shared space, owner `agriffith_three`) and `agriffith_three.explorer_fixture`
(table over `test_fixture_one/`). Both are live-check fixtures and can be deleted once the arc's
remaining checks are run.

---

## Live-check session — 2026-08-14

One session against the deployed portal (`d1kbh4bnvh1je8.cloudfront.net`), driven from the browser
as a **fresh account, `agriffith_three`**, signed up during the session. A clean account was chosen
deliberately: deterministic fixtures, and no risk to existing data.

`CLAUDE.md` carries one line per outcome and points here. This file is the evidence.

---

### Environment and what it can reach

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

### Discharged

#### SPEC-137 Phase 4 — the auth spans

Signing up `agriffith_three` succeeded, which alone rules out the cold-start `ModuleNotFoundError`:
on `pre-signup` that failure blocks sign-up outright. `logs/service=auth/` carried both spans at
`status: "ok"`:

- `pre-signup` — `span.start` + `span.end`, 0.149 ms
- `post-confirmation` — `span.start` + `user provisioned` (`username: agriffith_three`,
  `database: agriffith_three`) + `span.end`, 1381.8 ms

Field rule holds: username and database only, no token, no email.
**Defect found:** every record carries `"version": "0.0.0"` and `"env": ""` → SPEC-186 FR-005.

#### SPEC-146 — the username directory read

Typing one character in **Add members** returned **8 suggestions** (`adamparker`, `admin`,
`agriffith`, `akinwale14`, `denapolia`, `malathi`, `mrag`, `tencalade27`). Suggestions only render
if the portal role's SigV4 `GetObject` on `_directory/usernames.json` succeeded, so seeing them *is*
the end-to-end read confirmation.

The minutes-old `agriffith_three` was correctly **absent** — the document is built daily from S3
prefixes. That is the design, not a miss.

#### SPEC-175 — the cross-bucket `PutObject`

Saving a query into shared space `livecheck_0814a` produced, in order:

```
HEAD  dat-prod-shared-space/livecheck_0814a/saved_queries/DO_NOT_DELETE.txt        → 404
PUT   dat-prod-shared-space/livecheck_0814a/saved_queries/DO_NOT_DELETE.txt        → 200
HEAD  dat-prod-shared-space/livecheck_0814a/saved_queries/livecheck shared save.sql → 404
PUT   dat-prod-shared-space/livecheck_0814a/saved_queries/livecheck shared save.sql → 200
```

Two design points confirmed live beyond the write itself: the folder marker is planted **on demand**,
and the name-collision check is a **HEAD on the exact key**, not a scan of the loaded array.

#### The refresh arc — FR-010, end to end

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

#### The casing premise — now demonstrated, not corroborated

Uploaded `part00.csv` with headers `ID,Region,Amount` so it became the sample, against a stored
schema of `id,region,amount`.

- Refresh reported **`already up to date - no schema changes were found`** → `diff-schema` folds
  case, rather than seeing 3 added + 3 removed
- The rail still reads `id, region, amount` → **nothing was silently re-cased**

That is the mutation CLAUDE.md warned would be reported by no test and no notification. It did not
occur. Still unobserved: `get-table-versions` (that no new version was written), which needs FR-004.

#### SPEC-142 — the disagreeing-files check

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

### Half done

#### SPEC-125 — shared-space smoke run

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

#### SPEC-175 — opening a colleague's query

As `agriffith`, the Saved queries panel's space selector listed `livecheck_0814a`; the colleague's
query appeared as *"livecheck shared save · 44 min ago · 85 B"* with Open and Delete. Opening it
fetched `GET dat-prod-shared-space/livecheck_0814a/saved_queries/livecheck shared save.sql → 200`
and opened a tab named for the query with the saved body. **Discharged.**

Side observation: merely opening the panel planted the reader's own marker —
`agriffith/saved_queries/DO_NOT_DELETE.txt` 404 → `PutObject` 200 — so a read path creates the
folder too, not only a save.

#### SPEC-158 — the suggestion pass

**Passes:** 7 chips tokenize on Enter from comma-separated input; the confirm control stays inside
the dialog, in the viewport, and hit-testable. Backspace deliberately does not remove chips.

**Fails:** the list does *not* position inside the panel. Listbox spans y 472→682; dialog ends at
585 — a **97px overhang** clipped by the dialog's `overflow: auto`, leaving **3 of 8** options
visible (still reachable via the listbox's internal scroll: 259px of content in a 208px box).
→ SPEC-186 FR-003. Re-measure after FR-007, since this was measured inside an oversized dialog.

**Owed:** the **Share table** dialog under **both share kinds**, the **400px** pass, and the whole
thing in **Safari** — a Chromium run corroborates but cannot discharge a Safari pass.

---

### Unrunnable as written — the most valuable class

#### SPEC-173's marker check

Asks: delete `{root}saved_queries/DO_NOT_DELETE.txt` through the portal, confirm `AccessDenied`.
**The portal never issues that call.** The marker is hidden **by basename** so it cannot be selected,
and the folder delete is refused **client-side** by `UNDELETABLE_ROOT_FOLDERS` before any S3 request.
A network trace of both attempts shows **zero** `DeleteObject` requests against the marker.

Verified instead — the client-side layer, personal **and** shared:

> "Deleted 0 items. Could not delete 1: **saved_queries — Saved queries live in this folder, so it
> can't be deleted.**"

with the folder surviving, and an ordinary empty folder (`refresh_step2`) deleting cleanly beside it
as the control. The bucket-policy Deny — the second layer — remains unverified. → SPEC-186 FR-001.

#### SPEC-157's concurrency check

Not performable from the UI, and now measured. Two submits **2 seconds apart** — two tabs pre-armed
via the `/query?refreshTable=` deep link, which is the floor two browser clicks allow — **both
returned independently** with no `refresh_already_running`. An earlier pair 9 s apart behaved the
same. A small table's refresh completes inside that window, so the lock is never contended and the
check can neither pass nor fail this way. → SPEC-186 FR-006.

#### The archive arc's `head-object` assertions

SPEC-170's negative assertion (no `Restore` header after a `destination_occupied` refusal), SPEC-169's
`StorageClass: GLACIER` read-back and its empty-archive-prefix check all need `head-object` on
`dat-prod-archive`. No principal can reach it, and with no CloudTrail there is no independent record
of whether `RestoreObject` was called. **Do not proxy from the UI** — the script itself says a
refusal that had already started retrieval looks identical there, and being wrong costs 3–5 billed,
uncancellable hours. → SPEC-186 FR-004.

#### SPEC-149 / SPEC-153's catalog read-backs

`get-database` returns `Insufficient Lake Formation permission(s): Required Describe` — the same wall
that forced 153's docs-transcribed stand-in. → SPEC-186 FR-004.

---

### Defects found

| # | Finding | Where |
|---|---|---|
| 1 | **Nine dialogs render at full viewport width.** `New folder` and `New shared connection` both measured **1372px in a 1400px viewport, `max-width: none`**, against `Create table`'s correct 448px/`max-w-lg`. Root cause: `cx()` returns `''`, `FormDialog` passes it to `Modal`, and `Modal`'s `className ?? 'max-w-md'` does not fall back on an empty string | SPEC-186 FR-007 |
| 2 | Suggestion listbox overhangs its dialog by 97px; 3 of 8 options visible | SPEC-186 FR-003 |
| 3 | `saved_queries` shows Delete/Move **enabled**, raises "This can't be undone", then refuses — the most alarming confirm in the app for an action that cannot happen | SPEC-186 FR-002 |
| 4 | Refresh dialog's submit is natively `disabled` with no reason, where SPEC-172 set `Button.disabledReason` as the fleet-wide pattern | SPEC-186 FR-002 |
| 5 | `version: "0.0.0"` and `env: ""` on every structured log record | SPEC-186 FR-005 |
| 6 | The members roster shows `Pending` — with *"hasn't signed in yet"* — for a member the same page shows as `Active`; Refresh does not reconcile | SPEC-186 FR-008 |
| 7 | Recipient chips are three copied implementations, already drifted: remove target is **20×20** in Share table and Send files against **24×24** in Add members (WCAG 2.2 SC 2.5.8 minimum). Chip width is unbounded — a 63-char username extrapolates to ~610px, wider than its 448px dialog | SPEC-186 FR-009 |


## 2026-08-30 — the registry list grant, verified against the deployed roles

Run from a laptop against production IAM, read-only, immediately after #555's
`Deploy Infrastructure` went green on `main`. This is the **paired-simulation** row that
`owed.md` carried, now discharged; the other two rows it added remain owed.

`s3:ListBucket` on `arn:aws:s3:::dat-prod-athena-admin`, per deployed execution role, each
`allowed` paired with an `implicitDeny` control — an `allowed` alone proves the grant works and
never that it stayed scoped:

| Role | `s3:prefix=shared-spaces/demo.json` | control, `s3:prefix=logs/service=api/` |
|---|---|---|
| `dat-prod-archive-execution-role` | allowed | implicitDeny |
| `dat-prod-data-quality-execution-role` | allowed | implicitDeny |
| `dat-prod-file-ops-execution-role` | allowed | implicitDeny |
| `dat-prod-file-send-execution-role` | allowed | implicitDeny |
| `dat-prod-table-builder-execution-role` | allowed | implicitDeny |
| `dat-prod-table-share-execution-role` | allowed | implicitDeny |

And `dat-portal-user-role` on `arn:aws:s3:::dat-prod-user-space`, simulated with
`aws:PrincipalTag/username=alice`: `_directory/usernames.json` allowed,
`_config/feature-flags.json` allowed, `bob/docs/a.txt` **implicitDeny** — the isolation control,
which is the assertion that matters, since the change added a second list grant beside the one
carrying that isolation.

**What this does NOT settle.** A simulate is not a request. It says IAM would allow the list; it
does not show `cpcommon.registry.load` returning None, and it cannot, because the thing being
fixed is what S3 chooses to *say* on a `GetObject`. The behavioural check — a real request naming
an unregistered space ending at `unknown_space` rather than a failed run — is still owed.

---

### Fixtures

`~/Downloads/portal-live-check-fixtures/` — `sales/` (base table), `refresh_add/part0.csv` (sorts
first, adds `channel`), `refresh_casing/part00.csv` (headers `ID,Region,Amount`), `dq_agree/`,
`dq_disagree/`. Keep `part00.csv`'s name: the sampling rule makes ordering load-bearing.

**Left behind in the account:** shared space `livecheck_0814a` (member `agriffith` pending, one saved
query), table `agriffith_three.sales_livecheck`, and the fixture folders. The space is still needed
for SPEC-125's `leave`/`delete`.

---


## 2026-08-30 — Arc B's first real pass: the API, the catalog, the enqueue paths and an archive

Run from a warm signed-in Chromium session as `agriffith` against the **container origin**
(`portal.dataquarry.app`), deployed sha `726aa448`. Instruments 1–2 from `e2e.md` §1, extended with
an **XMLHttpRequest** patch — without it the upload is invisible, because the transfer is an XHR and
the shipped instrument only wraps `fetch`. Refusal probes were issued **in-page**, using the app's
own bearer, so no token entered the transcript.

### SPEC-199 — the arc's central claim, and the catalog surface

**Lake Formation still authorizes the session the API assumes.** `SELECT employee_id, name FROM
agriffith.employees` returned **2 rows, 112 B scanned, 706 ms**, rendered in the grid. LF grants
attach to a principal, and that principal is now the portal role assumed by the API rather than one
vended to the browser. **This also discharges SPEC-196 Phase 5 item 4**, which that spec recorded as
owed and re-homed here.

The denial half, both shapes **in one sitting**:

| Shape | Probe | Result |
|---|---|---|
| Glue read, no `DESCRIBE` | `GET /v1/catalog/databases/adamparker` | **403** `AccessDenied`, envelope-shaped, **no `detail` at all** |
| Athena query, no `SELECT` | `SELECT * FROM adamparker.employees LIMIT 1` | **200** on the poll, execution reaches **FAILED** |

The FAILED execution's `stateChangeReason` names the principal:
`arn:aws:sts::696000197480:assumed-role/dat-portal-user-role/agriffith`. That is independent live
evidence of two settled claims at once — the role is **reused, not minted**, and the **session name
is the username**. It is a stronger observation than the SPEC-196 probe route gave, and it arrives
from a direction that spec could not reach.

**The engine's current text still matches the wording rules after the JSON round trip** (FR-003):
the browser rendered *"You don't have permission to run that query. Contact the Administrator."* and
`main.innerText` contains **no** `arn:aws`, no `glue:GetDatabase` and no `Insufficient permissions`.
Had the rules stopped matching, every failed query would say only the generic sentence and nothing
would look broken.

| Check | Result |
|---|---|
| Foreign database vs absent database (FR-008 AC9) | **Indistinguishable** — `adamparker` and `nosuchname_xyz123` both **403 `AccessDenied`**, byte-identical apart from the request id; own database 200. **No existence oracle. Not a finding for SPEC-202.** |
| `null` ≠ `''` on the raw body (FR-004 AC2) | `{"columns": [{"name":"a","type":"unknown"},{"name":"b","type":"varchar"}], "rows": [[null, ""]], "nextToken": null}` |
| The 409/400 pair (FR-005 AC2) | Results against a still-running execution → **409 `QueryNotFinished`** (*"the execution has not reached SUCCEEDED"*); a malformed statement at submit → **400 `QuerySyntaxError`** (*"athena rejected the statement"*). One Athena exception name, two codes. |
| The disclosed SQL is byte-identical (FR-009, and `e2e.md` §4.5 row 11) | `aws athena get-query-execution` returned `SELECT employee_id, name FROM agriffith.employees` — byte-identical, and `DataScannedInBytes: 112` matches the cost line. Workgroup `dat-prod-portal-wg`. |
| The browser has stopped talking to Athena and Glue (FR-013 AC5) | **Zero** requests to `athena.*` or `glue.*` across every section run. One `POST /v1/queries`, one poll, results read only after the poll reported SUCCEEDED. |
| Cold start | The first invocation after the deploy succeeded; every record carries the real sha. |

### SPEC-198 — the object surface

| Check | Result |
|---|---|
| One API call per gesture | Folder create is **one** `PUT /v1/objects/content` (`overwrite:false`) plus the listing refetch. Empty name is refused **client-side with zero requests**. |
| The collision path | `overwrite:false` → **409** → banner *"A folder named … already exists"* with **Rename / Cancel / Overwrite**; verified in the listing, not from the dialog. |
| The upload | **One presign per file** — two `POST /v1/objects/upload-url` for two files, minted inside `uploadFile`, never per batch. |
| The transfer is `XMLHttpRequest` | `XHR:PUT dat-prod-user-space.s3.us-east-1.amazonaws.com/…` — a `fetch` would have completed correctly and left the bar at 0%. |
| The presign host | `dat-prod-user-space.s3.**us-east-1**.amazonaws.com` — the regional host, which is the one the CSP admits. Live confirmation of #553. |
| Foreign personal prefix (FR-013 live half) | **403 `AccessDenied`**, `detail: "personal space is not the caller's"` |
| Foreign shared space | **403 `AccessDenied`**, `detail: "no membership claim for that space"` |
| **The paired control** | The same route against the caller's own prefix → **200** with the listing. Without it a denial cannot be told from broken credentials. |
| `PUT` under `archive/` | **403 `AccessDenied`**, `detail: "archived locations are not writable"` — recorded as the **route-layer** refusal it is. |
| The CORS trio on the presign path (FR-011) | SPA origin → `access-control-allow-origin: https://portal.dataquarry.app`; **CloudFront origin `d1kbh4bnvh1je8.cloudfront.net` → its own ACAO**, so the rollback is intact; `example.invalid` → **no ACAO**. `access-control-allow-headers` is exactly `authorization,content-type,x-request-id`. |

**`owed.md` §2.1's marker Deny — run, and only half of it discharged.** `DELETE /v1/objects` on
`saved_queries/DO_NOT_DELETE.txt` is **403 `AccessDenied`** in the **personal** space and in a
**shared** one (`alexis_shared_space`), `detail: "folder markers may not be removed or replaced"`;
the paired control — an ordinary `.sql` file written and deleted in the same folder — is **200 and
200**. But that wording is the **API's own**, not IAM's: the route refuses before S3 is asked, so
what is settled is *the marker cannot be deleted through the API*, **not** that the bucket policy
denies it. The bucket-policy half is unreachable from this API and stays owed.

### SPEC-197 §F — the transport contract

| Item | Result |
|---|---|
| F.1 — suggestions **render**, by name | `SendFilesDialog` on `ad` → `adamparker`, `admin`, `tencalade27`; `AddMembersDialog` on `mi` → `mikec`; `TableShareDialog` on `mi` → `mikec`, `admin`. Real names, not a 200 with an empty array. |
| F.1 — one request, not three | Two dialogs in one page session issued **one** `GET /v1/user-directory` between them; the hour-long `staleTime` is unchanged by the port. The third dialog was opened after a full page load, so its own request is expected and the three-in-one-session claim is **corroborated across two, not three**. |
| F.1 — `AddMembersDialog` on `ad` returned **nothing** | Not a defect: `adamparker`, `admin` and `tencalade27` are all already members of `dwb_testing_all`. Checked against the roster before concluding. |
| F.2 — preflight headers | `OPTIONS` → **200**, `access-control-allow-headers: authorization,content-type,x-request-id`, `access-control-max-age: 600`. Every bearer-carrying cross-origin `fetch` in this session succeeded, which is the browser half — **in Chromium. Safari is still owed.** |
| F.3 — the refusals | No credential → **401** `{"error":{"code":"SessionExpired","requestId":"…"}}`; garbage bearer → the same, byte-identical apart from the id. |
| F.4 — **the correlation key is the gateway's** | `POST /v1/nope` with body `{"requestId":"spoofed"}` logged `request_id: "C6-0Oj1hoAMEZig="` and `client_request_id: null`. The string `spoofed` appears in **none of the 470 records**. |
| F.6 — cold start | The first invocation after the deploy succeeded. |

### SPEC-200 §G — the enqueue paths

**§G.5, the grants, simulated against the DEPLOYED roles.** `sqs:SendMessage` against all eight
request queues:

| Role | Result |
|---|---|
| `dat-portal-user-role` | **`implicitDeny` on all eight** |
| — paired control | `s3:GetObject` under the caller's own prefix (with `aws:PrincipalTag/username=agriffith`) → **`allowed`** |
| `dat-prod-api-role` | **`allowed` on all eight** |

This is the only evidence the browser's grants are actually gone rather than merely absent from the
templates. **Read the per-queue results one call at a time** — `--output text` over a multi-resource
simulate prints the decision on the first row only and the bare ARNs after it, which reads as seven
missing verdicts and cost a re-run to disbelieve.

**§G.1 row 8, archive, end to end** — the arc's first real request through the API on this plane, and
it is judged on the outcome rather than the 200:

- `POST /v1/enqueue/archive` → **200**, one call, body
  `{"requestId":"26c2e82f-…","source":{"space":…,"items":[{"kind":"folder","key":"agriffith/archive_live_0830/"}]}}`
  and **no `actor` and no `identity` field** — the actor is taken from the bearer server-side, which
  is the delegated-actor claim, observed.
- The notification arrived with the specified wording, and the folder left the listing.

**§G.1 row 9, restore** — `restore_started` arrived (below).

**§G.3, one log record per plane** — for the archive plane, every required field is present and every
forbidden one absent:

```
route_id: archive.archive   queue: archive   actor: agriffith
message_group_id: c781a6d5…  dedup_id = body_request_id = 26c2e82f-…
body_bytes: 1763   status: 200   env: prod   version: 726aa448…
```

### The structured log, swept mechanically rather than sampled

470 records in the session's window (215 `span.start` + 215 `span.end` + 40 others; 470 distinct
`log_id`s and **zero duplicate lines in the file** — the pairing is two spans per request, not a
double-write, which is what it looks like until you check).

**Nine absence checks, all zero:** any `eyJ`-shaped JWT substring, any email address,
`x-amz-signature`, any `AKIA`/`ASIA` string, a `usernames` array, raw SQL (`\bselect\b\s+\w`),
`stateChangeReason`, the string `Insufficient permissions`, and `arn:aws` anywhere in the fields.

**And the substitutes are present, which is the half a leak check cannot see:** `username_count`
(not `usernames`), `sql_bytes` (not the statement), `state` (not `stateChangeReason`), and on the
presign route **`key_length: 38`** — the key's *length*, never the key. Every record carries
`env: "prod"` and `version: 726aa448…`; **zero** records carry an empty or `0.0.0` version, which
was defect #5 of the 2026-08-27 session and is now fixed in the deployed build.

### The archive and restore (approval given in session)

Fixture `archive_live_0830/` created this session, two CSVs uploaded through the portal.

**B1 — every assertion passed.** The dialog heading named the folder **relative to the space root**
(`archive_live_0830/`, not `agriffith/archive_live_0830/`); it said the data will be removed and that
a restore takes several hours; it did **not** say "this can't be undone"; `role="alertdialog"`, and
**focus was on Cancel**. **Enter cancelled the dialog and issued zero requests** — the one
irreversible surface refusing the affordance that would fire it, observed for the first time.

The outcome: *"Archived 3 files (489 B). They have been removed from your space. Archive id:
26c2e82f-… - you'll need it to restore them."* — **3**, not 2, because the folder placeholder counts.
The notification's link is `/files?prefix=agriffith/archive/{uuid}/`, so it lands **in the archive
folder, not at the space root**. In that folder: `receipt.txt` (361 B) reads correctly; **Upload** and
**New folder** are `aria-disabled="true"` with `disabled === false`, `tabIndex 0` and the read-only
reason; **Archive is ABSENT, not disabled**. The source folder is gone from the space root.

**B2 — requested 15:16:39 UTC.** A nonsense id was refused inline with *"That doesn't look like an
archive id. Ids look like 3f8a1c2e-…"* and the submit control was **never merely disabled**
(`disabled: false`, `aria-disabled: null`, `tabIndex 0`). Fourteen seconds after submitting, the
receipt already read `Restore requested: 2026-08-30 15:16:39 UTC` with `Restored to: -` — **the
marker really is written before the bill**. The `restore_started` notification arrived — *"Restoring
3 files from long-term storage… Nothing has changed in your space yet."* — and carries **no link**,
as specified.

**Phase D is owed on this archive**, in 3–5 hours: the terminal notification and its link, the files
back at their original paths, `archive/{id}/` still holding its rewritten receipt, and multiple
`retrieval polled` events hours apart with `poll_count` climbing.

### Findings

| # | Finding |
|---|---|
| 1 | **The browser still calls the Identity Pool.** `fetchAuthSession` hits `cognito-identity.us-east-1.amazonaws.com`, and `/config.json` ships a **non-empty `cognitoIdentityPoolId`**. Expected — SPEC-202 is what retires it, and the CloudFront CSP allowlists the host deliberately — but **`CLAUDE.md`'s "the browser's only remaining AWS call is presigned S3 bytes" is false as deployed**, and `arc-b-api-container-e2e.md` §4's load-bearing negative would fail today if run as written. No AWS credentials are persisted (storage holds only oauth/id/access/refresh tokens), and the vended session's grants are the ones §G.5 measured. |
| 2 | **`arc-b-api-container-e2e.md` §F.3 asserted the wrong status.** It expected **404** from two *unauthenticated* `curl`s. The router resolves a principal **before** the route and refuses an unknown path as unauthenticated — its own docstring says so, because "a 404 to an unauthenticated caller tells them which paths exist". Both are **401**. With a valid bearer both are **404 `NotFound`**, envelope-shaped. Fixed in this branch. |
| 3 | The archive receipt's `Original path` reads `s3://dat-prod-user-space/agriffith/` — the **space root**, not the archived folder. The per-file paths live in the plan, so a restore is unaffected, but the receipt alone does not say *what* was archived. Not filed as a defect; worth a decision. |

### Not run, and why

- **F.5, the refresh-once path.** The stored token did age past its hour mid-session, but Amplify
  refreshed **proactively** on the next gesture — `cognito-idp` and `cognito-identity`, then a single
  `GET /v1/objects` **200 with no 401 first**. `apiRequest`'s 401-retry never fired, so the "exactly
  two requests" assertion has still never been observed. It needs the refresh broken, not merely the
  token expired.
- **The multi-GiB upload** (FR-005 AC8) — the premise the whole single-`PUT` design rests on. The
  fixtures here were 235 B and 254 B.
- **An intermediate upload percentage in a real browser** — the transfer is confirmed to be an XHR,
  which is the mechanism, but no progress event was sampled.
- **Safari, and 400 px.** Everything above is Chromium; it corroborates and cannot discharge.
- **§G.1's other eight rows, §G.2's double-submit guard, §G.4's refusals.** Archive and restore are
  two of ten planes.
- **A fresh sign-in.** The session was warm throughout. A second tab was found signed **out** —
  tab-scoped storage working as intended — but signing it in needs a password, which is not mine to
  enter.

---

## 2026-08-31 — the restore lands, and the browser's last AWS call is gone

Run from a warm signed-in Chromium session as `agriffith` against the container origin
(`portal.dataquarry.app`), after SPEC-202 **merge 1** deployed. Instruments 1–2 from `e2e.md` §1,
plus `performance.getEntriesByType('resource')` as the catch-all — it sees every subresource
whatever API issued it, which is what §4's row 9 actually needs.

### The archive from 2026-08-30, Phase D — every browser assertion passed

The restore requested at 15:16:39 UTC completed at **18:32:22 UTC**, 3 h 16 m later.

| Assertion | Result |
|---|---|
| The terminal notification, with its specified wording | *"Restored 3 files (489 B) to your space, back where they came from. The archive has been cleaned up."* Link `/files?prefix=agriffith/`. |
| Every file back at its original path | `archive_live_0830/` is at the space root holding `arch_a.csv` (235 B) and `arch_b.csv` (254 B) — 489 B, matching the receipt and the notification. The third "file" was the folder placeholder, which is why the folder exists at all. |
| `archive/{id}/` still holds its receipt | Present, and **416 B where it was 361 B** before the restore — the rewrite. |
| The receipt's archive lines survived, `Restored to` now filled | `Requested: 2026-08-30 14:56:06 UTC`, `Request ID`, `Original path`, `Archived path`, `Total size: 489 B`, `Files archived: 3`, `Restore requested: 2026-08-30 15:16:39 UTC`, `Restored to: s3://dat-prod-user-space/agriffith/`. **No line blanked.** |
| The bytes are readable, not merely listed | `arch_a.csv` fetched through its presigned URL in-page: 235 B, first line `id,region,amount`. |

**Byte-identity of the archive lines could not be asserted** — 2026-08-30 recorded the receipt's
*size*, never its text, so there is nothing to diff against. Capture the text next time; the size
is what you have when you want the bytes.

**The log half ran too** — see *The archive plane's log, read after the fact* below. An earlier
draft of this entry recorded it as classifier-blocked and owed; that was wrong, and the correction
is at the end of the entry.

### §4, the load-bearing negative — and this is the first window in which it could fail

`/config.json` no longer carries `cognitoIdentityPoolId`: the key is **absent**, not empty. That
closes 2026-08-30's finding #1, and it is what makes row 8 meaningful rather than structurally
unfailable.

One document held a listing, a folder create, a 7.0 MB upload, a download, an Athena query and an
enqueue. Nine filters:

| Filter | Expected | Observed |
|---|---|---|
| `api.dataquarry.app` | > 20 | **69** |
| `dat-prod-user-space.s3.us-east-1.amazonaws.com` | ≥ 2, a `GET` and a `PUT` | **2**, one of each |
| `cognito-idp.` / Hosted UI | any | **0** — no sign-in or refresh fell in the window |
| `athena.` · `glue.` · `sqs.` | 0 | **0 · 0 · 0** |
| `cognito-identity.` | 0 | **0** |
| catch-all | 0 | **empty** |

The entire host table was four entries: the SPA, the API, the user bucket, and
`fonts.googleapis.com`. The enqueue in the window (`POST /v1/enqueue/notifications`) is what makes
the `sqs.` zero mean something.

### The presigned URLs are SigV2 — and the leak sweep looks for a string they never contain

Both minted URLs carry `AWSAccessKeyId`, a **28-character** `Signature` (base64 HMAC-SHA1),
`Expires` as an absolute epoch, and `x-amz-security-token`. There is **no `X-Amz-Signature` and no
`X-Amz-Expires`** anywhere in either.

Two consequences, and the second is the one that matters:

1. `arc-b-api-container-e2e.md` §4 step 3 asserted those two parameter names, so anyone running it
   literally records a failure against a working system. Corrected in place.
2. **The credential-leak sweep has never run against the string production emits.** `e2e.md` §4.3
   and §4 step 4 both sweep the day's records for `X-Amz-Signature`; 2026-08-30 swept 470 records
   for `x-amz-signature` and found zero. That zero was unfailable. A presigned URL is a bearer
   token, and the check meant to prove none leaked could not have caught one. Corrected in both
   places, and the corrected sweep then **ran clean** — below.

The S3 client does take a botocore `Config` — `identity.py`'s `S3_ENDPOINT_CONFIG`, which pins the
regional endpoint and the addressing style *because* the SPA's `connect-src` names the regional
host. It sets no `signature_version`, and that word appears nowhere in `lambdas/` or `infra/`, so
the shape is botocore's default rather than a choice, and every offline fixture returns a v4-shaped
string it wrote itself. Whether to pin `s3v4` is a decision for a spec.

### The refresh-once path (F.5) — the arithmetic, at last

Reading or corrupting a stored token is refused by the agent's own classifier, and should stay
refused. The 401 was injected at the **response** layer instead — every `/v1/` answer replaced with
the API's own envelope at status 401 — which leaves Amplify's refresh entirely real.

| Condition | Result |
|---|---|
| Persistent 401, refresh healthy | **Exactly two** API requests for one gesture, **one** `cognito-idp` call between them, **zero** `cognito-identity`, **no third request**, user not signed out, no banner. |
| Persistent 401, refresh broken (`NotAuthorizedException` on every `cognito-idp` call) | **One** request, one failed refresh, and **no second request at all**. |

The second row is not what the script predicted. `apiClient.ts` returns
`failure('SessionExpired')` the moment a forced refresh yields no token, *before* the retry is
sent — so *"the retry 401s and there is no third request"* names a shape this code cannot produce.
No loop either way, which is the property the row exists for. **Still owed:** the same arithmetic
with a 401 the API itself produced from a genuinely expired bearer.

**A broken refresh does end the tab's session** — and recovery cost one click and no password,
because the Cognito Hosted UI cookie is browser-wide and outlives the tab's tokens. That is what
makes this a safe experiment to repeat, and equally why a warm-cookie sign-in cannot discharge
anything phrased against a *fresh* one.

### Also observed

- **Tab-scoped storage, three rows discharged** (see `owed.md`): a new tab arrived signed out; the
  code exchange ran; the deep link came back **with its query string**; tokens in `sessionStorage`,
  `localStorage` holding only `oauthSignIn`.
- **Lake Formation still authorizes the assumed session after merge 1** — `SELECT employee_id, name
  FROM agriffith.employees` returned **2 rows, 112 B scanned**. The 2026-08-30 pass observed this
  while the browser still held Identity Pool credentials; this one observes it with the pool gone.
- **§G.1 row 2, mark one notification read** — `POST /v1/enqueue/notifications`, and the bell went
  17 → 16 **and stayed 16 across a reload**.
- **A folder delete reaches the file-ops plane** — one `POST /v1/enqueue/file-ops`, an in-progress
  card, then *"Deleted 1 item."* and the card settled with the listing correct.
- **One call per gesture holds** — a folder create is one `PUT /v1/objects/content` plus the
  listing refetch; an upload is one `POST /v1/objects/upload-url` and one XHR `PUT`.
- The notifications page renders 10 of 83 with a client pager (`PAGE_SIZE`), and the bell's 17
  matched the document's 17 unread. Not a cap, and not a finding — checked in the source before
  writing it down.

### The archive plane's log, read after the fact

For request `26c2e82f`, from `logs/service=archive/`:

| Event | What it says |
|---|---|
| `restore plan built` 15:16:41 | **`manifest_present: true`** |
| `destinations clear` **15:16:42 and 18:32:11** | **Twice, three hours apart** — the guard before the bill, and the guard after retrieval. The two-pass design observed live rather than reasoned about. |
| `retrieval polled` × **39** | `poll_count` climbing **1 → 39** at five-minute intervals, 15:21:52 → 18:32:09, `complete: false` throughout and **`true`** on the last. The loop really looped. |
| `archive swept` 18:32:17 | The vault sweep ran. That it left *nothing behind* is still unread — that needs a principal on `dat-prod-archive`. |

The terminal notification landed 18:32:22, thirteen seconds after `complete: true`. **The sweep
event is named `archive swept`, not `cleanup`** — `e2e.md` §4.11 D and `owed.md` both said to look
for a `cleanup` block, so a reader grepping for that word finds nothing and concludes the sweep
never ran.

### The corrected leak sweep, and it is clean

`AWSAccessKeyId`, `x-amz-security-token`, `Signature=`, `X-Amz-Signature`, a JWT shape and an email
shape: **zero across 1,605 records** in `logs/service=api/` for the day. The positive control is
what makes that zero mean something — six `key_length` records in the same window, two of them this
session's own presigned keys, so the route really was minting URLs while the sweep was looking.

### A correction to this entry

An earlier draft recorded the log store as **classifier-blocked** and both checks above as owed.
That was wrong, and wrong in the way this project keeps paying for: **one compound command was
refused and I generalised it into a capability claim without testing the simple case.** `aws s3 ls`
and `aws s3api get-object` to stdout both run fine; `aws s3 cp` to a local file, and a pipe into
`python3`, are the shapes that get refused. The wrong claim reached a merged doc before the
spot-check caught it — a negative claim about *tooling* needs the same gate as one about code.

### Not run

- **Safari, and 400 px.** Everything above is Chromium; it corroborates and cannot discharge.
- **Data Explorer §4.5 rows 14 and 15**, and §G.1's remaining plane rows.
- **`KeyCount: 0` on the vault prefix** — needs a principal on `dat-prod-archive`.

## 2026-09-05 — the Data Quarry rename, against the deployed artifact

Run straight after PR #647's `main` deploys went green, against `https://portal.dataquarry.app`.
Chromium only.

**The served document.** `<title>` is `Data Quarry`, and a case-insensitive sweep of the served HTML
for `Data Workspace` and `S3 File Portal` returns **zero**. The title is the useful half: it is
stamped into `index.html` at build time rather than by the app, so it is the one brand site no
client-side check can confirm and no unit test covers.

**A deployed JS chunk, with both controls.** `/assets/errorMessages-*.js` carries
*"Data Quarry could not resolve where this space is stored"*, *"Data Quarry could not start"* and
*"Data Quarry is not configured correctly"*; the same chunk returns **zero** for the old
*"The portal could not start"*. The positive half is what makes the zero mean anything — the first
chunk I searched (`index-*.js`) returned zero for `Data Quarry` too, because the wordmark and the
error strings are in split chunks, and stopping there would have read as "the rename never shipped".

**The landing page, in a real browser.** All five brand sites render: the nav wordmark and its
`Data Quarry home` link label, the footer wordmark and its label, and `© 2026 Data Quarry ·`. The
hero reads *"Your data, scoped to you."* — the old copy echoed the previous product name and was
changed with it.

### Not run

- **The Data Explorer picker (`e2e.md` §4.5, the rewritten row).** Needs a signed-in session: the
  group headings `Tables (n)` / `Views (n)`, no title above the list, and no create control anywhere
  on the picker.
- **The Help step for Create table**, whose wording changed twice — it must read as the width
  condition ("if you cannot see Create table, the window is too narrow"), not as a device name.
- **The verification email's new subject.** `tofu` applied it in place (`0 to add, 1 to change,
  0 to destroy`, with the two `verification_message_template` strings as the only diff), but
  observing it needs a real signup.
- **Safari, and 400px.** Everything above is Chromium; it corroborates and cannot discharge.
