# The owed ledger

Every check that [`e2e.md`](e2e.md) cannot settle from one signed-in browser session, why, and what
it would take. **This file is the record — a check is owed until someone runs it and moves it out.**

**Settling a premise is not running the check.** A proxied assertion and an offline test that pins
the same property are both recorded here, not discharged. A Chromium run used to be on that list,
standing in for Safari; since 2026-09-01 Chromium is the engine of record and discharges on its own.

---

## 1. What is owed

> **Where Arc B's script went (2026-09-02).** Rows below cite `arc-b-api-container-e2e.md` by
> section — `§C.1`, `§E`, `§G` and so on. That file was the arc's one temporary script and was
> **deleted when the arc closed**, per `docs/process/completion-ritual.md` step 8. Its durable checks are folded
> into [`e2e.md`](e2e.md) — the front door, the CSP method, the no-AWS-calls negative and the
> presigned-URL shape are **§4.18**, and the per-feature ones sit in the feature sections. Its
> per-spec sections and its full execution log are in git history (`git show
> 95fddf14:docs/testing/arc-b-api-container-e2e.md`) and in [`sessions.md`](sessions.md). A section
> reference here is a pointer into that history, not a live path.

> **The 2026-09-10 sweep.** One sitting ran every row a signed-in session and a read-only CLI could
> reach, the archive plane excepted; rows it settled are struck below, and its evidence, the rows it
> could not reach and the five defects it found are the 2026-09-10 section of
> [`sessions.md`](sessions.md). **Two corrections that apply across this page:** a signed-in
> `POST /v1/enqueue/{plane}` replaces most "hand-crafted envelope" vehicles (§2.2 already says so),
> which also makes `fixtures/file-ops-plane.sh` unrunnable as written — it reads the token from
> `localStorage` and sends with `aws sqs send-message`; and **the Safari rows below rest on a premise
> Andrew retired on 2026-09-01** — the deployment's audience has no Safari — so a Chromium pass
> discharges them and they are marked retired rather than owed. That decision is recorded in
> SPEC-202's §9 criterion
> ([`SPEC-202-retiring-cloudfront-and-the-identity-pool.md`](../specs/SPEC-202-retiring-cloudfront-and-the-identity-pool.md),
> "Superseded 2026-09-01 (user decision)"); every "retired at its premise" below points there.

### Defects the 2026-09-10 sweep found — each owes a re-run once fixed

This table is where they are tracked; a follow-up session may already be working on one, but none
is closed until its re-run passes. Evidence is in the 2026-09-10 section of [`sessions.md`](sessions.md).

| Defect | The re-run that closes it |
|---|---|
| ~~**The Excel cap admits inputs the converter cannot finish** — a 60 MiB, 1,048,575 × 15 one-character-column result timed out at 600 s using all 3,008 MB~~ **CLOSED 2026-09-10 by SPEC-230's re-run:** the same query saved as Excel was refused in 3.1 s at 251 MB, naming 15,728,625 cells against 4,100,000, and saved as Parquet in 2.2 s. The at-cap row converted 1,025,000 rows at 2,410 MB in 61.4 s, inside the model's 2,518. Evidence in `sessions.md`'s second 2026-09-10 sitting | Convert that same shape to `.xlsx`: it must either finish, or be refused up front with a named reason rather than *"something went wrong"* ten minutes later. The SPEC-222 throughput row carries the measurements. `e2e.md` §4.3's cell-limit row is this re-run, and its at-cap row is the model's own check. |
| **Validation refusals carried no `requestId`** — file-ops' whole-request refusals and results-conversion's terminal both wrote `payload: null`. Fixed by #716, deployed 2026-09-10 21:42Z | Script §22 through a signed-in `POST /v1/enqueue/file-ops` (a delete of a shared space's root is the vehicle): the failure row's payload names the request id. Then a results-conversion failure **at the terminal**, where the gap was: a `destination_occupied` sent through the API so the browser's pre-flight is skipped, as the SPEC-222 row did. Its row must carry `requestId` and `format`. (A refusal at `validate-authorize` takes a different path, and a contract refusal there has no format.) |
| **The Query workspace's row-count walk is unbounded** — a 10-million-row result would take about 10,000 billed `GetQueryResults` pages | Run a query of about 10 million rows and count `GET /v1/queries/{id}/results` calls from the page: they must stop at a ceiling rather than walk every page. |
| ~~**The top bar overflows from 900 px up to about 960 px** (`innerWidth`; the page needs about 945 px of `clientWidth`, and the scrollbar takes 15) — at 900 px the page is 945 px wide in an 885 px `clientWidth`; worse with longer usernames~~ **CLOSED 2026-09-11 by #725's re-run:** on `/files`, with a 15 px scrollbar forced to match the sweep's, `scrollWidth` equals `clientWidth` at 900, 930 and 959 (885, 915, 944) and the account button ends at 871, 901 and 930, inside it; no tab or toolbar label wraps, and Delete stays inside the toolbar — the second overflow the header's had hidden, fixed by the same PR (`docs/decisions/browser.md`, the `tablet` band entry). **Not foregrounded:** the viewport was proven at each width by `matchMedia` instead, after a reload. **375 was not run live** — the device-toolbar half of §4.15's band check (a three-digit count wraps whole) stays owed with the 400 px pass below. Evidence: `sessions.md`, 2026-09-11 | At `innerWidth` 900, 930 and 959 px, foregrounded: `document.documentElement.scrollWidth` equals `clientWidth`, **and** the account button's right edge is within `clientWidth` — a fix that clips the header would pass the first half alone. Run it **on `/files`**, where the toolbar is, and read `e2e.md` §4.15's band check alongside. |
| **Navigation remounts the signed-in shell** — `RootLayout`'s `<ErrorBoundary key={pathname}>`; uploads abort and in-flight cards vanish | `e2e.md` §4.2's navigate-away row, and an upload that survives a route change. |
| ~~**Cancelling the overwrite question resets the save dialog** to its defaults~~ **CLOSED 2026-09-10 by #719's re-run:** a Parquet save of `explorer150_conv` into `conv0910_parquet/`, which already holds that file, raised *Overwrite "explorer150_conv.parquet"?*, and Cancel reopened the dialog with the name `explorer150_conv.parquet`, Parquet, My files and `My Files / conv0910_parquet` — where the sweep got `query-results-…`, CSV and the root. *My files* is also the default, so the space restore rests on #719's shared-space integration test. Evidence: `sessions.md`, 2026-09-10 third sitting | `e2e.md` §4.3's overwrite row: after a cancel the name field holds the file name the question showed (`<name>.parquet`, extension included), and the format, space and folder are the ones the user left. |
| ~~**The Excel row-limit refusal prints `1049000`** where the success message prints `1,049,000`~~ **CLOSED 2026-09-10 by SPEC-230's re-run:** the 1,100,000-row fixture's refusal read *"the results have 1,100,000 rows"*, refused in 305 ms | The row-limit refusal reads with a thousands separator. |
| ~~**A relative listing prefix equal to the space's own name reads as the space root** (`protected.contained_prefix` treats any prefix starting with the root as absolute)~~ **CLOSED 2026-09-10 by #719's re-run:** #719 gave a prefix one reading — absolute, like every key the API takes — so `<space>/` is the root by contract and the folder named like the space is `<space>/<space>/`. Against a fixture folder `agriffith/agriffith/inner/`, `prefix=agriffith/agriffith/` answered **200** listing exactly `agriffith/agriffith/inner/`, `prefix=agriffith/` answered **200** with the root, and the relative `arcb_files/` and `inner/` both answered **403 `AccessDenied`**, *"prefix is not inside the space root"* — the answer that tells the new code from the old, which re-rooted them. Evidence: `sessions.md`, 2026-09-10 third sitting | **Straight to `GET /v1/objects`**, for a space holding a folder named like itself: `prefix=<space>/<space>/` lists that folder, `prefix=<space>/` lists the root, and a relative `prefix=<folder>/` answers **403 `AccessDenied`** rather than listing `<space>/<folder>/`. The portal cannot reach this — every one of its listing callers sends an absolute prefix — so a click passes with the defect present. |
| **The log sweep is saturated** — every run stopped on its wave cap, `dat-prod-logs.fifo` held 17,134 messages, and `logs/service=api/` ran about two hours behind; `lambdas/info/planes/standalone.md` sizes `MAX_WAVES` for far less. **Fixed 2026-09-11, pending its re-run:** the ceiling was the message group, not the wave count — a group per service drained ten a wave — so the logs queue is now grouped per event, and the `logs-backlog` alarm watches the age of the oldest message | After one working session, the sweep's runs end on an empty queue rather than `wave-cap`, and the API partition is minutes behind, not hours. **Judge by age, not by the stop reason while the session is live:** a caught-up sweep can still stop on `wave-cap` then, chasing arrivals. The `logs-backlog` alarm reads `OK` throughout, and `ApproximateAgeOfOldestMessage` stays near one tick (about 600 s). **Start only once the pre-deploy backlog has drained** — it is still in the old per-service groups, which drain ten a wave, so the alarm may read `ALARM` for hours after the deploy — and record messages per wave, since the per-wave ceiling assumes a receive round returns about ten. |

### Needs a second (or third) account

| Check | Why one account cannot do it |
|---|---|
| **Receiving a send** (SPEC-167) — bob's link lands in `shared_files/alice/` with the files there; the space recipient's link carries `?space=` and lands in the space, not the sender's own files | The prefix is minted in Python and honoured by a TypeScript route rule; the failure mode is a link that *looks* like it worked. Needs `alice`, `bob`, `carol` and a shared space alice does **not** own (an owner who is also the sender gets two messages for one outcome, which changes every count). |
| **Membership as a non-owner member** — the Data Explorer against a shared space, archive/restore in one, the roster | Runs against real Cognito tags and real Lake Formation. The one-sided version passes trivially. |
| **Add → acknowledge → read roster** (SPEC-125, after SPEC-186 FR-008) | The acknowledge fan-out is what closed a roster saying `Pending` for a member the same page showed `Active`. Only a second account can flip it. |
| ~~**Cross-user prefix isolation** (SPEC-013 FR-004)~~ **DISCHARGED 2026-09-10 by paired simulation**, the vehicle this row allows: as `alice`, Put/Delete/Get on `bob/x.csv` `implicitDeny` beside `allowed` on `alice/x.csv`; `ListBucket` allowed only for `alice/`, and `bob/`, `bo`, no prefix and an empty prefix all `implicitDeny`. `AbortMultipartUpload` and `ListMultipartUploadParts` were not simulated; they sit in the same statement as the three object verbs that were. | As `alice`, every S3 verb against `bob/` is denied and a root listing leaks nothing, while the same calls against `alice/` succeed. The app never issues the cross-prefix call, so it needs two users' portal credentials or a policy simulation. The **paired success is what makes the denial mean anything**, and it must be driven from `npm run dev` — the production bundle's console cannot `import()` a bare specifier. |
| **A share's recipient queries the result** (SPEC-161) | `SELECT count(*)` from the recipient's own database must return the source's row count, not zero. |
| **Shared-space catalog isolation, both negatives** — **the IAM half DISCHARGED 2026-09-10 by paired simulation**: with slot tag `marketing`, `GetDatabase`/`GetTables` allowed on `marketing` and `implicitDeny` on `finance`; `DeleteDatabase`/`UpdateDatabase` `implicitDeny` on `marketing` and on `alice`, beside `DeleteTable` allowed on `marketing/t1`. **The Lake Formation half is still owed** — no simulator models LF. | Two live properties are asserted from reading two files and have never been measured: a member of space A cannot reach space B's Glue database, and **no** member can drop or alter a space's database (Lake Formation grants the shared role `ALTER`/`DROP`, and only the absence of `glue:DeleteDatabase`/`glue:UpdateDatabase` in IAM withholds them). `lambdas/test_shared_space_isolation_coupling.py` pins the artefacts, not the effect. Needs two accounts and their portal credentials, or a paired policy simulation. |

### Needs the CLI

| Check | Why | Recipe |
|---|---|---|
| ~~**A real run's records carry ONE `trace_id`** (SPEC-225 FR-005, in production)~~ **DISCHARGED 2026-09-09 on the archive plane.** Three real runs in one sitting — one archive (`f0465c23-…`) and two restores (`589e1b90-…` succeeded, `7728c043-…` failed) — **three request ids, zero carrying more than one `trace_id`**, and **three different trace ids across the three runs**, which is the warm-container half: the restores ran 25 s apart. **Every `span.start` belonging to those three runs carries a non-null `parent_span_id`, and every record with NO `request_id` is a deploy-time cold-start probe whose parent IS null.** The split is load-bearing and is stated as two POPULATIONS because unscoped the claim is false. **A DAY-scoped count rots** — that object grows with every deploy. A PER-RUN count does not, once the run has ended; the figures an earlier draft pinned rotted for a different reason, which is that two of the three runs were still executing when it wrote them. The archive run's trace id is the one in its own SQS `traceparent`, so it was minted at the API and propagated in. **The file-send half too**: that plane had no real traffic for days 06–09, so **three** runs were driven — `456ae6a8-…` (18 records, `522a88ce…`), `e2fbb066-…` (`fb345885…`) and `1de4a077-…` (**65 records, `25dc566d…`, across 8 Distributed-Map children**). One trace each, **three distinct trace ids**, zero null parents, so the warm-container half holds here too. **Cite `1de4a077-…`, not `456ae6a8-…`** — the first run was a `recipient conflict` that skipped the transfer and started no Map child, making it the one run that could not show it. | — | Evidence: [`sessions.md`](sessions.md) 2026-09-09 |
| ~~**A real FAILED run's records carry one `trace_id` INCLUDING `notify-failure`'s, and a failure that replaced the state does not** (SPEC-227 FR-002, in production)~~ **DISCHARGED 2026-09-09, both halves. The limit half was REAL WHEN MEASURED and SPEC-228 has since closed it** — the measurements below stand as the record of what the fleet did on 2026-09-09, and they are what the repair was derived from; what is no longer true is the general claim in this row's title, because every `RecordFailure` now carries the forwarded envelope and `notify-failure` reads the run's traceparent and the caller's request id out of it in Python. **(a)** The archive plane supplied the positive half without the deliberate run this row proposed: restore `7728c043-…` failed **post-identity** at `PollRestore`, and its `notify-failure` records carry the run's own trace `4176296a…` with a **non-null** `parent_span_id` (`6a790f3d…`), the same trace as that run's `validate-authorize`; across its records no request id carries more than one trace. **(b)** Driven as request `579de943-…`, execution `301a88ae-…`, naming `spec227_no_such_space` — **no object under `shared-spaces/` carries that name**. The run's trace `336d82e0…` is **four** records over **two** partitions (the API's root span `8f52805494b02b63` in `service=api`, `validate-authorize` under it in `service=archive`); `notify-failure` is **three** records in `service=archive` on `8a06aa9a…` with a **null** parent. Nothing joins them. **Name the partitions or the count means nothing** — a first draft said "two records" of the four-record trace, because the sweep is per service. **Three things this row asserted were wrong, and running it is what showed that.** (1) **It needs no queue write.** The row reasoned that only a hand-crafted envelope could name an unregistered space, because the UI offers none — true of the UI, false of the API under it: the enqueue routes read no membership by design, the contract types `space.name` as a free string, and the FIFO group id is derived from the body. A signed-in `POST /v1/enqueue/archive` reaches the plane intact, so no assumed role and no `sqs:SendMessage` are needed — which is what made this runnable at all from a session whose production AWS writes the harness refuses. **§2.2 now leads with this, and several rows in §1 still name a hand-crafted envelope for a body the API can in fact send.** (2) **The reason code is `forbidden`, not `unknown_space`.** Archive has **no** `unknown_space` code: `arcommon/messages.py` records that a shared space that does not exist fails `authorize_source` as `forbidden` on purpose, so that "no such space" and "you are not a member" stay indistinguishable — the difference is an existence oracle over other people's spaces. The trap the row names is still real, but the discriminator is **`unauthorized` versus `forbidden`**: an envelope with no identity block gives the first and proves nothing. Check the reason, not the shape. (3) **The failure correlated on NOTHING, not on the request id — the measurement SPEC-228 was derived from, and the one it closed.** `notify-failure`'s records carry no `request_id` at all — the seed supplies `requestId: null` and, on the ASL door, `ar_notify_failure` recovers only the **actor** from `raw` (the mode comes off the state, where the seed put null, so a pre-identity RESTORE failure is worded as an archive). SPEC-228 FR-001 already said so; the claim survived in **three current-tier homes** — `docs/decisions/control-planes.md`'s SPEC-127→129 and SPEC-225 entries, and `lambdas/info/shared-layer.md` — and all three are corrected. **Not user-visible:** `validate-authorize` notifies from its own `except TerminalError` before re-raising (hence `notify_terminal=False` on its decorator), so the inbox correctly read *"You don't have access to archive those files."* and `notify-failure`'s *"suppressed a duplicate of the verb's own failure notification"* is right rather than a lost message — `_verb_already_notified`, whose six-plane population is in the register's suppression clause. **The data-quality observation this row used to carry is kept, because it predicted the result:** the refused check `d3c33db9-…` was a **post**-identity failure — actor verified, the *location* refused — whose `validate-authorize` sat on the run's trace `69f4847b…` while its `notify-failure` ran 3 s later on `2333f306…` with a **null** parent. That is the shape the register attributed to *pre*-identity failures, observed on a failure that had an identity, and it is why "pre-identity" names the CATCH shape rather than the absence of one. | — | Evidence: [`sessions.md`](sessions.md) 2026-09-09 second sitting, and the 2026-09-09 entry beneath it for (a) and for the data-quality observation |
| ~~**`ItemBatcher.BatchInput` reaches the child of an `ItemReader`-fed Distributed Map**, with `Items` unchanged beside it (SPEC-225 FR-003 AC-1)~~ **DISCHARGED 2026-09-09 — and without the throwaway state machine, exactly as the row above predicted.** The deployed archive orchestrator carries **three** Distributed Maps — `TransferObjects`, `RetrieveObjects`, `CopyBackObjects` — each `ItemReader`-fed with `ItemBatcher.BatchInput` holding `traceparent.$` and `requestId.$`. A real archive run's child execution input, read back whole: `{"BatchInput":{"requestId":"f0465c23-…","traceparent":"00-563c9568…-be39d193…-01"},"Items":[{"srcBucket":…,"srcKey":"agriffith/spec220_archive_fixture/",…,"storageClass":"GLACIER"},{…"header-only.csv"…}]}` — both present, the items the manifest rows untouched. **What makes it sound rather than circumstantial: the items carry no `traceparent` of their own**, so `BatchInput` is the only channel the child's trace could have arrived by. Corroborated at runtime on two different Maps — `copy-objects` and `initiate-restore` records both carry their run's trace id and a non-null `parent_span_id`. | — | Evidence: [`sessions.md`](sessions.md) 2026-09-09 |
| ~~**The route layer refuses `PUT /v1/objects/content` under `{root}system_settings/archive/x`**, with the SAME code as under `{root}archive/x` (SPEC-219 FR-004)~~ **DISCHARGED 2026-09-09.** Both homes answer **403 `AccessDenied`** with the identical `detail` — *"archived locations are not writable"* — and a control write to `agriffith/spec220_route_control.txt` answered **200**, which is what tells a key-specific refusal from a blanket one. Issued from the signed-in session, so the ROUTE really did consult the predicate. The envelope carries no AWS text. | — | Evidence: [`sessions.md`](sessions.md) 2026-09-09; recipe in [`e2e.md`](e2e.md)'s API table |
| ~~**The `DO_NOT_DELETE.txt` Deny on the portal role**, personal and shared (SPEC-173)~~ **DISCHARGED 2026-09-09 by simulation, both halves, each with a control:** `s3:DeleteObject` on `alice/DO_NOT_DELETE.txt` **explicitDeny** beside `alice/reports/x.csv` **allowed**; and on `marketing/DO_NOT_DELETE.txt` **explicitDeny** beside `marketing/reports/x.csv` **allowed**, with `shared_space_1=marketing`. The control is what makes it mean anything — an `explicitDeny` alone cannot tell the marker Deny from a mistyped ARN. **§2.1 is no longer the vehicle** (see its banner); this ran as `simulate-principal-policy` from the operator CLI identity. | The portal issues **zero** `DeleteObject` against the marker — it is hidden by basename and the folder delete is refused client-side first. The Deny is the layer that matters if the SPA is ever wrong. | §2.8 |
| ~~**Refresh-lock contention** (SPEC-157)~~ **DISCHARGED 2026-09-10** with two `table-refresh` POSTs in one `Promise.all`: A held the lock 04.124–05.854 and succeeded; B, 44 ms behind, was refused `refresh_already_running`, and its no-etag release left A's lock alone (A's CAS release logged no lost-compare-and-swap). | Two UI submits 2 s apart both return independently — a small table's refresh finishes inside that window, so the lock is never contended. Nothing that runs today proves two real executions serialize. | §2.2 |
| **A malformed message on a request DLQ** (SPEC-133 Phase 5; also discharges SPEC-126's) | The user is notified, the message is gone, and the redacted body is in `logs/service=dlq-drain/`. Nothing in the app can send a malformed request. | §2.2 |
| **A deleted space keeps its objects and its Glue database** (SPEC-205 FR-003) | The whole point of the change, and the owner is the one person who can no longer see it — their access ends with everyone else's. From the browser the space is simply gone, which looks identical to the old destroying behaviour. Needs an admin credential to list `{space}/` and `GetDatabase`. | — |
| **The emptied record is inert to its original owner** (SPEC-205 FR-004) | `authorize` reads the `owner` field, and a delete clears it — so every owner-only action is refused. There is no UI path left to attempt one: the space is gone from the owner's list, so the buttons do not render. Needs a hand-built enqueue as the original owner. | — |
| **A share or a file-send into an emptied space is refused** (SPEC-205 FR-006) | Asserted offline against both validators, and the browser cannot drive it: the share dialog suggests only spaces you belong to, and a former member belongs to none. Needs a hand-built request naming the space. | — |
| **A failed delete offers Retry and no Dismiss** (SPEC-205 FR-007) | Nothing in the app can make a delete fail. The affordances are asserted in the portal suite against a seeded cache entry; what is owed is that a real failure writes `failedAction: "delete"` into that entry. Needs a fault injected into the verb. | — |
| **The query workspace inside the credential window** (SPEC-205 FR-009) | A removed member holding a live token can still `SELECT` from — and `DROP TABLE` in — the retained Glue database, because the editor takes a fully qualified `database.table` and the principal tag was minted before the delete. Every other plane refuses them via `is_active_member`. Bounded by the Identity Pool TTL and accepted; owed because nothing offline measures how long that actually is. | — |
| **`glue:GetDatabase` under a Lake Formation denial** (SPEC-205 FR-001) | The backfill's report reads absence from `EntityNotFoundException` only, so an LF denial fails the run loudly rather than mis-reporting a create as never-provisioned. That is the right direction and nothing offline can prove the live shape — the repo already pins that LF answers `AccessDeniedException` elsewhere. | — |
| ~~**The file-operations plane, end to end** (SPEC-187) — a valid request reaching its terminal, an unauthorized source notifying the ACTOR rather than the body's claim, each protected-location rule refusing PER ITEM while the ordinary item beside it proceeds, and the space root refused outright~~ **DISCHARGED 2026-09-10 through the API**, not the script: valid copies and moves `SUCCEEDED`; another user's source refused `forbidden` with one notification in the ACTOR's inbox; four protected folders refused per item beside an ordinary folder that was deleted, the run `SUCCEEDED`; the space root refused `space_root_not_an_item` — aimed at a shared space holding only test files, not the personal root. | Nothing in the browser reaches this plane: the enqueue service exists and no gesture calls it until SPEC-190. Every check is a hand-crafted envelope. And a shared layer's import-time failure only shows at COLD START, so no offline test can tell you a verb shipped without `focommon`. | [`fixtures/file-ops-plane.sh`](fixtures/file-ops-plane.sh) §1–5 |
| ~~**A real `move` of a folder over 1,000 objects** (SPEC-189) — the source deletion is complete, and conditional~~ **DISCHARGED 2026-09-10**: 1,201 objects `moved`, 0 failed, source and parent empty, 151 Map batches covering 1,201 items — equal to the manifest; and the conditional half in the modified-source row's run, two rows down. | Only a real Map Run past the pagination boundary exercises the batch path and the per-item attribution together. | [`fixtures/file-ops-plane.sh`](fixtures/file-ops-plane.sh) §10 |
| **The batch path's precondition-mismatch `Code` string** (SPEC-189) — and the ALREADY-GONE one beside it | **AWS does not document it.** `DeleteObjects` answers HTTP 200 with the object in an `Error` element, and the mapping has to tell `source_changed` from `AccessDenied` from "already deleted". Two strings, not one: a replayed verb meets keys its predecessor removed, and reading those as failures reports correctly-moved items as `duplicate`. | §11 |
| ~~**A `move` whose source is modified between the copy and the delete** (SPEC-189)~~ **DISCHARGED 2026-09-10**, the window hit deliberately: an in-page loop polled the DESTINATION `f0001.txt` and overwrote the SOURCE the moment it landed; the item ended `duplicate` / `source_changed`, the source kept only the changed `f0001.txt`, the destination holds all 1,200 with the old bytes. | The mismatch must surface as a per-item **`duplicate`**, never a silent skip — the user holds the data twice and only they can choose. | §12 |
| **A `delete` of a folder holding a nested `DO_NOT_DELETE.txt`** (SPEC-189) | The marker survives and **the rest goes**, which is only true because `assert_item_deletable` is per item. **Not stageable through the portal (2026-09-10)**: an upload of a nested marker is refused 403 *"folder markers may not be removed or replaced"*, and a copy of `saved_queries/` plans without its marker — the fixture needs an operator write. | §13 |
| **The conditional-delete ENFORCEMENT probe** (SPEC-189) | A service model carrying `ObjectIdentifier.ETag` proves botocore will *serialize* the condition, not that S3 *enforces* it — and a serialized-but-ignored condition deletes a changed source silently, versioning off. **`CONDITIONAL_DELETE_ENABLED` stays `False` until this passes**; until then the HEAD-compare path runs and a race window remains. **And one code change is owed with the flag**: a 409 currently raises, which escalates a partly-complete deletion to a whole-request failure with no per-item terminals — it must become a per-item retryable outcome first. | §14 |
| ~~**The file-ops execution role's IAM simulation** (SPEC-189)~~ **DISCHARGED 2026-09-10**, both buckets identical: `system_settings/athenaresults/` delete, nested marker delete, `user_settings/` put and `system_settings/archive/` put all `explicitDeny` beside allowed controls. **The script's `{root}athenaresults/` DENY row is stale** — that path is an ordinary folder since SPEC-220's narrowing, so it reads `allowed`, correctly. | Needs the **deployed** role, and every denial paired with an `allowed` control — an `implicitDeny` alone cannot tell an ungranted action from a wrong resource ARN. | §15 |
| ~~**Two file operations in one space do not run at once** (SPEC-187 FR-009)~~ **DISCHARGED 2026-09-10** with two API POSTs in one `Promise.all` — one group, distinct dedup ids, a 1,201-object source for the winner: the loser's history shows `WaitForLock → AcquireLock` twice and it operated only after the winner's `ReleaseLock`; `acquire-lock` logged 1 attempt then 3, and no steal. | The obvious technique does not work and must not be re-derived: two submits seconds apart both return independently, because the window is milliseconds on a small selection. Needs ONE `send-message-batch`, same group, distinct dedup ids, **and a several-hundred-object source for the winner** — with a small folder the first run finishes before the Pipe starts the second, and the check passes having measured nothing, which is exactly how the table-builder's own equivalent failed. **The pass condition is NOT that plane's**: this loser WAITS, so what is observed is a `Wait` → re-acquire cycle followed by success, two lock claims and no steal warning. | Script §6 |
| **A wedged lock makes the waiter GIVE UP rather than time out** (SPEC-187 FR-009) | The give-up bound is deliberately well under the machine's ceiling, and nothing offline proves the inequality holds in a real run — a bare `TIMED_OUT` instead of the refusal would mean it has been broken. The wedged holder must be a DEAD execution: a live waiter re-claims its own lock every attempt and so refreshes `acquiredAt`, and would never be stolen. | Script §7 |
| ~~**A folder of more than 1,000 objects plans every one of them** (SPEC-188) — submit an expansion whose source folder crosses the pagination boundary and confirm the plan's `objectCount` matches what the bucket actually holds~~ **DISCHARGED 2026-09-10**: `plan.json` read from the admin bucket, `objectCount` 1201 — the 1,200 files plus the zero-byte folder object, which is what the prefix holds — 1,201 unique keys, `failed: 0`. | The boundary is what a fixture proves least: a fake paginator yields whatever the test told it to, so a verb that read one page and stopped passes offline and plans two thirds of a folder in production — and for a move, SPEC-189 then deletes the rest. Needs a real folder over 1,000 keys and a hand-crafted envelope, since no gesture reaches this plane until SPEC-190. **Read the plan back from `{admin_bucket}/file-ops/{requestId}/plan.json`** — the object count on the state is the same number the plan records, so it is not independent evidence. | [`fixtures/file-ops-plane.sh`](fixtures/file-ops-plane.sh) §1, with a larger source folder |
| **A destination conflict is reported PER ITEM** (SPEC-188 FR-005) — one selected folder whose derived keys collide and one that does not, in a single request, ending at the ordinary terminal with one `conflict` and one `cleared`. **RUN 2026-09-10 with two FILE items, not folders**: one request, one item `conflict`/`destination_occupied` against a real `HeadObject`, one `copied`. **Still owed: the folder variant as written, and the `overwrite` half** — under `onConflict: overwrite`, a destination object whose `LastModified` is at or after the request's `submittedAt` must still come back as a `conflict` and be left untouched, while an older one is replaced; stage it by writing that object between building the body and sending it. **The 403 half has no vehicle**: the execution role's `GetObject` and `ListBucket` carry no conditions on either space bucket, so `HeadObject` answers only 200 or 404 for it. | Every offline test drives a fake S3. What is owed is that a real `HeadObject` against a real destination produces the same verdict, ~~and that a 403 — which the role's own `athenaresults/` Deny can produce — is read as occupied rather than as clear~~ (that Deny covers put and delete only, so no 403 is reachable; anything but a 404 reading as occupied is pinned offline). The `overwrite` half needs an object modified AFTER the body's `submittedAt`. | Script §17 (a pre-populated destination) |
| ~~**A cross-space move takes TWO locks and releases both** (SPEC-187 FR-009)~~ **DISCHARGED 2026-09-10 on a cross-space COPY** — the destination-lock branch is the same for both operations; a move was not separately run: *"holding 2 space lock(s)"*, and both lock objects polled back to `holder: null` after. | Needs a shared space the acting user belongs to. Without the destination lock, a concurrent delete in that space runs alongside the move — which is this FR's own failure mode on the side the group id does not cover. | Script §8 |
| ~~**A request that takes the first lock and LOSES the second releases the first** (SPEC-191)~~ **DISCHARGED 2026-09-10 from the `acquire-lock` log, against a LIVE holder.** The shared lock sorts first for the standing pair (`114a…` before `c781…`). While a large copy held the personal lock, cross-space request `e8a06e3c` logged *space lock acquired* (shared) → *space lock refused* (personal) → **_space lock released_ (shared)** within 66 ms; request `c4ed47d8`, blocked by three short personal-space requests, did the same on three attempts. *Space lock released* is the proof: `cpcommon.lock.release` logs it only after the conditional write under the acquire's tag succeeds. The `released_partial: 1` on the same attempt is **not** proof — it counts the locks held, and reads 1 even with the release removed. A CLI loop reading the shared lock about once a second saw `holder: null` throughout. **§8b's recipe used to be vacuous for this pair** — it wedged the shared lock, which sorts first, so the request held nothing — and it now wedges the lock that sorts second. The give-up under a wedged, dead holder is the SPEC-187 FR-009 row, script §7, and is still owed. | Deadlock-freedom on two locks is the class nothing offline proves, and it is the whole reason the two are taken in digest-sorted order. A first lock left held blocks that user's whole space until the stale steal, hours later. | Script §8b |
| **The run's notification, its link and its payload** (SPEC-191) — a clean run's one message; a PER-ITEM partial in one request; the payload a re-submit is built from; a `delete`'s link landing in the items' PARENT — **RUN 2026-09-10; everything that ran passed except §22.** Read from `notifications.json`: one message per request with `payload.requestId`; the partial names both halves and carries `conflicts`; the capped message ends *"And 1 other not listed here."*; a multi-item delete links to the items' parent. **§22 FAILED**: both whole-request refusals had `payload: null`, because the validator built its failure event by hand without the id. #716 fixed it and was deployed at 21:42Z the same day. **Still owed: §22 re-run live** — a signed-in delete of a shared space's root is the vehicle, and the failure row's payload must name the request id; **and §20's single-folder repeat**, the one shape where the parent link can go wrong, which did not run. | The notification IS the completion channel, so a run that did the work and said nothing is a failure of the plane even though the execution is green. Nothing in the browser reaches this plane until SPEC-190, so every one is a hand-crafted envelope — and the payload is not RENDERED anywhere until then either, so it is read out of `notifications.json` in the Network tab. | Script §16–18, §20, §22–23 |
| ~~**A shared-space link carries `?space=` FIRST** (SPEC-191 FR-004)~~ **DISCHARGED 2026-09-10**: a cross-space copy's link begins `?space=another_shared_space&prefix=…`; clicking it lands in that space with the files listed. | The failure is silent, which is why it cannot be settled offline: the row's feature gate tests for the literal `?space=`, so the other parameter order slips the gate, the route never reads the space, and the user lands in their OWN files with no banner while the message names a shared one. | Script §19 |
| **A real folder move in the deployed app, in Safari at 400 px** (SPEC-190) — accepted immediately, the in-progress card surviving navigation, the listing correct after a focus return, and the notification settling the card — **RUN 2026-09-10 in Chromium at 1512 px, and it FAILS one clause**: one API call and zero AWS calls, the card, the folder-selection gate and the settle all pass; **the card does not survive navigation** — `RootLayout`'s `<ErrorBoundary key={pathname}>` remounts the signed-in shell on every route change, which also aborts uploads in progress (tracked in the defects table at the top of §1). **Still owed: the navigation clause once that is fixed, the listing after a focus return (`e2e.md` §4.2's *Refresh this folder* row, not run), and 400 px**, which needs the device toolbar. The Safari clause is retired at its premise. | Everything offline mocks the queue, so what is unproven is the whole loop: a real `SendMessage` reaching a real execution, and a real notification coming back with a `requestId` the browser matches. The width matters on its own — the in-progress card is a fixed element sharing the bottom of a 400 px viewport with the mobile action bar, ~~and Andrew browses in Safari, which is not the engine any of this was driven in.~~ (Safari retired at the premise, 2026-09-01.) | [`e2e.md`](e2e.md) §4.2, the async-switchover rows |
| ~~**A prefix holding a query character survives the round trip** (SPEC-191 FR-004)~~ **DISCHARGED 2026-09-10**: a copy into `q?a&b=c#0910/` links as `prefix=agriffith/q%3Fa%26b%3Dc%230910/`, and clicking it lands in exactly that folder. | The only link on the fleet built from an arbitrary user-controlled KEY rather than a constrained name. An unencoded `?` or `&` truncates it into a URL that resolves somewhere else — and the browser's own `isSafeInAppPath` cannot see that, since it only inspects the first two characters. | Script §21 |
| ~~**The notifications `create` boundary** (SPEC-206) — a `create` sent with real portal-role credentials is refused, and `markRead` beside it still succeeds~~ **RETIRED AT ITS PREMISE 2026-09-10**: real portal-role credentials cannot send to the queue at all — `sqs:SendMessage` simulates `implicitDeny` for `dat-portal-user-role` beside an allowed control, and of the two browser-facing roles only the API role is allowed (the planes' own execution roles also send, to emit notifications) — and the one door a browser has refuses the verb: `POST /v1/enqueue/notifications {action:"create"}` → 400, `markRead` → 200. | Every offline test fakes the SQS event, so the `SenderId` a test supplies is the one it wants. What is owed is that the value **real portal-role credentials** produce is the one the writer refuses — the role-id half of what Cognito's enhanced flow actually stamps, which AWS does not document. It cannot be driven from a signed-in browser either: the production bundle's console cannot `import()` a bare specifier (recorded below), which is what driving the SQS client from there would need. The pass condition is **no new row in the target's inbox** plus the reason code in the log — **not** "it reaches the DLQ", which is exactly what the refusal drops to avoid. | **§2.1 is RETIRED and this row has no vehicle today** — see its banner. It needs the `SenderId` that real portal-role credentials produce, which a policy simulation cannot supply, so neither §2.1 nor §2.8 settles it. Named here rather than left pointing at a dead recipe. |
| ~~**A request naming an unregistered space is REFUSED, not faulted** (the registry list grant)~~ **DISCHARGED 2026-09-10** on file-send through the API: the execution `SUCCEEDED`, the recipient annotated `invalid: "unknown_space"`, no `AccessDenied` traceback. | This is the defect the grant fixes, and its offline test cannot see it: every suite fakes S3, and a fake raises `NoSuchKey` for a missing key, which is the one shape production never produced under a role with no list statement. What is owed is a real send to a space name that is not in `shared-spaces/`, ending at the ordinary `unknown_space` refusal with the recipient annotated — **not** a failed execution. The pre-fix signature to check it against is the 2026-08-17 traceback: `AccessDenied ... s3:ListBucket on arn:aws:s3:::dat-prod-athena-admin` out of `cpcommon/registry.py:30`. | A hand-crafted envelope on any plane's authorize step; no plane-named script exists for file-send yet |
| **The two documents that belong to no user answer ABSENT, not denied** (portal role) | `ListTheSharedDocuments` is what makes `_directory/` and `_config/` absence reachable, and neither route's handler has ever run in production. Measured in `logs/service=api/` on 2026-08-30: every `/v1/user-directory` record was refused before the handler (`verification_failed`, `no_bearer_credential`, or the route not being served), and `/v1/feature-flags` does not appear at all — so both absence branches are unrun as well as unprovable offline. **The API is not idle**, which an earlier draft of this row wrongly claimed: `PUT /v1/objects/content` and `POST /v1/queries` both carry authenticated traffic. Delete or rename the flag document and call the route: expected `404 NotFound`, not a 5xx. Same for the directory, expected an empty `200`. **Restore the document afterwards** — the flags document is read on every page load. | — |
| **The archive/restore negative assertion** — for a refused restore, **no** `RestoreObject` for that archive id | A refusal that had already begun retrieval is invisible from the UI and costs 3–5 billed hours. Read the audit trail, never `head-object`. | §2.4 |
| **The vault prefix is swept after a restore** (SPEC-171 FR-005) — **PARTLY SETTLED 2026-08-31:** `logs/service=archive/` carries `archive swept` for request `26c2e82f` at 18:32:17, so the sweep *ran*. That it left **nothing behind** is still unread. | Nothing human can read `dat-prod-archive`, and the browser sees only the receipt folder, which survives by design. `aws s3api list-objects-v2 --bucket dat-prod-archive --prefix "personal/$USERNAME/archive/$ARCHIVE_ID/" --max-keys 5` → **`KeyCount: 0`**, `_manifest.json` included. Needs a principal on that bucket's allowlist, which no human identity is. | — |
| ~~**`head-object` on user-space or archive** — restored objects back at `STANDARD`, content type survived, byte-identical~~ **DISCHARGED 2026-09-09** for archive `f0465c23-…`, restore completed 14:25 UTC. Against `agriffith/spec220_archive_fixture/header-only.csv`, with `agriffith/header-only.csv` — the never-archived object it was copied from — as the control: **`STANDARD`** on both, content type **`text/csv`** on both, 10 bytes on both, and **ETag, raw bytes and SHA-256 all equal**. `lastModified` is the pair that shows a REWRITE rather than an object that never left: control **2026-08-06T01:11:48Z**, restored **2026-09-09T14:25:14Z**, which is the copy-back. The archive run also ran `DeleteSource`, and the fixture was gone from the root listing. | **What `STANDARD` excludes, and what it does not.** It excludes the silent failure the archive ASL names on `CopyBackObjects`: an item copied without an explicit STANDARD *"lands back in GLACIER and expires to unreadable a few days later, having looked like a success throughout"*. It does **not** establish what the vault held — that is still unobservable, and the row further down saying so stands. Note the route defaults a missing class to `STANDARD`, so the reading means "S3 reported no class"; it still bites, because S3 reports `GLACIER` explicitly. **Content type excludes nothing here** — at 10 bytes this took the single-copy path where `MetadataDirective` is S3's own default; the discriminating case is the `>5 GiB` row below, still owed. **And no `head-object` by the OPERATOR CLI identity** — that half of the blocker is real and current, both buckets deny it — but the route makes one server-side under a role that can reach the bucket. | Details drawer, [`e2e.md`](e2e.md) §4.2 |
| **The `>5 GiB` metadata round trip** (SPEC-171, and all three transfer planes) | `CreateMultipartUpload` carries no `MetadataDirective`, so before the fix every object over 5 GiB lost its content type on every copy this repo makes. Only an object over the threshold exercises it; a fixture below it passes forever. Confirm `ContentType` survives by `head-object`. **No browser can make the fixture** (2026-09-10): the upload drawer caps a file at 5 GB, so the source object needs an operator write. |
| ~~**The restore plan agrees with the receipt** (SPEC-170)~~ **DISCHARGED 2026-09-09** for request `589e1b90-…`: `archive/589e1b90-…/restore-plan.json` exists with `objectCount: 2` and `totalBytes: 10`, the receipt reads `Files archived: 2`, and both `destKey`s are the original paths — `agriffith/spec220_archive_fixture/` and `…/header-only.csv`. | Evidence: [`sessions.md`](sessions.md) 2026-09-09. |
| ~~**The archive plane's log events** (SPEC-169/170/171)~~ **DISCHARGED 2026-08-31** for request `26c2e82f`: `restore plan built` 15:16:41 with **`manifest_present: true`**; **39** `retrieval polled` events, `poll_count` climbing **1 → 39** at five-minute intervals from 15:21:52 to **18:32:09**, `complete: false` throughout and flipping **`true`** on the last; then `archive swept`. **`destinations clear` appears TWICE** — 15:16:42 and **18:32:11**, three hours apart — which is the two-pass guard observed live rather than reasoned about. The terminal notification followed 13 s later. **The sweep event is named `archive swept`, not `cleanup`**, which is what this row said to look for. | `logs/service=archive/` carries the events above. |
| ~~**The fan-out is visible exactly once per child** (SPEC-166/167)~~ **DISCHARGED 2026-09-09** for request `1de4a077-…` — a **29-object** folder sent to **two** recipients (a user and a shared space). The `TransferObjects` Map run reports `total: 58, succeeded: 58` across **8 child executions**, and `logs/service=file-send/` carries **exactly 8 `batch copied` events**, item counts `8+8+8+8+8+8+8+2 = 58` — the Map's own total. Each carries a distinct `span_id` under **one shared `parent_span_id`** (`f037c2da…`), so the fan-out is visible as a span tree and not just as a count. **Get the batch size right or this measures nothing:** `MaxItemsPerBatch` is **8**, so a send of one file to one recipient is 1 item, 1 child, 1 event, and the 1:1 holds trivially — the first attempt this session did exactly that, and a second was refused as a `recipient conflict` with the transfer skipped and **no** child at all. It needs more than 8 transfer items (**objects × recipients** — 29 × 2 = 58 here) to be a real fan-out. **Size it from the OBJECT count, never from what the browser shows:** this folder lists as 23 files in the UI while the copy plan counted **29** keys, because the listing the browser renders is not recursive and the plan is. | Evidence: [`sessions.md`](sessions.md) 2026-09-09. |
| **Table share at scale** (SPEC-160/161) — a several-hundred-object, >20 GiB table shared to two recipients where one conflicts; the 100-column clone read back with all 100 comments through `GetTable`; and the over-cap refusal — with ~500 objects, **41 recipients** exceeds it — whose operator detail reads `N recipients x M objects is <product> transfer items (cap 20000)` while the notification says only *"that's too many files to copy to that many recipients at once."* | The counts and the clone are only readable through Glue and the structured log. | §2.5 |
| **The `TIMED_OUT` door** (all **six** planes: `archive`, `file-ops`, `file-send`, `results-conversion`, `table-builder`, `table-share`) — **THE PATTERN HALF DISCHARGED 2026-09-09 — and the measurement found a HOLE rather than surplus coverage.** Production runs **eight** orchestrators. `data-quality` and `shared-space` set no `TimeoutSeconds`, so they cannot emit `TIMED_OUT` and need no rule. **`table-builder` set `TimeoutSeconds: 3600`, shipped a `dat-prod-table-builder-notify-failure`, and had NO rule** — no EventBridge rule in the account named it and `infra/modules/table-builder/` defined none. **Fixed and confirmed live 2026-09-09**; see the row below. A state-machine-level timeout cannot be caught by a `Catch`, so EventBridge is the only door, and for that plane it was missing — an hour-long table build that timed out notified nobody. **That was a defect, not a gap in this check** — see the row below. All **six** planes with a ceiling now declare one, and a fleet guard derives that population from the ASL rather than listing it. All six carry an `…-orchestrator-timed-out` rule: all **ENABLED**, all with `detail.status` exactly `["TIMED_OUT"]`, **no `FAILED` anywhere in the pattern**, each scoped to its own `stateMachineArn`, each targeting that plane's `notify-failure`. | Waiting out a real 3-hour timeout is not a test anyone will run — which is why the remaining half is a synthetic event, and **do not re-derive that by driving a real timeout.** **The rule-MATCHING half is discharged too, and read-only** — `test-event-pattern` against the deployed pattern answers `True` for the right `stateMachineArn` with `TIMED_OUT`, `False` for another machine's, and **`False` for `FAILED`**, which is this row's real worry measured rather than eyeballed. **What is left is the HANDLER half, and the reason is neither effort nor a credential.** It needs **no token**: since SPEC-201 (`ff3a76b6`, 2026-08-30) `cpactor.trusted_actor` reads only the nested `identity` block and imports no JWT code, so the body needs `{"identity":{"actor":"<username>","delegated_by":null,"assurance":"interactive"}}`; §2.5 below carried a flat token until this session and now says so. `events:PutEvents` on the default bus measured **`allowed`** for the operator CLI identity on 2026-09-09, so the grant is there too. What stops it is that an **agent session's production AWS writes are refused by the harness**, and `put-events` is one — measured, not assumed. The vehicle is therefore CI or a human at the CLI. **And `put-events` is the wrong write anyway:** a `Source` beginning `aws.` is reserved, so the entry is refused while the call still returns 200 with `FailedEntryCount: 1` — an exit-code check passes having published nothing. §2.5 now leads with `lambda invoke`. | §2.5 |
| ~~**`table-builder` has a state-machine timeout and no timed-out door** (found 2026-09-09)~~ **FIXED 2026-09-09 — both halves.** The EventBridge rule now exists in `infra/modules/table-builder/stepfunction.tf` beside the other five, and `tb_notify_failure` dispatches on the detail-type into a door that recovers the actor from the `identity` block, so the plane matches the correlation the gap was found by: the planes with a rule are exactly the planes whose handler has the door. The deploy role's grant landed first, in its own PR. **The rule alone would not have fixed it** — it would have deployed green and delivered a status-change event to a handler reading a top-level `actor` that such an event does not carry, reproducing the same silence. | **CONFIRMED LIVE 2026-09-09**, after `Deploy Infrastructure` and `Deploy Lambdas` went green on the merge: `describe-rule` returns `dat-prod-table-builder-orchestrator-timed-out` **ENABLED**, pattern `status: ["TIMED_OUT"]` with no `FAILED`, scoped to that plane's machine, targeting `dat-prod-table-builder-notify-failure`; the handler was re-deployed the same run. Re-measured across the fleet: **all six orchestrators with a `TimeoutSeconds` now carry a rule**, and the two without one (`data-quality`, `shared-space`) correctly carry none. |

### Control-plane bring-up, only reachable through a hand-crafted request

These prove the plane itself, not the feature, and the UI cannot stage them. The first four are
driven by a hand-crafted request (§2.2); SPEC-108's has its own recipe in §2.3; SPEC-058's is a
policy simulation (§2.8). **SPEC-169's Deny-on-one-key needs a temporary policy edit and has no
recipe anywhere** — write one when you run it.

| Check | Why it matters |
|---|---|
| **`cpcommon` imports at a real cold start** (SPEC-168, and every plane) — **observed 2026-09-10 on the results-conversion plane**: real queued messages hit cold starts of `convert` (init 1,076 ms), `notify-failure` ×5 and `describe-results`, and every one imported and ran. The other planes' executions that day ran too, but nothing forced their cold starts, so **every other plane is still owed**: a cold start shows as an `Init Duration` on the function's `REPORT` line in CloudWatch. | SPEC-137 shipped instrumented code whose layer attachment was missing and **every offline gate passed** — `conftest.py` puts the shared roots on `sys.path`, and `update-function-code` succeeds against a function that cannot import. The attachment is gone with the layers, and the image's matrix plus the deploy's cold-start probe now cover what it used to risk; a hand-crafted request through the queue is still the only thing that runs a real cold start on a real message. |
| **A `PutObject` into your own `archive/` prefix is refused**, personal and shared (SPEC-168) | The browser Deny that stops a receipt being forged. The app never issues the call. |
| **A Deny on ONE key mid-archive** (SPEC-169 step 3) | The whole point of the commit gate: the run fails, **every source object is still there**, the archive prefix is empty, and the notification is honest. Nothing else exercises the rollback arm against real S3. |
| ~~**The pagination boundary** (SPEC-165)~~ **DISCHARGED 2026-09-10 with zero writes**: a file-send of a 1,200-object folder to a nonexistent space — `InspectSource` runs before recipients are checked — reported `objectCount` 1200 and the exact byte sum; the copy plan holds 1,200 unique keys and no marker. The bucket's own listing of that prefix is 1,201: the one more is the zero-byte folder object, which file-send's expansion drops by design along with markers, so 1200 is the count this criterion means. | Over a **1,200-object** folder, `InspectSource`'s `objectCount` equals the `list-objects-v2` count exactly — **not 1,000**, and not one more than it — the `DO_NOT_DELETE.txt` marker is excluded, but it lives at the **space root**, not in this folder. The only live proof the lister paginates. |
| ~~**The state order, including the poll loop** (SPEC-108, data quality)~~ **DISCHARGED 2026-09-10** on a 10-million-row CSV: `WaitForQuery CheckQuery` three times, then `ByteScan AssembleReport DropTempTables`, `SUCCEEDED`. The 150-row fixture loops only once and proves nothing — **size the input so the profile outlasts the 30 s wait**; a 1,200-file folder is refused outright (`DQ_MAX_OBJECTS` 1000). | **`WaitForQuery`/`CheckQuery` must appear TWICE** — one pass through is a poll that never polled. Recipe in §2.3. |
| ~~**The portal role can enqueue a user action and NOT a `create`** (SPEC-058)~~ **PREMISE CHANGED, and the boundary that replaced it DISCHARGED 2026-09-10**: since SPEC-200 the portal role enqueues nothing — `implicitDeny` on the notifications queue beside an allowed control — and the API role is the sender; the API's notifications route refuses `create` (400) and accepts `markRead` (200). | The anti-spoof boundary: a browser that could enqueue `create` could write any user's inbox. Simulate `sqs:SendMessage` against the notifications queue and read the rendered policy. |
| **The seven shared-space producer events** (SPEC-061), especially **delete fanning out to every member** | One notification per member per event, from the verified actor. A missed fan-out is silent. |
| ~~**The front door answers, and its 200 is deliberate** (SPEC-221)~~ **DISCHARGED 2026-09-10**: `POST /v1/enqueue/results-conversion` → **200** with the request id echoed, captured from the page's own enqueue. | `POST /v1/enqueue/results-conversion` from a signed-in session answers **200** with the echoed request id — 200 rather than 202 is a recorded decision, and a 202 read as failure would be this check's own bug. **SPEC-222 retired the other half of this row:** it used to assert the execution reaching `Placeholder` with nothing written, and there is no `Placeholder` and no read-only role any more. What replaced it is §1 of `docs/testing/fixtures/results-conversion-plane.sh`, which drives the same POST and expects a file. **SPEC-223 shipped the browser surface**, so the enqueue itself is now reachable by clicking **Convert and save**; this row stays owed only for the *envelope* — the literal 200 and the echoed id — which a click cannot show without the network panel open. |
| ~~**Each of validate-authorize's refusals, against the real Athena** (SPEC-221)~~ **DISCHARGED 2026-09-10**: `forbidden`, `protected_location`, `execution_not_found`, `execution_not_finished` (*"execution is RUNNING"*) and `no_result_set` (*"statement type is 'UTILITY'"*), each 200 at the door and **one** notification in the actor's inbox. | Five of the twelve registered codes, provokable with one real execution id of the session's own: another user's space (`forbidden`), a protected folder (`protected_location`), a made-up execution id (`execution_not_found`), a still-running execution (`execution_not_finished`), and a `SHOW TABLES` (`no_result_set`). **The sixth needs a second account and is in the section below.** Offline fixtures cover every branch; what only a live run settles is that Athena's real `GetQueryExecution` shape feeds them — the `StatementType` and `ResultConfiguration.OutputLocation` fields are read from a document no test has seen. Each refusal arrives as **one** notification in the actor's own inbox. |
| ~~**A conversion end to end, one per format** (SPEC-222)~~ **DISCHARGED 2026-09-10 by clicks** (see the SPEC-223 section): Parquet and JSON read back through **Create table** at `count(*)` 150; the `.xlsx` parsed in-page at 151 rows and 0 formula cells, and a formula probe (`=`, `+`, `-`, `@`, tab, CR) came back as strings. | The arc's whole point, and no offline test can reach it. **SPEC-223 shipped the browser surface, so this is now a click** — §4.3 and §4.5 of [`e2e.md`](e2e.md) carry the steps, and the hand-crafted request is the fallback rather than the method. Per format, the file lands in the chosen folder, **one** notification says `Saved N rows as <Format> to "<name>"`, and its link resolves to that folder. The Parquet and the JSON are then read back by the table builder — which is the property the arc exists for, "save it, then build a table from it" composing — and the `.xlsx` opened and checked for a formula cell. Recipe: `docs/testing/fixtures/results-conversion-plane.sh`. |
| ~~**`destination_occupied`, staged as a real race** (SPEC-222)~~ **DISCHARGED 2026-09-10** through the API, so the browser's probe was skipped: `convert` downloaded the input and THEN logged *"refused destination_occupied"* — the conditional write refused, not a pre-check; the named notification arrived and `lastModified` did not move; the `overwrite` twin moved it from 19:10:18Z to 19:30:19Z. | **Still NOT stageable from the browser, and SPEC-223 made that more true rather than less.** `useSaveResults` runs an `objects.exists` pre-flight and turns an occupied answer into the overwrite question, so the browser can never send `onConflict: refuse` at an occupied destination — reaching the plane's own conditional refusal needs a hand-crafted envelope that skips the probe. Convert the same name twice with `onConflict: refuse`. The second must arrive as the named refusal rather than an overwrite or an `AccessDenied`, which is the only live proof that `If-None-Match` is doing the work and no lock is needed. Then repeat with `overwrite` and confirm the object's timestamp moves. |
| ~~**Athena populates `Precision`/`Scale` beside a bare `decimal`** (SPEC-222)~~ **DISCHARGED 2026-09-10 through the plane's own read**, since the CLI identity cannot read results: four decimal columns the portal types as bare `decimal` converted to Parquet — `athena_type_of` would refuse one without a precision, and read a missing scale as 0 — and a table over the file reads `decimal(10,3)`, `decimal(5,1)`, `decimal(38,2)`, `decimal(4,0)` exactly. | Captured evidence settles half of this: `lambdas/fixtures/athena_result_all_types_columns.json` shows Athena reporting `decimal` with no parameters, which is why `describe-results` carries the siblings. What it cannot show is whether those siblings are POPULATED — the portal's own results route maps `ColumnInfo` to `{name, type}` and drops everything else, so they are invisible to any browser capture. Needs one direct `athena:GetQueryResults`. If the precision were absent, `athena_type_of` refuses the column rather than guessing one, so the failure is loud (a missing scale alone reads as 0); the risk is a refused conversion, not a wrong file. |
| **A size reaching `CreateFunction` through INDIRECTION** (SPEC-222) | `test_fleet_derivation.py` refuses an over-quota `memory`/`ephemeral` declaration by reading the literal out of the fleet's `.tf` files. A value assigned through a local or a variable — `memory = local.heavy_tier` — carries no literal to read, and refusing indirection wholesale is not open: seven `memory_mb = each.value.memory` sites are how the fleet is legitimately wired. The check that would close it reads the PLAN's resolved values (`tofu plan -json`, `aws_lambda_function` → `memory_size` / `ephemeral_storage`), which needs credentials and belongs in CI beside the apply that already knows. Until then the local gate covers literals only — and it no longer leaves that silent: `test_every_size_the_gate_cannot_read_is_a_known_wiring_form` bounds the blind spot by FORM, so a new kind of indirection reddens even though its value cannot be read. |
| **The converter's real throughput on amd64** (SPEC-222) — **MEASURED 2026-09-10, and it found a defect in the cap, not the timeout**: about 0.82 MB/s — **below this row's own ~1 MB/s trigger** — though 64 MiB still fits the 540 s usable at about 82 s, so the timing half is safe; but peak memory was about 49 B per CSV byte with the function's 147 MB baseline subtracted (57.9 without it) against the assumed 32.45, and a 60 MiB result of 1,048,575 × 15 one-character columns — inside both the size cap and the row limit — **timed out at 600 s using all 3,008 MB**, telling the user only *"something went wrong"*. Tracked in the defects table at the top of §1; this row closes when the cap is re-derived. | **Superseded in part by SPEC-230:** the cap is re-derived per cell and the 4.2 MB/s check below is gone, replaced by per-cell checks against a measured corpus; this row closes with that spec's live conversion at the cell cap (§4.3), whose `REPORT` line is the reading it asks for. That conversion ran on 2026-09-10 — 2,410 MB in 61.4 s, in `sessions.md`'s second sitting — and the "roughly 1 MB/s" trigger below is the byte-rate check SPEC-230 retired. Closing the row is left to the session recording the throughput measurements, which owns it. The convert timeout's check derates a measured 4.2 MB/s Excel figure by 4, because the measurement was taken on an arm64 build and production runs amd64 — a factor no local run can supply. Read the `REPORT` line (Duration, Max Memory Used) from the converter's CloudWatch log after a live `.xlsx` conversion. **If Excel is below roughly 1 MB/s the size cap has to come down**; the derate exists to make that the only thing at stake. |
| **A shared space whose NAME is not catalog-safe** (2026-08-19) | The premise behind `sqlIdentifier`/`sqlDdlIdentifier` on `CREATE VIEW` and `DROP`: `shared-space-validate` applies **no format check** to `space` on the create path, so the browser dialog is the only thing holding the rule. Enqueue a create for a name containing a backtick, a double quote or a space (§2.2), then confirm from the member's browser that dropping a table in it and creating a view from it both run — and that the rendered statement quotes the name rather than breaking on it. **If Glue itself refuses the name, say so and close this** — that would mean the quoting is belt to a braces that already holds, which is worth knowing either way. |

### SPEC-223's live checks — RUN 2026-09-10: six of eight settled, the band row settled but for 375 px, and the flag-off row still owed

**Run on 2026-09-10 in Chromium**, evidence in the 2026-09-10 section of [`sessions.md`](sessions.md).
The row-limit row needed no fixture after all — Athena generates the rows (`UNNEST(sequence())`,
0 bytes scanned) — which falsifies the paragraph below about its cost; it is kept as written because
it records why the row was separated. What follows is the section as it stood.

**Seven of the eight** are reachable from a single signed-in session with no second account, no CLI
and no hand-crafted request — the surface shipped, which is what SPEC-223 was for — and they are
owed because **the session that built it had no browser connected**, so nothing was observed. That
is a different kind of owing from the rest of this page and is recorded separately for that reason.

**The other one costs more, and says so in its own row** rather than leaving it to be discovered:
the flag-off check needs a config change merged and published. The row-limit refusal used to cost
more too, and no longer does — a zero-scan query stages it, as its row says. Counting the flag-off
check with the seven would make the section's own claim false. That
is a different kind of owing from every other row on this page, and it is recorded as such rather
than blurred into them: the steps are in [`e2e.md`](e2e.md) §4.3, §4.5, §4.14 and §4.15, ready to run.

| Check | Where | What would settle it |
|---|---|---|
| ~~**Each of the four formats saved from the Query workspace**, and each read back — Parquet and JSON through **Create table** to `count(*) = 150` against the `explorer150` fixture, the `.xlsx` opened~~ **DISCHARGED 2026-09-10** — both tables `count(*)` 150; JSON one object per line; the `.xlsx` parsed in-page (151 rows, 0 formula cells), not opened in a spreadsheet app | §4.3 | One signed-in sitting. The conversion is asynchronous, so allow a minute per format for the notification. |
| ~~**The same four from the Data Explorer**, and the two surfaces agreeing on every label~~ **DISCHARGED 2026-09-10** — identical title, intro, labels, options, default name and buttons; three conversions of 150 rows and zero query starts | §4.5 steps 11–13 | The same sitting. The dialog is one component, so a disagreement between the two is the regression the pair exists to catch. |
| ~~**The overwrite confirm on a conversion**, and the pre-flight asking *before* the request leaves~~ **DISCHARGED 2026-09-10** — asked with zero enqueues; confirming sent one `overwrite`. **Cancel resets the dialog** to its defaults (name, CSV, root): `useSaveResults.cancelOverwrite` remounts the dialog. That was a defect, **closed 2026-09-10 by #719's re-run** — see the table at the top of §1 | §4.3 | The same sitting. Distinct from SPEC-222's `destination_occupied` row above, which is the plane's half; this is the browser asking first. |
| ~~**A shared-space destination writes an undoubled key**~~ **DISCHARGED 2026-09-10** — `another_shared_space/reports0910/explorer150_shared.parquet`, no doubled folder at the root, and the link opens that space | §4.3 | The same sitting, plus a shared space. **The highest-value check here** — the root-relative prefix is the one defect on this branch that a personal-space fixture cannot see, and a doubled root is refused by nothing. |
| ~~**The notification's link refreshes the folder it lands on** — the file is present on arrival~~ **DISCHARGED 2026-09-10** — listed on arrival, after one fresh listing call | §4.3 | The same sitting. Asserted offline against a spy; what is unobserved is that a real listing is stale without it. |
| **`resultsConversion` off hides the select on both surfaces** — needs more than a sitting | §4.14 | §4.14's method is a repo change plus CI: edit `config/feature-flags.json`'s `environments.prod`, **merge**, wait for **Publish Config**, hard-reload — then undo all of it. Not a browser-only check. |
| ~~**The `excel_row_limit` refusal, staged above the limit** — the one row here that needs more than a sitting~~ **DISCHARGED 2026-09-10 with no fixture** — `SELECT 1 AS x FROM UNNEST(sequence(1,1049)) CROSS JOIN UNNEST(sequence(1,1000))` (1,049,000 rows, 0 B scanned) gave the pinned sentence, and the same result saved as Parquet. The refusal prints `1049000` where success messages print `1,049,000` — **fixed by SPEC-230**, which renders every count with separators and checks Excel's row ceiling first, from a count taken before anything is built, so the third column's `results_too_large` note is now true only over 64 MB | §4.3 | Over **1,048,575 data rows** (Excel's ceiling less the header) **and under 64 MB** as CSV — `describe-results` refuses on size before convert counts rows, so a wide result returns `results_too_large` and this refusal never fires. No §2 fixture reaches either bound (the largest is 150 rows). The cost is building one: a generated single-narrow-column CSV — about 8 bytes a row keeps 1.05M rows near 8 MB — in its own folder, a table over it, then `SELECT` that one column. The wording is pinned in both languages by `test_the_row_limit_refusal_is_the_sentence_the_browser_renders`; what is unobserved is a user receiving it. |
| **The dialog at 375 px, and across the 375–899 band** — **768, 899 and 900 px DISCHARGED 2026-09-10** (fields full width and stacked, button 31.5 px for both labels; below 900 px it is opened from the Explorer, because the Query page shows only Saved and History); **375 px still owed** — below 606 px needs the device toolbar. The same run found the **top bar overflowing from 900 px up to about 960 px**, a separate defect in the table at the top of §1 | §4.15 | Four widths — 375, 768, 899, 900. The fields stack and the format select is full width at each. jsdom measures no geometry at all, so this is the only place the layout is checked. |

### Needs a second account for the REFUSAL half

| Check | Note |
|---|---|
| ~~**Another user's real execution id refuses identically to a made-up one** (SPEC-221)~~ **DISCHARGED 2026-09-10 through the operator's workgroup list**, a vehicle this row names: a SUCCEEDED execution whose output sits under another user's prefix was refused `execution_not_found` with `describe-results` and `convert` never invoked, and the user's sentence is **byte-identical** to the made-up id's. | The half that makes the refusal not an existence oracle: `execution_not_found` must carry the **same sentence** for an id Athena has never seen and for one belonging to somebody else, or a caller can enumerate whose queries exist. One account cannot stage it — nothing in the product surfaces another user's execution id, so it needs a second signed-in account to run a query and hand its id over, or an operator reading the workgroup's execution list, which is not a signed-in session. |
| **Shared-space authorization negatives** (SPEC-053/054) | A **non-owner** `add_members` and `remove_members`; an **owner** trying to `leave`; a **non-owner** trying to `delete`. Each must fail in `Validate` with no side effect. The positive half is in `e2e.md` §4.8 and passes trivially. |
| **A forged or expired `idToken`** | Fails in `Validate` (Catch → `Failed`) with no side effect — auth is server-side, and this is the only check that says so live. |
| **A stale membership tag reads as `AccessDenied`** | Sign the member out and in again before concluding anything about a membership check. Without the token refresh a correct system looks broken. |

### Needs an admin-bucket write no browser session can make

| Check | Why one signed-in session cannot do it |
|---|---|
| **The operator request path** (SPEC-208 FR-007/FR-008, widened by SPEC-217) — drop a `space,action,username` CSV in `<admin-bucket>/operator-requests/inbox/`, wait a tick, and see each request land, the file move to `processed/`, and the right people notified | The inbox is in the **admin** bucket, which the portal role can read but not write, so the file cannot be put there from a signed-in session or from my own upload path. It needs the CLI under a credential that can write that prefix. **One file, three spaces, all three words** — `add`, `remove` and `transfer` — is the whole check: an operator-driven add must be the same verb, the same notifications and the same records as an owner-driven one, which is the claim reuse rests on and which no offline test can settle. Sub-checks that ride with it and are owed for the same reason: the **retired header** `space,new_owner` is rejected to `rejected/` with a `.reason.txt` naming the new one; a file naming **one space under two actions** is rejected naming both lines; a message with `origin: operator` from any **other** principal is refused and the space's owner is notified; and a file with more rows than one invocation can read is REJECTED with a reason naming the cap rather than left for a tick that could never take it. The offline suite drives every one against fakes — what is owed is the real `SenderId`, which no fake can produce. |
| **An operator removal, and the session it does not revoke** (SPEC-217 FR-004) | Two facts that only a live run shows. A `remove` row naming the space's **current owner** must be refused by name, telling the operator to transfer the space first — offline this is a predicate call, live it is the single most likely thing an operator will write. And the removed member's access does **not** end when the row is processed: the principal tag was stamped when their credentials were vended, so they keep it until their token is re-minted. Needs a second account signed in at the time of the removal, and someone watching the clock. |
| **The operator's own feedback channel** (SPEC-208, widened by SPEC-217) | An operator gets no notification: the people notified are the space's owner and the members added or removed, and none of those messages names the operator. Their only channel is the reader's structured log, which now says the action and the space on every enqueued request and which lines fed it — so the check is that a removal does not read as an ownership transfer. Confirming it means reading the logs queue's output for a real run, which needs the CLI check above to have happened first. |

### Needs infrastructure that is deliberately not created

| Check | Blocker |
|---|---|
| **`Description` and column-comment preservation across a refresh** (SPEC-149) — both survive, the columns changed, `get-table-versions` shows a previous version | Needs the `dat-prod-verification` role. From any other principal Glue returns *Insufficient Lake Formation permission(s): Required Describe*. See §2.5. |
| **The foreign projection fixture** (SPEC-153 FR-006 AC2) | The same `GetTable` response. Paste it **verbatim** when you have it — the shipped fixture is docs-transcribed. |
| **SPEC-201 H.4 (the staged pre-cutover message) and H.5 (`assurance` refused live with a neighbour)** | Both hand-enqueue onto a request queue, and after SPEC-200 FR-008 only the **API's execution role** holds `sqs:SendMessage` there. A laptop identity has no grant — that is the isolation working — and an agent session's production AWS writes are classifier-blocked whatever the chat authorization says. Needs an assumed session of that role driven from CI, which is where the grant already lives. Recipe: the arc script §H.4, §H.5. |

### SPEC-203's two owed checks — one of them EXPIRES

| Check | Blocker | What it takes |
|---|---|---|
| **The two membership sources agree, against a real user** (FR-007) — read `custom:shared_space_*` with `admin_get_user`, read the resolved space set out of the `logs/` record for a real request (FR-010 puts it there as a `spaces` field), compare as sets | Needs a deployed environment running `MEMBERSHIP_SOURCE=index`, and **the variable is in no Terraform** — deliberately, because FR-011 requires every environment to omit it and a module variable defaulting to `""` would make the empty-string case the live one. There is also only one environment. | Wire `MEMBERSHIP_SOURCE` into `infra/modules/api/lambda.tf`'s environment block in a non-production environment, deploy, sign in, make one request, then run `aws cognito-idp admin-get-user` for the same user and compare. The **carve-out is part of the check**: a space mid-provision holds a Cognito slot and legitimately yields no tag from the index, so it is present in one and absent from the other by design. |
| ~~**The API role's membership-index grant, simulated against the DEPLOYED role** (FR-009)~~ **DISCHARGED 2026-09-10** with `s3:prefix` supplied as context: `memberships/*` get and list `allowed`; `feedback/` and a prefix-less list `implicitDeny`. | Needs the deployed role, and every denial paired with an `allowed` control — an `implicitDeny` alone cannot tell an ungranted action from a wrong ARN. | §2.8. **Supply `s3:prefix` as a context entry** for the `ListBucket` half: a prefix-conditioned grant simulates as `implicitDeny` when it is not, because IAM answers what it decides given *your* context and never what the service supplies. Run without it, this produces a false negative on the one statement it most needs to confirm. |

> **The parity check cannot be re-run after the environment moves.** It exists because Cognito slots
> and the index both exist right now; in the successor account only one survives and a wrong
> implementation is indistinguishable from a right one. A later reader should treat a recorded
> result as **evidence**, not as a repeatable gate — and should not try to reconstruct it.

### Needs a deliberately broken deployment

| Check | Why | Recipe |
|---|---|---|
| **The runtime-config hard failure and the unparseable path** (SPEC-192) — `BootFailure` renders, **no route mounts**, the console names the missing key and **no value from the document appears in it** | Only a production build shows it: under Vitest and in `npm run dev` the fallback answers every read, so the whole suite exercises the arm that will not exist in production. It needs a `config.json` published without a required key, and a second one carrying HTML. | the arc script §A.2, §A.3 |
| **The promotion property** (SPEC-192) — change one repository variable, re-run Deploy App with no source change, read the new value on the FIRST request | The point of the whole spec, and invisible from the UI: a stale document renders a working, fully-functional portal pointed at the wrong account. | §A.1 |
| **Fresh sign-in end to end, from a private window** (SPEC-192) — proves Amplify is configured before the first render — **a cold-cookie sign-in ran 2026-09-10 in a normal profile**: a new tab, the password screen reached, `redirect_uri` accepted, one `oauth2/` fetch 200, and the deep link restored. A private window's cold HTTP cache and empty storage are what remain | A warm session cannot exercise it: the browser arrives already authenticated, and a bootstrap that configured Amplify too late looks identical. Same shape as the omitted Hosted UI host that broke fresh sign-in for a day. | §A.4 |
| **Everything the container owns about `/config.json`** — the entrypoint rendering it from the task environment, nginx's `no-store`, image promotion itself | No container exists yet; the document is a static object until SPEC-194. | SPEC-194's own checks |
| **An Excel conversion killed for memory reads the specific sentence** (SPEC-230) | notify-failure words an Excel request's `Sandbox.Timedout` and `Runtime.OutOfMemory` as *the conversion ran out of time or memory*. The first is the name production delivered; the second is the name Lambda gives an out-of-memory kill and has never been observed in this account, and the cell cap exists to make the case unreachable — so nothing a signed-in session can do will produce it. If a different name arrives, that case falls back to *something went wrong*, which is what it said before. The same sentence is also what an Excel request reads if any OTHER verb times out; describe-results makes two small calls, so that would be an outage, and the misdirection is accepted rather than guarded. | Deploy the converter at `memory = 512` in a scratch environment, save the 1,048,575 × 15 query of §4.3 as Excel, and read the error name `notify-failure` logs as `reason`. |

### DISCHARGED 2026-09-02 — SPEC-213 FR-007's rollback, exercised both ways

Run [33667798352](https://github.com/agriffi10/data-analysis-prototype/actions/runs/33667798352)
pointed all 86 functions at `9d1c8fa1`'s image; run
[33668619737](https://github.com/agriffi10/data-analysis-prototype/actions/runs/33668619737)
returned them to `1028b8b5`. Both green, and the probe passed on each.

**What makes it a real discharge rather than a green tick:** `point-lambda.sh` reads
`Code.ImageUri` back off every function and fails on a mismatch, so 86 per-function read-backs are
what the green consists of. That matters because the obvious confirmation — "main went green" —
cannot see the failure this arc is about: the `deploy-lambdas` concurrency group holds one pending
run, so a merge landing mid-exercise can evict the FORWARD dispatch and leave the fleet on the
rollback image, serving perfectly. The queue lock was held across both runs for that reason.

### The Cause reservation's escape ratio is measured on a CONSTRUCTED Cause, not a captured one

The fleet reserves twice `CAUSE_MAX_CHARS` for an error `Cause` on a state, because 32,768 is a
maximum length in **characters** on the execution-history event shapes and a Cause is a JSON
document sitting inside a JSON string. The guard measures the escape ratio and the bytes per
character of a Cause built to the shape Lambda documents, at `errors.MAX_DETAIL_CHARS`.

**The properties asserted are of the encoding rather than of that string** — which is deliberate,
because asserting a captured Cause FITS would prove nothing: a real one runs to a couple of
thousand characters and fits a 32 KiB, a 36 KiB and a 66 KiB reservation identically. So this is a
weaker premise than it looks only in one direction: a real Cause carrying a character class the
fixture has none of would escape differently.

| Check | Why it is not settled | What it takes |
|---|---|---|
| ~~**A Cause captured from a real failure escapes no worse than the reservation**~~ **DISCHARGED 2026-09-10** on nine real failed results-conversion executions: every `Cause` is ASCII; `TerminalError` causes of 749–926 characters escape at 1.070–1.075 and the timeout's at 1.071, against the 2.0 reserved. | No captured Pipes record or Lambda Cause exists in the tree, and producing one needs a production failure on a real execution — which no session can cause, and which the classifier blocks writing to production to arrange. The fixture is written from Lambda's documented shape. | Take any `RecordFailure` state from a real failed execution — the DLQ drain surfaces these, or `aws stepfunctions get-execution-history` on a failed run — and measure `len(json.dumps(cause)) / len(cause)`. Assert it against `CAUSE_RESERVATION_BYTES / CAUSE_MAX_CHARS`. If a real Cause carries multi-byte characters the fixture does not, the reservation's units need re-deriving, not just its size. |
| **The Pipes SQS record's real field set matches the model** — **RUN 2026-09-10, and it does NOT match**: real records carry `AWSTraceHeader` (95 characters, `Root;Parent;Sampled;Lineage`), which `_record` omits, and `eventSourceARN` runs to 76 characters where the model allows 57. The model's generous `receiptHandle`, group and dedup ids still net out above the 2026-09-10 records, so the cap holds for now; the model needs both fields fixed. | Same reason: the record model in `test_request_size_chain.py` is written from the service's documented shape at each field's maximum, and its reservation guard therefore measures a model against a model. | Read one `$$.Execution.Input` from a real execution and diff its keys against `_record`. A field the model omits is bytes the fleet cap does not reserve. |

### The cold-start probe's discriminator has never been observed on this fleet

The probe fails a function when its `errorType` is under `Runtime.`, when its log carries
`Status: error`, or when the log has no `^REPORT RequestId` at all. Two of those three were arrived
at by building containers from the fleet's pinned base image and driving them through the runtime
interface emulator; the third comes from AWS's documented production output. **Neither is this
account's Lambda.** The emulator is already known to diverge on exactly this path — it answers 502
with no `X-Amz-Function-Error`, where production answers 200 with one — which is why two earlier
designs passed the failure they were written for.

| Check | Why it is not settled | What it takes |
|---|---|---|
| **An init failure on this account produces a log the probe rejects** | Three designs have now been wrong about which line separates "the container did not start" from "the handler refused the payload", and each looked right until it was driven. The current rule is safe in the false-positive direction — `Status: error` never appears on a healthy invocation, so it cannot redden a good deploy — but its coverage of the failure is inferred. | Deploy a throwaway function on the fleet image whose module raises at import, `aws lambda invoke --log-type Tail` it, and decode `LogResult`. If the `REPORT` line is old-style and carries no `Status` field, an import-time exception whose class is not under `Runtime.` would pass, and the rule needs the `INIT_REPORT` signal instead — which is NOT used today because some runtimes emit it on every cold start and failing on it would redden every deploy. |
| ~~**The first real probe run's output is read**~~ **DISCHARGED 2026-09-02** | Run [33666840335](https://github.com/agriffi10/data-analysis-prototype/actions/runs/33666840335): all 14 reached their handler — six `validate-authorize` verbs refusing with `TerminalError`, two writers with `ValidationError`, `pre-signup` with `Exception`, and five returning cleanly. **This settles the false-positive direction only.** Nine of those went through the `^REPORT RequestId` branch, so a handler error demonstrably produces an anchored REPORT line in a real production tail. The failure direction is still inferred. | — |

### The cold-start probe reaches 15 of 86, and one of those is deliberately not probed

`Deploy Lambdas` invokes one function per plane plus each standalone after pointing the fleet, and
fails on an `errorType` under `Runtime.`, on `Status: error` in the log, or on no anchored
`^REPORT RequestId` line. (An earlier draft of this row said `START RequestId` — the first of three
designs the spec discarded, because it is written *before* init and regardless of its outcome.)
That is SPEC-213 FR-006, and these are the parts it does not reach.

| Check | Why the probe cannot settle it | What it takes |
|---|---|---|
| **`control-plane-dlq-drain` starts** | Invoking it sweeps all four request DLQs, **deletes** the messages it reads and emits a notification into each actor's inbox. Consuming a DLQ destroys the only copy of a dead-lettered body, and a deploy-time sweep runs it through a container that has just changed — the moment the drain is least proven. FR-006's own third criterion says to record this rather than count it as covered. | A deliberate operator invocation against a DLQ known to be empty, or a probe payload the handler recognises as a no-op. The deploy role's `lambda:InvokeFunction` grant is already there. |
| **The other 71 functions start** | The probe is a sample by design. All 86 run the **same image**, and `lambda-image-matrix.sh` imports every handler module inside it through the real runtime bootstrap — so what the sample adds is that a deployed function's *configuration* lets it start, and that is per-function. A plane-mate starting says nothing about a sibling whose environment or memory is wrong. | Invoking all 86, which needs 71 more grants; or accepting the sample, which is what FR-006 asks for. Named here so the gap is a decision rather than an assumption. |
| **A cold start specifically** | `update-function-code` discards every warm environment, so a probe straight after pointing is cold in the ordinary case — but `log-sweep` and the DLQ drain fire on ten-minute schedules and can be warm when it runs. The script reports which it observed; it does not force a cold one. | Nothing safe. A warm hit still implies an earlier successful init of the same code, because a failed init leaves nothing to reuse — weaker evidence, and the script says so rather than implying more. |

### SPEC-210's dark-mode checks — ONE DISCHARGED 2026-09-01, one now owed for a NAMED reason

| Check | Why the suite cannot settle it | What it takes |
|---|---|---|
| ~~**Monaco keeps the cursor and the scroll position across a theme switch**~~ **DISCHARGED 2026-09-01.** Dark → Light with 25 lines, the cursor mid-line on line 21 and the editor scrolled: the **DOM node was identical** (not re-created), scroll `-146px` → `-146px`, cursor top **412px** / left **77px** unchanged, text identical. The cursor's `visibility` went `hidden` on blur — refocusing the edit context *without clicking* restored it at exactly 412px/77px. | `SqlEditor.test.tsx` stubs the editor, so it can assert the buffer and that the editor was not re-created — a **count**, mutation-tested — but there is no cursor and no scrollable viewport in jsdom to lose. | Ran: `e2e.md` §4.16 step 4. |
| **No flash of the light theme before the first paint** — **the STRUCTURAL half is discharged (2026-09-01); only the perceptual half is owed, and NOT from an agent tab** | The pre-paint initialiser is asserted three ways offline, and all three were then confirmed **on the deployed origin**: `/theme-init.js` is a **200** with `Cache-Control: no-cache`, external and render-blocking at **script index 0** ahead of the module script, and **no `<script>` in the production document has a body** — the half only a deployed page proves, since an inline initialiser works in dev and is refused by `script-src 'self'`. A hard-reloaded `/query` arrives with `data-theme="dark"` already applied, no console error, no CSP refusal. What remains is only *"there was no white frame"*. | **Not runnable from the agent's browser tab**: it is backgrounded, so Chrome never paints it — `performance.getEntriesByType('paint')` returns an **empty array**, and one run reported first-paint at **12,512 ms**. There is no frame sequence to observe. Needs a **foreground** tab: a human watching a hard reload, or a screen recording. |

### The undersized-target register — SWEPT 2026-09-01, and TWO ENTRIES FAIL

`src/lib/targetSize.test.ts`'s `ACCEPTED_UNDERSIZED` names every interactive control whose own size
class — or, for a checkbox or radio, its ABSENCE of one — puts it under WCAG 2.2 SC 2.5.8's 24×24
CSS px floor. **Read the register for the population; it is deliberately not counted here**, because
a number in prose goes stale on the first correct fix with nothing to catch it.

**Being under the floor is not a violation.** The spacing exception exempts a target nothing else
comes within a 24px-diameter circle of, and that is geometry no suite here can do. The recipe is
`e2e.md` §4.13; measure the **centre-to-centre** distance to the nearest other target, not just the
box.

**What was measured, and what that measurement is worth.** A pass over the register was run in a
browser at the 14px root, against the built stylesheet, on markup **reproduced from source** — not
on the running app. That is enough to settle geometry that depends only on a control and its own
container, and it is *not* the live check: a parent the reproduction did not include could change a
distance. Every figure below is from that pass. **The residual owed against each one is the same and
is stated once here** — confirm it in the deployed app rather than in a harness. An entry's `why` in
the register carries its number, so the two do not drift.

**How the 2026-09-01 sweep measured it, because the numbers below depend on it.** For each target
under 24×24, find the neighbour with the least slack, applying the exception's two halves
separately: against a neighbour that is itself ≥24, a 12px radius from the target's centre must not
reach that neighbour's **box**; against a neighbour that is **also** undersized, centres must be
≥24 apart. One guard is not optional — an `elementFromPoint` hit test excluding elements lying
**behind** an overlay. Without it the Colours panel reported a violation against the `Generated SQL`
row underneath it, and any future sweep will invent the same class of phantom.

#### Confirmed failures — fix or accept, but they are no longer open questions

All three are pairs of **mutually** undersized targets, so no verdict turns on the contested
enclosing-target reading. The third was added on 2026-09-10, in the live app.

| Surface | Measured 2026-09-01, the third 2026-09-10 | Shortfall |
|---|---|---|
| **The Data Explorer column header** — `ExplorationGridHeader.tsx:78` | Every column pairs a `Column options` trigger at **18.55 × 21** with a `Resize column` handle at **10.5 × 39**, centres **9.32px** apart. Both undersized, so the spacing exception cannot apply to either. The enclosing `<th>` is 347.01 × 40 and is *not* itself undersized, so it is not what decides this. Reproduced on **all four** columns of a four-column result. | **−14.68px** |
| **`CalcPanel`'s aggregate checkboxes** | Ten **13 × 13** checkboxes; the aggregate list (*Count, Count distinct, Count nulls, Sum, Average, Minimum, …*) stacks at exactly **19.5px** vertical pitch, all sharing an x. **Nine** adjacent pairs fail. | **−4.5px** |
| **`StripingControl`** — the Colours dialog's *Band rows by* fieldset | With four columns one row, slack +18.51. With **twenty** (a view made for the check) its **13 × 13** checkboxes wrap into four rows at **19.5px** pitch, centre to centre 19.5px — the harness prediction, now measured live. The same class as `CalcPanel`. | **−4.5px** |

#### Confirmed overlap, already a settled design decision

| Surface | Measured 2026-09-01 |
|---|---|
| **The tab-strip closes** — `ExplorationTabStrip`, `QueryTabStrip` | **FIXED, and the earlier reading of this entry was wrong.** The measurement stands — a **21 × 21** `span` inside a `role="tab"`, so the spacing exception cannot rescue it — but "cannot be rescued by the exception" is not "cannot be fixed": a target that IS 24 × 24 needs no exception, whatever encloses it. Both ✕ are now `h-[24px] w-[24px]` and conform outright, with the tab left at `h-7`. Raising the tab to `h-8` was tried and reverted: it removes a 0.75px overhang where the ✕'s hover fill paints onto the tab's 1px border, and costs a visible 3.5px mismatch against the `+`, the bar buttons and `ResultTabs`. Still owed from this pass: tab-to-tab spacing, since only one tab was open — **half settled 2026-09-10**: with two tabs in `ExplorationTabStrip`, each ✕ is exactly 24 × 24, 111.59px apart, tabs 24.5px tall with a 3.5px gap, and nothing is undersized. **`QueryTabStrip`'s is still owed.** |

#### Measured and exempt — resolved, do not re-open

| Surface | Measured 2026-09-01 | Slack |
|---|---|---|
| `OrderFilterDialog` | Eight **13 × 13** checkboxes, **56px** row pitch | +24.41 |
| `RowColoursDialog` | Five **13 × 13**, worst pair 63.59px apart | +39.59 |
| `GroupingPanel` | Two **13 × 13** | +6.50 |
| `TransformersDialog` | **Zero** undersized targets in its default state | — |
| Columns drawer | Move-earlier / move-later **32.16 × 28**, close **28 × 28** | — |
| `FileListTable` header + rows | Row checkboxes **14 × 14** at **42px** pitch; *Select all* **14 × 14**. The binding neighbour is the **adjacent row's checkbox**, not the enclosing row link — the half previously computed rather than measured | +18 / +34.5  **One open disagreement, recorded rather than resolved:** the enclosing `<li>` carries `onDoubleClick` to download and measures 876 × 42, so under the enclosing-target reading the row checkbox has centre-to-box 0 and fails. This pass deliberately does not lean on that reading, calling it contested, and settles the entry on the adjacent-row pitch instead. Both are written down because the register should not look settled while the reading it turns on is not. Either way the static sweep is blind to the row: `POINTER_HANDLER` matches `onClick`/`onPointerDown`/`onMouseDown`, not `onDoubleClick`. |
| `SelectionToolbar` | All buttons **28px** tall, ≥75 wide at desktop widths; between 900 and 1299, where the glyphs give their room to the words, the narrowest is Copy at **46.7** wide | — |
| `SendFilesDialog` | Two **14 × 14** radios **69.1px** apart, confirmed by direct measurement as well as by the sweep | — |
| `Chip` remove ✕ | **Exactly 24 × 24**, **153.71px** apart on a row; with the earlier 31.75px wrapped figure, both axes are now measured | pin holding |
| Divider ▲/▼ (SPEC-209) | **Exactly 24 × 24** each — the absolute pin, not the 24.5 a `h-7` restyle would give | — |
| Theme controls (SPEC-210) | Header button **28 × 28**, drawer options **24.5**, menu row **32** — the menu row has no height class and the static sweep cannot see it | — |

#### Still owed

| Check | Why it did not run |
|---|---|
| ~~**`AdvancedCopyDialog`**~~ **MEASURED 2026-09-10, exempt by one pixel** — the dialog opened ("Copy selection", seven cells selected) as the positive control; three **13 × 13** checkboxes at **25px** centre to centre, slack **+1**. A tighter row pitch would fail. | *Copy…* carries `aria-disabled="true"` without a cell selection. An early probe recorded it as "0 undersized" when the dialog had simply never opened — **take a positive control before recording any zero here.** |
| ~~**`StripingControl`**~~ **MEASURED 2026-09-10 — a FAILURE, moved to *Confirmed failures* above.** It is the Colours dialog's *Band rows by* fieldset. | Not separately locatable from the Options menu; it may live inside Colours. Identify the surface first. A HARNESS — reproduced markup, not the running app — puts it at **19.5px** centre-to-centre between wrapped `gap-y-1` rows, which would make it a failure. Treat that as a reason to go and find the surface, not as the measurement. |
| ~~**`RefreshTableDialog`, `TableShareDialog`**~~ **MEASURED 2026-09-10, both exempt** — `RefreshTableDialog`'s one 14 × 14 checkbox at slack +175.74; `TableShareDialog`'s two 14 × 14 radios at +30.75. | Not reached this pass. Arithmetic from source at best. (`Toast` and `TableActionsMenu` were on this row and have left the register: both are `h-[24px] w-[24px]` now. Neither was failing — a harness put them at 37.8px and a 14px centre-to-box — so those two are robustness, not fixes.) |
| ~~**`FileListRowMobile`**~~ **MEASURED 2026-09-10 at 700px, exempt** — **14 × 14** row checkboxes at 49px pitch, worst slack +7.25 against the row's *Open folder* target. Two apparent failures were rows **behind** the fixed mobile action bar, which a hit-test confirmed, and the last row scrolls clear of it. **Exclude occluded targets before recording a failure here.** | Needs a width below 900px on `/files`. Reachable now — see the corrected `resize_window` trap in `e2e.md` §1 — just not run. |
| **The breadcrumb trails** — `DestinationPicker.tsx:282`, `FileBrowser.tsx:265` | **DECIDED and FIXED.** The Inline exception does **not** apply: a trail is not a sentence, and its size is not constrained by the line-height of non-target text — measured, flooring a crumb takes it 18 → 24px while the `/` beside it stays at its own 18px line-height and the row simply grows. A constraint you can lift by editing one class is not a constraint. This pass's own point is preserved and was right: with ordinary folder names the horizontal axis is not in question (68.44px apart), and 22.56px is the **wrapped** trail's line pitch. The two axes fail for different reasons — the vertical whenever the trail wraps, the horizontal only with very short names, where a one-character folder (legal: `validateLeafName` forbids only empty, untrimmed, `/` and control characters) draws a **7.3px-wide** box with 22.82px between two of them. `min-h-[24px] min-w-[24px]` covers both. ~~**Still owed:** confirm on a wrapping trail in the live app, which this pass could not produce — the deepest path available was three crumbs.~~ **Confirmed 2026-09-10** on a seven-level trail at 700px: two lines at 27.5px, every crumb 24px tall, long crumbs capped at 160px and truncated — it conforms outright. |

### Needs 400px (the Safari half retired 2026-09-01)

| Check | Note |
|---|---|
| **The whole CSS list** (`e2e.md` §4.15) — **the engine premise is retired; the list itself is still owed at 400 px.** The deployment's audience has no Safari (Andrew, 2026-09-01), so a Chromium pass discharges the list. No Chromium pass of the whole list has run at 400 px yet — the band below 606 px needs the device toolbar, per the next row. | ~~A Chromium run **corroborates and cannot discharge** rendering. Andrew browses in Safari.~~ Andrew's own Safari use is corroboration, never a gate. |
| **The 400px pass** | Not reachable by window resize on macOS — Chrome's floor is 606px. Use DevTools device toolbar (⌘⇧M) and assert on `matchMedia`. **Corrected 2026-09-01:** `resize_window` is *not* inert — the window really resizes, but a **backgrounded tab reports a stale `innerWidth`** (and `outerWidth` 0), which is what earlier passes read as "changes nothing". Widths between 606px and desktop ARE reachable, and the 700px drawer rows were run that way; only the sub-606px band still needs the device toolbar. **Sharpened 2026-09-09** — the mechanism is §1's stale-viewport trap in [`e2e.md`](e2e.md), which now carries both conditions; `e2e.md` §4.11's read-only rows were run at 606x732 that way, with both compiled breakpoints reading `false`. |

### SPEC-196's live verification — PARTLY RUN 2026-08-27, the rest owed

**Six items ran on 2026-08-27** and are struck through below, with the evidence in
[`sessions.md`](sessions.md). **§E items 1 and 9 — the trust statement and the IAM simulation
against the deployed roles — were discharged on 2026-08-31 by SPEC-202 FR-010**, which is the
overlap the arc script recorded deliberately: whichever ran first discharged both. Row for row
against SPEC-196's pre-retirement table, with no row changed; the evidence is the ported execution
log in [`sessions.md`](sessions.md). The rest of §E is still owed (see the note at the top of this
section for where that script lives now).

The 2026-08-27 decision to run Arc B's live verification once at SPEC-202 was **narrowed for this
section**: SPEC-197 deletes the probe routes §E is driven through, so running it at 202 would have
meant deleting the only instrument that can observe the isolation model before it was ever observed.

**The probes are gone now, so what remains needs a different vehicle** — noted per row. Recorded as
rows rather than as one line because a later reader settling some of them needs to see which are
still open.

| Check | Why it is owed |
|---|---|
| ~~**The ID token really carries the claims** (§E.0)~~ **DISCHARGED 2026-08-27** — `cognito:username` and `custom:shared_space_1` both present. | Every offline test supplies its own claims. The inference from `identity-pool.tf` is strong — AWS reads those very claims out of this very token today — but a token that did not carry them would pass the entire suite and fail on the first real request. **Run this first**; if it fails nothing else in the section matters. |
| ~~**The trust policy admits the API with BOTH actions** (§E.1)~~ **DISCHARGED 2026-08-27** — `/_identity/self` answered 200, which needs both. | `sts:AssumeRole` without `sts:TagSession` renders, plans, applies and unit-tests green. |
| ~~**The `username` tag is actually stamped** (§E.2)~~ **DISCHARGED 2026-08-27** — `ownPrefixListable: true`, unreachable without the tag. | Behavioural only: this account records **no `AssumeRole` event anywhere** — the one trail carries data events on the archive bucket alone — so a criterion phrased against CloudTrail cannot fail. §E.6's `ownPrefixListable` is the observation. |
| ~~**The ten SLOT tags are stamped** (§E.2, second half)~~ **DISCHARGED 2026-09-10** by the call this row names: a user-plane upload, listing and download in a shared space the caller belongs to all succeeded through the API — a bucket with no policy, so the slot tag is the whole gate. There is no paired negative through the API: a space the caller is not in is refused by the route's own membership check before any S3 call, so it does not reach the tag. | **SPEC-196 cannot discharge this at all.** Every call it ships touches the user-space bucket, and `spaceCount` comes from the token's claims — it reports the same number with every slot tag dropped. Settled by the first user-plane call against a shared space the caller belongs to, where the bucket has no policy and the tag set is the entire gate. **Passed to SPEC-198.** |
| ~~**The bucket-policy allowlist admits the assumed session** (§E.3)~~ **DISCHARGED 2026-08-27** — the probe made the call. | `simulate-principal-policy` does not fetch a bucket policy, so `aws:PrincipalArn` resolving to the role's IAM ARN under `sts:AssumeRole` — rather than `AssumeRoleWithWebIdentity` — needs a real call. The probe is that call. |
| ~~**Lake Formation still authorizes the session** (§E.4)~~ **DISCHARGED 2026-08-30** — `SELECT` on the caller's own database returned 2 rows through the API. The FAILED foreign query's `stateChangeReason` also named the principal as `assumed-role/dat-portal-user-role/agriffith`, which is independent evidence the role is reused and the session name is the username. | LF is not modelled by the simulator, and confirming it needs one Athena query on the user plane. **There is no route until SPEC-199**, which discharges it. Running it from a laptop proves nothing: the local IAM user is a different principal. |
| **The credential cache does not leak in a warm container** (§E.5) | Needs two callers interleaved in one execution environment, confirmed by a shared `logStream` — otherwise the observation is two cold starts and proves nothing. The offline sequence pins the algorithm; it cannot pin the runtime. |
| ~~**Both probe booleans** (§E.6)~~ **DISCHARGED 2026-08-27** — `own: true, foreign: false`, the conjunction. | The whole point is the conjunction. Recording only `ownPrefixListable` would pass with the isolation model deleted. |
| ~~**A real `env` and a real build sha in the records** (§E.7)~~ **DISCHARGED 2026-08-27** — `env: "prod"`, a real sha, on all 44 records. | The stamp is written into the deployment package by the deploy script; offline the resolver returns the unstamped value, so only a deployed invocation can show a real sha. |
| **The propagation delay is unchanged** (§E.8) | Both halves are required: refusing before a refresh alone is indistinguishable from a broken grant, and succeeding after one alone from a grant that was always live. |
| ~~**The twelve-row IAM simulation against the DEPLOYED role** (§E.9)~~ **DISCHARGED 2026-09-09 by running the twelve rows**, against `dat-portal-user-role`, one resource per call, running the table's own twelve rows and its own expectations: GetObject alice/bob; ListBucket with `s3:prefix` alice/bob; DeleteObject on an ordinary key versus `DO_NOT_DELETE.txt`; PutObject on `alice/archive/`; `glue:GetTable` on database alice/bob; and the three shared-space slot-tag rows, including **slot tags absent** to `implicitDeny`. **Twelve expected verdicts, twelve matches, zero mismatches.** Nine of the twelve are paired allowed/deny within the table; the `PutObject alice/archive/` row has **no** PutObject control among the twelve — SPEC-196's table does not supply one — so its control is the separate `PutObject alice/notes.txt` → **allowed** run in this session's FR-004 rows. Saying "every denial paired with a control" of the table as written would overstate it. **An earlier draft of this line struck the row on SPEC-202 FR-010's 2026-08-31 re-simulation, and that was wrong** — the section intro does claim it, but the ported Arc B evidence covers GetObject/PutObject alice-versus-bob and nothing else, so it would have retired a twelve-row check on about two of them, while `DO_NOT_DELETE` (row 6) sat a few lines above still marked open. **A section intro saying a thing was discharged is not evidence that it was.** Evidence: [`sessions.md`](sessions.md) 2026-09-09. | — |

### Identified by review, deliberately not built, with a reason

| Item | Disposition |
|---|---|
| **A `ForAnyValue:StringEquals` floor on the trust statement's `sts:TagKeys`** (SPEC-196 FR-003) | `ForAllValues` is a **ceiling**: it is satisfied by a request carrying a subset of the listed keys **and equally by one carrying none**, so the statement permits a tagless `AssumeRole` and cannot require that `username` was stamped. A `ForAnyValue` clause alongside would read "a subset of the eleven, and at least the username key". **Not added in SPEC-196**, deliberately: that spec ships zero live verification, the bug it guards (one that drops the whole tag list) already surfaces as `AccessDenied` everywhere, and adding an IAM condition every user's every request depends on — one that cannot be exercised until SPEC-202 and can only fail closed — trades a named risk for an unnamed one. **Land it with SPEC-198**, when a live call can prove it. |
| **A credential written into an exception message is not redacted** (SPEC-196 FR-009) | The mechanism is **preventative**: an AST sweep forbids this repo's code from rendering the event, the headers, a token or any of four session-material names into an f-string, a `%`-format, a `.format()` call or a `raise` argument, and a sentinel test drives a path that genuinely raises through the span while holding a real assumed session. **No redactor exists** — `log-foundry` exposes no way to turn stack capture off, re-verified against the pinned version and asserted by a test — so a future route that interpolates a session value *despite* the sweep would still reach the log store. Settled 2026-08-27; revisit if the library gains an opt-out, and do not delete the sweep. |
| **A presigned URL signed from a cached session dies with that session** (SPEC-196 FR-006) | The credential margin is sized for the life of **one request**, so a URL signed with 29 s of credential left is valid for 29 s and not for its stated expiry. Nothing in the API presigns today and a tripwire asserts it, so the spec that first does must revisit the margin rather than inherit a silently wrong one. **Passed to SPEC-198.** |
| **A recreated API execution role would silently break the trust policy** (SPEC-196 FR-003) | IAM stores a trust policy's principal as the role's **unique id**, not as the ARN written. If that role is ever destroyed and recreated — a project or environment rename, a taint — the rendered ARN is unchanged, Terraform shows no diff, never rewrites the trust policy, and every API request refuses against a dead id. No offline assertion can catch it and no plan shows it. A tripwire pins the shape (exactly one AWS principal in the policy) so a reader chasing a blanket refusal has one place to look; the real check is a live one after any rebuild. |
| **The API plane's declaration mechanism has no live subject** (SPEC-196 FR-005) | `api_client` has no caller in shipped code, and both `ROUTE_PLANES` entries are empty, so the runtime guard is exercised only by synthetic test routes. Forced: assuming happens for every route, so it cannot go through a door that refuses undeclared ones. The first real subject is SPEC-200's queue writes. |
| **The single expiry retry does not cover a paginator** (SPEC-196 FR-006) | It proxies direct method calls; a paginator, a waiter and anything reached through `meta` hold their own client reference. Fail-closed, not a leak. A tripwire asserts no route paginates, so the limitation is announced rather than discovered. |

### Tab-scoped Cognito tokens — the change that touches what a warm session cannot test

Amplify's token storage moved from `localStorage` to `sessionStorage` (2026-08-27, at Andrew's
direction, outside SPEC-197's scope and shipped as its own commit). It changes **sign-in**, which is
the one path a signed-in session cannot exercise — so it ships with rows rather than a claim.

**Three of the four ran on 2026-08-31** — a new tab arrived signed out, and one click carried it
through the Hosted UI and back. Evidence in [`sessions.md`](sessions.md).

| Owed | Why it is not settled offline |
|---|---|
| ~~**The Hosted UI redirect still completes**~~ **DISCHARGED 2026-08-31** — `POST {domain}/oauth2/token` ran in the returned document, and all five token keys landed in `sessionStorage` with `localStorage` holding only `oauthSignIn`. The two stores did not fight. | The offline tests assert which store the provider is given; they cannot exercise a real authorization-code round trip. Amplify keeps the OAuth `state` and PKCE verifier in its own store, so the two halves are now in different stores — that is expected to be fine and has not been observed. **Sign in FRESH, in a private window.** |
| ~~**A second tab signs in cleanly**~~ **DISCHARGED 2026-08-31** — a brand-new tab rendered the signed-out landing page, and Sign in returned it signed in as `agriffith`. | The intended cost of the change, and it must be confirmed to be a clean sign-in rather than a broken one: open the portal in a new tab of the same window and confirm it lands on the Hosted UI and returns signed in. |
| ~~**A deep link in a new tab returns to the link**~~ **DISCHARGED 2026-08-31** — `/files?prefix=agriffith/` in a fresh tab bounced to the landing page leaving `portal.returnPath` in `sessionStorage`, and sign-in landed back on that path **with its query string intact**. | `lib/returnPath.ts` restores the intended path after sign-in; with per-tab storage the new tab has no session, so the restore now runs on a path that previously never needed it. |
| **SPEC-192's fresh-sign-in check is RE-INVALIDATED** — and 2026-08-31 did **not** settle it: the Cognito session cookie was warm, so no password screen was reached. What ran is the **code exchange**, not the credential prompt. **2026-09-10 settled the tab-scoped half**: a new tab with a cold Hosted UI cookie reached the password screen and completed the code exchange (200) under tab-scoped storage, and the deep link was restored. What is left is the private window's cold HTTP cache — the SPEC-192 row above. | It was recorded against browser-wide storage. Whatever it discharged about first-load sign-in must be re-run under tab-scoped storage. |

**Learned on 2026-08-31, and it makes the private-window rows cheaper than they read:** a tab whose
session is gone re-signs-in with **one click and no password** while the Cognito Hosted UI cookie is
live. That is what makes breaking a session a recoverable experiment rather than a session-ending
one — but it is also why a warm-cookie sign-in **cannot** discharge anything phrased against a
*fresh* sign-in.

### SPEC-197's live verification — MOSTLY RUN 2026-08-30

**F.1, F.3, F.4 and F.6 ran on 2026-08-30**, with F.2's header half; evidence in
[`sessions.md`](sessions.md). The rows below are struck through as they were settled. What remains
is unrun rather than unobservable, which is why it is not in the section below.

| Owed | Why it is not settled offline |
|---|---|
| ~~**The preflight is answered, in a browser** (SPEC-197 FR-010)~~ **DISCHARGED 2026-08-30** (it read PARTLY until its Safari half was retired) — `OPTIONS` returns 200 listing exactly `authorization,content-type,x-request-id`, and every bearer-carrying cross-origin `fetch` in the session succeeded. **In Chromium.** ~~Safari is owed.~~ The Safari half is retired at its premise (the audience has no Safari, 2026-09-01). | Found broken live on 2026-08-27 and fixed in the router: `$default` matches `OPTIONS`, so API Gateway's own CORS responder never saw a preflight and the Lambda refused it deny-by-default. Every bearer-carrying `fetch` then failed as an opaque `TypeError`. `curl` cannot settle it — only a browser enforces CORS — and the offline tests assert the router's answer, not the browser's acceptance of it. |
| ~~**Suggestions RENDER from the ported route** (SPEC-197 FR-013)~~ **DISCHARGED 2026-08-30** — real names in all three dialogs; two of them shared one `GET /v1/user-directory`. | A `200` with an empty array looks identical to a healthy but empty directory, so the assertion is on the rendered NAMES, from a fixture known to be in the document, in all three dialogs — `AddMembersDialog`, `TableShareDialog`, `SendFilesDialog`. |
| ~~**The isolation proof against a PER-USER route** (SPEC-197 FR-014)~~ **DISCHARGED** — SPEC-198 FR-013's paired 403/200 settled it on 2026-08-30, and 2026-09-10 re-confirmed it on `GET /v1/objects`: own space 200; another user's and a nonexistent user's both 403 with the same detail. | `GET /v1/user-directory` cannot carry it and does not claim to: the `ReadTheUsernameDirectory` grant is unconditioned and the document is byte-identical for every caller, so the route returns the same bytes with the principal tag dropped. **Passed to SPEC-198's first per-user route.** |
| ~~**The browser's refresh-once path** (SPEC-195 FR-008)~~ **ARITHMETIC DISCHARGED 2026-08-31, the genuine 401 still owed.** With every `/v1/` response replaced by a synthetic 401 in the envelope's own shape: **exactly two** API requests for one gesture, **one** `cognito-idp` refresh between them, **zero** `cognito-identity`, no third request, the user not signed out and no banner. With the refresh broken as well (every `cognito-idp` call answered `NotAuthorizedException`): **one** request, one failed refresh, and **no second request at all** — the provider returns null and `apiRequest` exits before the retry is sent, so the script's *"the retry 401s and there is no third request"* names a shape this code cannot produce. **What is still owed is the 401 coming from the API rejecting a real expired bearer** — the 401 here was injected client-side, because reading or corrupting a stored token is refused by the agent's own classifier and should stay refused. | The 2026-08-30 lesson stands: Amplify refreshes **proactively** on the next gesture, so an aged token never reaches the retry. The refresh must be **broken**, not merely expired. |

### SPEC-198's live verification — PARTLY RUN 2026-08-30

**Most of the SPEC-198 block of [`e2e.md`](e2e.md) §4.2 ran on 2026-08-30** — the per-gesture call
count, the per-file presign, the XHR transfer against the regional host, both isolation 403s with a
paired 200 control, the archive-write refusal, the CORS trio (as it then stood — three origins,
including the CloudFront rollback one) and the log record. Evidence in
[`sessions.md`](sessions.md). What is below is what remains — **and see the re-run the origin
narrowing owes, in the SPEC-202 section**.

| Owed | Why it is not settled offline |
|---|---|
| **The presigned URL's expiry is evaluated at request RECEIPT, not at completion** (FR-005 AC8) — **not reachable on Andrew's uplink (2026-09-10)**: 240 MB uploaded in about 17 s, so the 5 GB per-file cap finishes in about 6 minutes, inside one 900 s window. A throttle only helps if **one 112,500,000 B part outlasts its own 900 s URL**, which means under about 125 KB/s: each part is minted just before its `PUT`, so a throttle that merely stretches the whole file past 900 s re-mints every part and tests nothing. A throttled single-URL download of a large object is the other vehicle. | The premise the whole single-`PUT` design rests on. **Still owed, and deliberately still worded this way.** SPEC-216 makes the UPLOAD design correct under either reading — a part is sized to finish inside half its window on the slowest supported uplink, so no part depends on a long transfer — but that is not the same as knowing which reading is true, and the premise still governs a presigned **download** of a large object, which SPEC-216 does not touch. The check itself is now: **a multipart upload of a multi-GiB file completes**, past the 900 s window, with per-part re-minting (`e2e.md` §4.2's multipart block). If it were false, every large upload would fail at the tail with an opaque 403 **after the user waited** — and with `UPLOAD_CONCURRENCY` 3 a deep queue would put that failure on the files they waited longest for. |
| ~~**A presigned URL signed INSIDE a Lambda by an assumed session is honoured by S3**~~ **DISCHARGED 2026-08-30** — two uploads redeemed against `dat-prod-user-space.s3.us-east-1.amazonaws.com` and both returned 200. | Signing is a local SigV4 operation, so offline it always "works"; whether S3 accepts the resulting signature at redemption is a fact about the account. |
| ~~**A browser preflight against the deployed bucket CORS succeeds from the container origin** (FR-011)~~ **RE-DISCHARGED 2026-09-10 in Chromium, both buckets**: a real upload and download from the portal origin, each `PUT` 200 with `ETag` readable cross-origin, each read-back a `cors` fetch of the exact bytes. The Safari half is retired at its premise. — **RE-OWED 2026-09-02.** The discharge below is **pre-narrowing evidence**: it was observed against three admitted origins, one of which was a distribution that no longer exists. Merge 2 narrowed both buckets' CORS, and ~~**no browser has redeemed a presigned URL since**~~ no browser redeemed a presigned URL until the 2026-09-10 run above — the 2026-09-02 pass was CLI-only, and a preflight is not observable from `curl` against a bucket that answers the request anyway. **This is the only check that detects the bucket-CORS narrowing**, and a wrong narrowing presents as an opaque browser `TypeError` that reads as "the API is down". Discharge it with one real upload **and** one real download from `$APP_URL`. *Superseded discharge follows.* ~~**DISCHARGED 2026-08-30 in Chromium** — two presigned `PUT`s completed from the container origin, and the three-origin `curl` returned an ACAO for the SPA origin and for `d1kbh4bnvh1je8.cloudfront.net`, none for a foreign one. **Safari owed.**~~ | A CORS failure is an opaque `TypeError` and presents as "the API is down". `curl` cannot see it — only a browser enforces CORS. |
| ~~**The live 403 on a foreign prefix** (FR-013)~~ **DISCHARGED 2026-08-30** — foreign personal space and a foreign shared space both 403 `AccessDenied`, with the caller's own prefix answering 200 as the paired control. | The **zero-call** half is taken offline, by call count, in `test_objects_routes.py` — a route that resolved the prefix from the request and let IAM refuse would return an identical 403, so the live half proves the deployed route refuses and nothing more. The credential-layer half is **SPEC-196 Phase 5 item 6's dated `_identity/self` result, cited rather than re-run**. |
| ~~**`owed.md` §2.1's bucket-policy Deny on a marker key**~~ **CLOSED — the other half was settled on 2026-09-09** by the paired `DO_NOT_DELETE.txt` simulation in the CLI table above; the Deny lives in the role's policy, not a bucket policy. — **HALF DISCHARGED 2026-08-30, and the half that ran is not the half that was owed.** `DELETE /v1/objects` on the marker is 403 in a personal *and* a shared space, with an ordinary file in the same folder written and deleted as the control. But the `detail` is *"folder markers may not be removed or replaced"* — the **route's** wording. The route refuses before S3 is asked, so ~~the **bucket-policy Deny is still unexercised** and~~ the Deny is not reachable from this API at all; the simulation named above is what exercised it. |
| ~~**An intermediate upload percentage, in a real browser**~~ **DISCHARGED 2026-08-31** — a 7.0 MB upload fired **seven** `xhr.upload` progress events at **19, 23, 36, 53, 71, 87 and 100 %**. Six intermediate values, from one presign and one `PUT`. | Asserted offline against a stubbed `XMLHttpRequest`. What is not observed is that a real `xhr.upload` fires progress events for this transfer — the one thing a `fetch` implementation would silently lack. |
| **A multipart upload's abort actually lands during SIGN-OUT** (SPEC-216 FR-004) — **the navigation variant landed on 2026-09-10**: because the shell remounts on every route change (a defect, tracked in the table at the top of §1), leaving Files mid-upload unmounted the provider, and its `POST /v1/objects/upload/abort` returned 200. The sign-out variant — the session torn down in the same moment — is still owed. | The queue provider aborts everything in flight when it unmounts, which happens on sign-out. For a multipart upload that abort is an **API request needing a bearer**, fired from an unmounting component while the session is being torn down — so whether it reaches the API is a race an offline test cannot settle, and the test environment answering it proves only that the call is made. Not a correctness bug either way: the bucket's seven-day `abort_incomplete_multipart_upload` rule is the backstop, and FR-004 already declines to guarantee the abort. Recorded so the cost is known rather than discovered on a storage bill. Steps: start a large upload, sign out mid-transfer, then `aws s3api list-multipart-uploads` with an operator credential. |
| ~~**The AGGREGATE upload percentage, in a real browser** (SPEC-216 FR-003)~~ **DISCHARGED 2026-09-10 in Chromium**: a 240,000,000-byte, three-part upload with part 2's first `PUT` failed at 25% by client-side injection — the app's own `'error'` listeners fired, because an abort would take the cancel path. The bar, sampled 223 times, never decreased. Each part was minted just before its `PUT`, the failed part re-minted and re-sent once, `ETag` readable on every part. | A DIFFERENT and harder claim than the discharged row above it, which is why that one is left standing rather than re-pointed — re-pointing a discharged row erases a check that was actually run. That one settled that a single `PUT` fires intermediate `xhr.upload` events. This one is about the aggregate across parts: it must rise past one part's worth and **never fall**, including across a RETRY, where last-value-wins makes the bar drop and a running sum makes it over-report. Offline the three implementations are separated by a fixture firing several progress events per attempt with the retry starting small — measured: with one full-size event per attempt all three agree and every mutation passes. What is owed is that a real browser's event sequence has the same property. Steps: `e2e.md` §4.2's multipart block. |
| **The SPEC-159 quarantine sequence end to end** | Needs a deliberately corrupted `query-history.json` in a real prefix. **The route will write one** (`PUT /v1/objects/content`), **but the agent harness refused to corrupt Andrew's history** on 2026-09-10 — it needs his explicit go-ahead, or his own hand. |
| **The presigned-URL leak sweep has never run against the string production emits** — found 2026-08-31 | Both presigned URLs this API mints **were SigV2 when this was found**: the query carried `AWSAccessKeyId`, a 28-character `Signature`, `Expires` and `x-amz-security-token`, and contained **no `X-Amz-Signature` and no `X-Amz-Expires`**. **The version is pinned to SigV4 as of 2026-09-01** (`identity.S3_SIGNATURE_VERSION`), so the shape has changed and every sweep now names BOTH families — `X-Amz-Signature`, `X-Amz-Credential`, `X-Amz-Security-Token`, `AWSAccessKeyId`, `x-amz-security-token` and `Signature=` — precisely so it cannot go unfailable again the next time the version moves. Every offline fixture fakes `generate_presigned_url` and returns a v4-shaped string (`test_presign.py`), and both live sweeps — `e2e.md` §4.3 and `arc-b-api-container-e2e.md` §4 step 4 — search the day's records for `X-Amz-Signature`. **That substring cannot appear**, so the 2026-08-30 sweep of 470 records could not have failed, and a presigned URL sitting in a log would have passed it. **The corrected sweep RAN 2026-08-31 and is clean:** `AWSAccessKeyId`, `x-amz-security-token`, `Signature=`, `X-Amz-Signature`, a JWT shape and an email shape all **zero across 1,605 records** in `logs/service=api/` for the day — with the positive control that the window really did contain presign mints, six `key_length` records (the key's *length*, never the key). A presigned URL is a bearer token, so this is the check that matters most on that path, and it had never actually been run. |
| ~~**Nothing pins the S3 signature version**~~ **DISCHARGED 2026-09-01** — `identity.S3_SIGNATURE_VERSION = "s3v4"` is now passed at the single client construction site, with a test that reddens when it is removed and that also covers the endpoint pin, which had no test at all. **The ledger's own recommendation below — route this through a spec — was considered and overtaken:** the defect was measured live on a real upload and a real download, the fix is one keyword at one site, and `transition_plan.md` §5.5's G9 row already documents SigV4 presigning as the property this application depends on, so pinning it narrows the gap between doc and code rather than deciding anything new. Recorded here rather than in a commit message alone because this row is where the next reader will look. | The S3 client *is* given a botocore `Config` (`identity.py`'s `S3_ENDPOINT_CONFIG`), so a reader who greps `Config(` finds one — but it sets `addressing_style` and `us_east_1_regional_endpoint` and **no `signature_version`**, and that word appears nowhere in `lambdas/` or `infra/`. The v2 shape above is botocore's default, not a choice this repo made. A botocore bump that flips the default changes every minted URL's shape with the whole suite green, because the only assertions naming that shape are fakes this repo wrote. **Whether to pin `s3v4` is a decision for a spec, not for the ledger** — recorded here so the next reader does not rediscover it from a broken upload. |
| ~~**Recorded as OWED with no check to write:** part-level retry behaviour — there is none, by design (FR-005 AC6)~~ **SUPERSEDED by SPEC-216** — part-level retry exists again, and it has a live check in `e2e.md` §4.2's multipart block (kill the network mid-upload; one part's bytes are re-sent, not the file's). The row is kept rather than deleted because its SECOND half is still live: an end-to-end "user A read user B's bytes and was refused by IAM", which **is not reachable from this API** because no route accepts a foreign prefix. A temporary foreign-prefix probe route was **declined**: a route that grants a foreign-prefix read in order to test that foreign-prefix reads are refused is the shape of the defect it tests for. |

### SPEC-199's live verification — MOSTLY RUN 2026-08-30

**Most of the SPEC-199 block of [`e2e.md`](e2e.md) §4.3 ran on 2026-08-30**, along with §4.5's row
11. Evidence in [`sessions.md`](sessions.md). Rows are struck through as they were settled; §4.5's
rows 14 and 15, and the Data Explorer surfaces generally, were **not** reached.

| Owed | Why it is not settled offline |
|---|---|
| ~~**Lake Formation authorizes the ASSUMED-ROLE session** (FR-008 AC7)~~ **DISCHARGED 2026-08-30 — the arc's central claim, and it holds.** 2 rows, 112 B scanned, rendered. **Also discharges SPEC-196 Phase 5 item 4.** | The arc's central claim, and **it also discharges SPEC-196 Phase 5 item 4**, which that spec recorded as owed and re-homed here. LF is modelled by no IAM policy simulator, and every offline test supplies its own botocore fixture, so nothing offline can say whether LF still enforces against a principal the API assumes rather than the browser holds. Running it from a laptop proves nothing either: the local CLI identity is an IAM **user**, a different principal, and LF filters its catalog to empty. |
| ~~**Both Lake Formation denial shapes, in one sitting** (FR-008 AC4)~~ **DISCHARGED 2026-08-30** — Glue read with no `DESCRIBE` → **403**; Athena query with no `SELECT` → **200** reaching **FAILED**. Both against `adamparker`, a real foreign database. | A Glue read with no `DESCRIBE` is a **403**; an Athena query with no `SELECT` is a **200** whose execution reaches FAILED. Recording only the 403 proves nothing about the shape that matters more — the one six authored sentences are chosen from. Needs a database and a table the acting user is genuinely not granted on, so a second account or an ungranted fixture. |
| ~~**A foreign database and an absent one, compared** (FR-008 AC9)~~ **DISCHARGED 2026-08-30 — they are INDISTINGUISHABLE**, both 403 `AccessDenied` byte-identical apart from the request id, own database 200. No existence oracle; **nothing for SPEC-202's sweep**. | Whether they are distinguishable is **Lake Formation's** property, not this API's, and the route adds no existence check of its own. Record what each returns; if they differ it is a finding for SPEC-202's sweep, not a failure of this spec. |
| ~~**A real engine message still matches the wording rules after a JSON round trip** (FR-003)~~ **DISCHARGED 2026-08-30** — Athena's current text matched, so the banner read *"You don't have permission to run that query."* rather than the generic sentence, with no `arn:aws`, no `glue:GetDatabase` and no `Insufficient permissions` anywhere in the rendered page. | Every offline fixture is a string this repo wrote. What is unproven is that Athena's *current* text still matches the six `MATCH_RULES` once it has crossed the wire verbatim. If it stops matching, every failed query says "Contact the Administrator" and nothing looks broken. |
| ~~**`null` ≠ `''` on the raw body, against real data** (FR-004 AC2)~~ **DISCHARGED 2026-08-30** — `"rows": [[null, ""]]` on the wire. | The rendered grid shows the Value panel's rendering of both, so it cannot tell them apart; the assertion is on the response body text. |
| ~~**The disclosed SQL is byte-identical to the `QueryString` Athena received** (FR-009)~~ **DISCHARGED 2026-08-30** — `get-query-execution` returned the statement byte-identical, and `DataScannedInBytes: 112` matched the cost line. | Needs `aws athena get-query-execution` on the execution the disclosure named. A statement mangled by a `strip()` still runs, still returns rows and still looks right in the disclosure. |
| ~~**The 409/400 pair, from `curl`** (FR-005 AC2)~~ **DISCHARGED 2026-08-30** — 409 `QueryNotFinished` and 400 `QuerySyntaxError` from the one Athena exception name. | A results read against a still-running execution and a malformed statement at submit raise the **same** Athena exception name. The browser cannot stage the first — the caller-side gate is what prevents it — so the negative needs a direct request. |
| ~~**The browser has stopped talking to Athena and Glue** (FR-013 AC5)~~ **DISCHARGED 2026-08-30** — zero requests to `athena.*` or `glue.*` across every section run. | The packages are gone and a guard asserts they do not resolve, but "no request leaves the tab for `athena.*.amazonaws.com`" is a network-panel observation. |
| ~~**Cold start**~~ **DISCHARGED 2026-08-30** — the first invocation after the deploy succeeded. | A layer imported and not attached deploys clean and fails at import; the first invocation after a deploy is the only place it shows. |


### SPEC-226 FR-005 — the child-span budget has no ceiling and no rate to derive it from

FR-005 asks for the volume this spec adds to be asserted against **a budget in events per
service-day, derived from the day-object ceiling and the fleet's invocation rate**. Most of that
ships: `lambdas/test_child_spans_per_plane.py` drives the worst-case verb on each of the seven
planes, counts every span event through a capturing sink, holds the count at a ratchet, and derives
an events-per-service-day figure from `log_sweep.LARGE_OBJECT_WARN_BYTES` — read from the sweep —
divided by a measured event size.

**What is owed is the figure's precision, not its existence.** The constant that budget rests on is
a detector sized to fire early rather than the true ceiling, so the derived budget is conservative
by an unmeasured factor; and there is no invocation rate to say whether the resulting headroom is
comfortable. Both are recorded rather than guessed at.

| Input | Why it cannot be established today | What would settle it |
|---|---|---|
| **The day-object ceiling** | `log_sweep.LARGE_OBJECT_WARN_BYTES` (64 MiB) reads like the ceiling and is not one: it is a **detector deliberately sized to fire early**. `infra/modules/observability/README.md` says the sweep's memory is 512 MB and that this constant "warns long before that becomes binding", and the sibling constant's own guard in `test_feedback_writer.py` asserts `memory_bytes > LARGE_OBJECT_WARN_BYTES * 4` precisely because peak resident while appending is several multiples of the object. The real ceiling is 512 MB ÷ that multiple, and **the multiple is nowhere measured**. | Measure the sweep's peak resident against a day object of known size — the same measurement the feedback writer's guard assumes but does not take. |
| **The fleet's invocation rate** — **a first real measurement, 2026-09-10, and it is of the drain rather than the source**: one user's session backed up `dat-prod-logs.fifo` to 17,134 messages; every `log-sweep` run stopped on its wave cap after 1,102–1,627 messages, which at one run every 10 minutes is a ceiling of 6,612–9,762 an hour; and `logs/service=api/` ran two hours behind. Nothing alarms on the backlog. | Greenfield: no production users, no reserved concurrency (`docker-lambda`'s `reserved_concurrency` defaults to `-1` and no module sets it), no API throttle. There is no rate to convert a per-invocation count into a per-service-day one. | Any period of real traffic, or a deliberate cap. |

Until both exist, the events-per-service-day figure would be a number chosen to pass. What is
guarded instead is that the per-invocation volume cannot grow without somebody editing the table
and saying why.

### Not observable at all

| Check | Why |
|---|---|
| The restore's **`Restore` header format**, and `GLACIER`-stays-`GLACIER` on the archived object | The audit trail does not report either. The plane's own `complete: false → true` polling corroborates it; that is not the same thing. |
| **`SaveQueryDialog`'s "nowhere to save" state** (SPEC-186's ninth dialog) | Needs the personal space unavailable, which cannot be staged from the UI. |
| **SPEC-151 FR-006's escaping over a real partition segment containing `'`** | Asserted at render time only. If such a folder ever fails, suspect the engine before the renderer. |
| **SPEC-151 FR-003's failure direction** | A denied key cannot be staged from the UI; unit-tested only. |
| **A partial restore, and `restore_timed_out`** | Forcing one item to fail mid-copy means denying a destination the guard would have refused up front. Seven hours of waiting to observe a counter. |
| **A JWKS key rotation across the refetch cooldown** (SPEC-195) | For up to 60 s after a provider rotates its signing keys this API refuses tokens signed with the new one — the accepted cost of bounding an unauthenticated amplification vector. Cognito publishes both keys across a rotation and the window sits far inside any overlap, so no real rotation is expected to reach a user. Forcing one means rotating a pool key; **accepted rather than verified**. |
| **The unknown-`kid` refetch bound under real load** (SPEC-195) | The counter is asserted offline against a fake transport. What is not observed is the fetch rate a real burst produces against the real JWKS endpoint. |
| **A live 403 on the user plane** (SPEC-197) | Cannot be staged against a bucket-wide grant. **Passed to SPEC-198.** |
| **What `setUnauthenticatedHandler` should DO** (SPEC-197 FR-007) | The hook ships with **no handler registered**, deliberately: `apiRequest` never navigates, and what a genuinely-dead session should do to the UI is a product decision this spec's scope excludes. Until one is registered, a surviving 401 resolves to "Your session expired. Sign in again." and nothing else happens. |
| **A 429 mid-walk, observed live** (SPEC-199 FR-007) | API Gateway account throttling cannot be staged. The degradation is unit-tested — a failed page leaves `total: null` and raises no banner — and the live half is the one that would show whether a real burst produces it at all. |
| ~~**Stale root-level static assets** (SPEC-141)~~ — **VOID 2026-09-02** | The S3 delivery path is retired: the image IS the file set, so there is no reconciliation pass and no orphan class, and an asset the build did not produce is an honest 404. Kept for the reasoning only. An accepted orphan class, not a check. Removals were by hand, and **not verifiable by status code** — the distribution maps `403/404 → /index.html` with a **200**, so check `content-type` and `x-cache: Error from cloudfront`. |

### Accepted exposure, with an owner

| Exposure | Owner | Note |
|---|---|---|
| **A browser holding another user's execution id can read that execution** | unowned — **owed a spec** | Athena authorizes `GetQueryExecution` / `GetQueryResults` / `StopQueryExecution` by **workgroup**, and this deployment has one shared workgroup. SPEC-199's port **preserved this exactly** — the API adds no ownership check and removes none — because a real fix needs an execution→owner record that does not exist. The whole mitigation shipped is `actor` and `execution_id` on every catalog span, so a cross-user read is at least attributable in `logs/service=api/`. |
| **The API is internet-facing and unthrottled** | SPEC-196 | `api.dataquarry.app` answers `GET /healthz` without a credential and **401s everything else**, identified or not — it now verifies a bearer token (SPEC-195), so "unauthenticated" is stale, but it still makes no AWS call and holds no data. One new exposure comes with the verification: an unknown `kid` makes a JWKS refetch, so a stream of random `kid`s is an amplification vector against the provider **from unauthenticated requests** — bounded by a per-container cooldown, and the bound is asserted offline only (see *Not observable at all*). A rate limit is **deliberately deferred by the arc**, so the account default (10,000 rps / 5,000 burst) applies and every request is a billed invocation. CORS restrains browsers, not `curl`. Reviewed and accepted 2026-08-26; the exposure is billing, not disclosure. Revisit if the placeholder is still there when a route with a body lands. |

| **The pre-migration Cognito token set is still in `localStorage`** | unowned — **raised 2026-09-01, disposition open** | The 2026-08-27 move to `sessionStorage` left the old keys behind and nothing clears them. Observed live: `localStorage` holds a complete set — `idToken`, `accessToken`, `refreshToken`, `clockDrift`, `oauthMetadata`, `LastAuthUser` — for **`agriffith_three`**, while a fresh tab renders signed **out** and this session signed in as `agriffith` alongside them with no interference. So it is **inert**, which is why no test or check would ever surface it: the app reads `sessionStorage` and the stale set is invisible to every code path. The exposure is that a refresh token for another principal persists in browser storage indefinitely on any machine used before the migration. A one-time cleanup on boot is the obvious remedy; whether it is worth a change is Andrew's call. **RE-MEASURED 2026-09-09, and it does NOT bear on the 2026-09-01 reading.** `localStorage` is partitioned per origin, and the two readings have different subjects: the stale set was seen on `d1kbh4bnvh1je8.cloudfront.net` in Chromium via an agent browser, while today's — **exactly one** key, `CognitoIdentityServiceProvider.<app-client-id>.oauthSignIn` — is on `https://portal.dataquarry.app` in Andrew's own Chrome. It matches what that **same** origin already showed on 2026-08-31, so nothing was measured as having changed. And the CloudFront distribution was destroyed 2026-09-02 (`NoSuchDistribution`), so that origin cannot be loaded again: the set is **unreachable, not demonstrably cleared** — a different disposition, and a weaker one. **Anyone re-opening this must name the origin AND the browser profile, or the measurement means nothing.** |

### Dated, and nothing in CI will raise it

| Check | Due | Note |
|---|---|---|
| **The front door's domain registration expires** | **2027-08-26** | `dataquarry.app`, auto-renew **deliberately off**. Every hostname in the container arc hangs off it — both ACM certificates, the Cognito callback and logout lists, the CSP's `connect-src`. A lapse takes the platform's DNS dark, and no workflow, alarm or scanner watches a registrar expiry. Re-check with `aws route53domains get-domain-detail --domain-name dataquarry.app --query '{AutoRenew:AutoRenew,Expiry:ExpirationDate}'`. |
| ~~**A live CORS preflight: one `access-control-allow-origin` per origin, and none for a foreign one**~~ **DISCHARGED 2026-09-10** — `OPTIONS` from the portal origin returned exactly one `access-control-allow-origin`, methods without `HEAD`, no credentials header; from a foreign origin, 200 with none | with SPEC-193 PR 6 | Only the foreign-origin half can fail — a `"*"` configuration passes the echo check. Offline the configuration is asserted; the header count is not observable without a request. |
| ~~**One real invocation producing one span with `env` and `version` populated**~~ **DISCHARGED 2026-09-10** — all 56 results-conversion records of the day carry `env: prod` and a real build sha | with SPEC-193 PR 6 | The gate the structured-logging spec lacked, and the entire argument for building a placeholder. A missing layer attachment passed every offline gate: the shared conftest puts the shared roots on `sys.path`, and `update-function-code` succeeds against a function that cannot import. Layers are gone; the class of failure is not, which is why this row is about a real invocation rather than about packaging. |
| ~~**`describe-user-pool-client` shows BOTH origins in the callback AND logout lists**~~ | **DISCHARGED 2026-08-30, then narrowed 2026-09-02** | Both were live before merge 1 — the apply had widened rather than replaced, which was the point. The lists now name `localhost:5173` and `spa_origin` only; the CloudFront entry went with the distribution. The live shape is re-read in the SPEC-202 section below. |
| ~~**The two front-door certificates are unattached until the API and SPA ship**~~ | **settled 2026-08-27** | Both have shipped: the API's flipped `INELIGIBLE` → `ELIGIBLE` when its custom domain attached it, and the SPA's is on the load balancer's listener serving `portal.dataquarry.app`. The reasoning stands and is worth keeping for the next certificate — ACM's managed renewal covers a certificate only while it is **associated with a service** or exported, so `ISSUED` is not a durable end state and verification must confirm *association*, not status. |
| **A fresh sign-in against the container origin, from a private window** | **owed, and now the arc's sharpest gap — see the SPEC-202 section below** — a cold-cookie sign-in in a normal profile ran 2026-09-10 and passed; the private window's cold cache is what remains | **A signed-in pass never tests sign-in.** The authorization-code exchange is the only `fetch` to the Hosted UI host and a warm tab never makes it, so a `connect-src` missing that host produces a portal that works for everyone already signed in and for nobody else — this repo's own recorded outage, and it lasted a day. Since 2026-09-02 it also exercises the **narrowed** Cognito callback and logout lists, which nothing else does. Steps: `e2e.md` §4.1. |
| ~~**The CSP is enforcing, proved by a negative control**~~ | **DISCHARGED 2026-08-31, Chromium** | A `fetch` to `athena.us-east-1.amazonaws.com` raised a **positive** `securitypolicyviolation` with `effectiveDirective: "connect-src"` and `disposition: "enforce"`, with `/config.json` returning 200 in the same run as the control. **The method in this row was wrong and is corrected in `e2e.md` §4.18:** CDP evaluation is exempt from `script-src`, **not** from `connect-src`, and the "same-origin page script" recipe is unsatisfiable under `script-src 'self'`. Reporting no violations is still not evidence. |
| ~~**Safari, once, against the container origin**~~ **RETIRED AT ITS PREMISE** — the audience has no Safari (2026-09-01); the report-only blind spot is moot now that the CSP enforces | with SPEC-194 | Safari refuses to evaluate a report-only policy naming no reporting endpoint — the blind spot no Chromium harness surfaces, and the tooling here is Chromium. §C.3. |
| **A rolled-back deployment actually reddens the pipeline** | with SPEC-194 | The mechanism is asserted offline; that it fires is not. It needs an image broken in a way the pre-push matrix **cannot see** — a required key the entrypoint demands and the task definition does not supply — because an entrypoint that simply exits 1 reddens at the matrix and never reaches the deploy gate. §C.6. |
| **A browser honours `immutable` across a real deployment** | with SPEC-194, and not dischargeable offline | The header is asserted on the response; what a browser does with it over a deploy boundary is not observable from `curl`. |
| ~~**A warm-cache user of the CloudFront origin is unaffected while both delivery paths run**~~ | **VOID 2026-09-02** | There is one origin. The distribution is destroyed, so there is no second cache to be unaffected. Retired at its premise rather than left owed. |
| **Terraform-registered revisions never reach the running container** | with SPEC-194, structural | The service carries `ignore_changes = [task_definition]`, so a change to the runtime-configuration map or the CSP registers a revision CI never points at — the running container keeps the old value until the next push to `main`. `Deploy SPA image`'s `workflow_dispatch` is the lever. Recorded so a stale CSP is not diagnosed as a container defect. |
| **`TF_VAR_spa_image_tag` still names a placeholder-era sha** | with SPEC-194 | CI owns which revision runs, so this is inert while `ignore_changes` holds. It stops being inert if the service is ever **replaced** rather than updated: Terraform would create it pointing at its own revision, whose image is the placeholder — which is healthy and serves a placeholder page, with no error anywhere. |

---

## 2. Recipes

### 2.1 Credentials as the portal role

> **RETIRED by SPEC-202 (2026-09-02). This recipe cannot be run: there is no Identity Pool, so no
> browser session can mint portal-role credentials.** Re-verified 2026-09-09 —
> `cognito-identity list-identity-pools` returns `[]` — and its first step ("paste the idToken
> from devtools → Local Storage") was already dead when tokens moved to `sessionStorage` on
> 2026-08-27. **Use `simulate-principal-policy` from an operator CLI identity instead** (§2.8),
> which is how the `DO_NOT_DELETE` and §E.9 rows above were finally settled. A check that needs
> the role's *runtime* behaviour rather than its policy has no vehicle today — say so in its row
> rather than pointing here.

Needed for anything refused by an **IAM layer the app never reaches**. The `DO_NOT_DELETE.txt` Deny
is in the **portal role's own identity policy** — `data/policies/portal-role-permissions.json.tftpl`
and `shared-spaces/policies/portal-role-shared-space.json.tftpl` — not in a bucket policy, and
**there is no shared-space bucket policy at all** (only user-space, archive, static assets and the
audit trail have one). So the check must run *as the portal role*: the laptop IAM user is not on the
user-space allowlist and would be refused by that allowlist instead, which is a different refusal
wearing the same name. On the shared-space bucket a laptop identity is not blocked by a bucket
policy — but it does not hold the Deny either, so it proves nothing.

**Never paste the token into a shell command** — it is a live credential and it lands in history.

```bash
umask 077 && cat > /tmp/idtoken     # paste the idToken from devtools → Local Storage, then Ctrl-D

IDENTITY_ID=$(aws cognito-identity get-id \
  --identity-pool-id "$IDENTITY_POOL_ID" \
  --logins "cognito-idp.$AWS_REGION.amazonaws.com/$USER_POOL_ID=$(cat /tmp/idtoken)" \
  --query IdentityId --output text)

aws cognito-identity get-credentials-for-identity \
  --identity-id "$IDENTITY_ID" \
  --logins "cognito-idp.$AWS_REGION.amazonaws.com/$USER_POOL_ID=$(cat /tmp/idtoken)" \
  --query Credentials
```

Export the three values in a shell you will close afterwards, then `rm -f /tmp/idtoken`.

**The marker check, and the control that makes it mean anything:**

```bash
# Expect AccessDenied on BOTH.
aws s3api delete-object --bucket dat-prod-user-space   --key "$USERNAME/saved_queries/DO_NOT_DELETE.txt"
aws s3api delete-object --bucket dat-prod-shared-space --key "$SPACE/saved_queries/DO_NOT_DELETE.txt"

# Expect BOTH to succeed — this is what proves the refusals above came from the marker Deny
# and not from the credentials being wrong.
aws s3api put-object    --bucket dat-prod-user-space --key "$USERNAME/saved_queries/marker_control.txt" --body /dev/null
aws s3api delete-object --bucket dat-prod-user-space --key "$USERNAME/saved_queries/marker_control.txt"
```

Afterwards, both markers are still present (they are hidden in the portal, so confirm with
`head-object`, not by eye).

**The notifications `create` boundary, and the control that makes it mean anything** (SPEC-206). Same
credentials, same reason: only the portal role produces the `SenderId` the writer refuses, and the
laptop identity produces a different one — which would be refused for the wrong reason, or not at all.

**Target your OWN username.** The portal role can only read its own `user_settings/`, so aiming at a
second account leaves you unable to observe the pass condition at all.

**The portal role holds `sqs:SendMessage` and NOTHING ELSE on this queue** — no `GetQueueUrl`, so
resolve the URL from the root output first, in the laptop shell, BEFORE switching credentials:

```bash
QUEUE_URL=$(tofu -chdir=infra output -raw notifications_queue_url)
```

Both sends below run in the portal-role shell, and **before the `rm -f /tmp/idtoken` above** — the
control needs the token, and running it after the cleanup sends an empty one, which dead-letters and
looks exactly like the boundary having broken everything. The queue is FIFO, so `--message-group-id`
is required and there is no content-based dedup:

```bash
# THE CHECK. Expect the send to SUCCEED — the grant is unconditioned, so SQS accepts it.
# The refusal happens in the writer, which is the whole point.
aws sqs send-message --queue-url "$QUEUE_URL" \
  --message-group-id "$USERNAME" --message-deduplication-id "boundary-$(date +%s)" \
  --message-body "{\"action\":\"create\",\"username\":\"$USERNAME\",\"message\":\"SPOOFED\"}"

# THE POSITIVE CONTROL. Expect this to succeed AND take effect — without it, a refusal cannot be
# told apart from the browser having lost access to the queue entirely.
aws sqs send-message --queue-url "$QUEUE_URL" \
  --message-group-id "$USERNAME" --message-deduplication-id "control-$(date +%s)" \
  --message-body "{\"action\":\"markAllRead\",\"identity\":{\"actor\":\"$USERNAME\",\"delegated_by\":null,\"assurance\":\"interactive\"}}"
```

Then observe, in this order:

1. **No row saying `SPOOFED`** in `s3://dat-prod-user-space/$USERNAME/user_settings/notifications.json`
   — read it in the portal's Network tab or with `get-object`. This is the pass condition.
2. **Every row now reads** — the control landed, so the credentials and the queue both work.
3. **`reason: untrusted-sender`** under `logs/service=notifications/year=/month=/day=/`, with the
   send's id in the **`message_id`** field. **Read this from the LAPTOP shell, not the portal-role
   one** — the portal role has no admin-bucket access at all, so from there the read is an
   `AccessDenied` that says nothing about the boundary. **And wait a sweep first:** the logs queue is
   swept every 10 minutes and never long-polled, so checking immediately shows an empty prefix and
   reads as a failure. A `sender-check-unconfigured` there instead means the deploy lost the
   environment variable — the control has broken, not been tested.

### 2.2 Hand-crafted control-plane requests

The only way to stage a malformed request, or two executions that genuinely contend.

> **REWRITTEN by SPEC-201 (2026-08-30). Every recipe below that sends a token is now a refusal.**
> The planes stopped verifying tokens; they read the `identity` block the API stamps, and the
> per-plane token-field table this section used to carry has no subject left. Two things changed
> for anyone running these:
>
> 1. **The envelope is the block, on every plane.** `{"identity": {"actor": "<username>",
>    "delegated_by": null, "assurance": "interactive"}}` plus that plane's own fields. All three
>    keys are required — an absent `delegated_by` or `assurance` is refused, deliberately.
>    A message with a token and no block is refused `unauthorized`, produces no notification, and
>    does **not** dead-letter (the Pipe is `FIRE_AND_FORGET`, so `StartExecution` succeeds and the
>    refusal happens inside the execution).
> 2. **A laptop identity can no longer send these at all**, which matters more. SPEC-200 removed
>    the portal role's `sqs:SendMessage` and gave it to the API's execution role alone, so every
>    recipe here needs an assumed session of that role rather than the credentials the rest of this
>    file assumes. That is a real obstacle, not a formality — see the row for it in the ledger.

Every plane takes one FIFO queue:

| Plane | Queue |
|---|---|
| Table builder | `dat-prod-table-builder-requests.fifo` |
| Data quality | `dat-prod-data-quality-requests.fifo` |
| Shared spaces | `dat-prod-shared-space-requests.fifo` |
| Table share | `dat-prod-table-share-requests.fifo` |
| File send | `dat-prod-file-send-requests.fifo` |
| Archive / restore | `dat-prod-archive-requests.fifo` |
| File operations | `dat-prod-file-ops-requests.fifo` |

```bash
QUEUE=$(aws sqs get-queue-url --queue-name dat-prod-table-builder-requests.fifo --query QueueUrl --output text)
aws sqs send-message --queue-url "$QUEUE" \
  --message-group-id "$USERNAME" --message-deduplication-id "$REQUEST_ID" \
  --message-body "$(jq -nc --arg u "$USERNAME" --arg r "$REQUEST_ID" \
      '{identity:{actor:$u, delegated_by:null, assurance:"interactive"},
        mode:"refresh", requestId:$r, tableName:"partfix",
        space:{kind:"personal", bucket:"dat-prod-user-space", prefix:($u+"/partfix/"), database:$u}}')"
```

**Two things about that body are load-bearing, and both fail quietly.** The verb is **`mode`**, not
`action` — this plane has no unknown-field check, so an `action` key is silently ignored and
`_validate_mode(None)` returns **`"create"`**: a contention run built that way starts two *creates*
and never claims the refresh lock at all. And `space` needs all four of
`{kind, bucket, prefix, database}` — `{kind, name}` is refused as `forbidden` before the mode is
ever read, because `_authorize_space` compares `database` against the actor.

**Refresh-lock contention (SPEC-157).** The lock is claimed by the *execution*, so two messages are
two executions. Send both at once — same group is enough (the Pipe starts the second while the
first still holds the lock); different groups removes even that serialization.
**Pass:** one succeeds, the other ends `refresh_already_running`, the loser is **notified rather
than queued**, and `logs/service=table-builder/` shows one lock claim and one refusal. *(The
no-token alternative: point a table at a folder with several hundred objects so the first refresh's
listing takes tens of seconds, then two UI tabs really do overlap.)*

**A malformed body (SPEC-133/126).** Send a body that is not the envelope at all. Expect: the
message dead-letters, the drain sweeps it within 10 minutes, **the actor is notified from the
verified token and nothing from the untrusted body reaches the message**, the message is gone
(nothing redelivers), and the redacted body is in `logs/service=dlq-drain/`.

**Archive and restore.** Two UUIDs per run, and they must **differ** — the plane refuses a restore
whose `requestId` equals its `archiveId`. The group id is the digest of the **archive root alone**,
which is the contract the browser reproduces:

```bash
--message-group-id "$(printf 'personal/%s/archive/%s/' "$USERNAME" "$ARCHIVE_ID" | shasum -a 256 | cut -d' ' -f1)"
--message-body "$(jq -nc --arg r "$REQUEST_ID" --arg u "$USERNAME" --arg a "$ARCHIVE_ID" \
    '{identity:{actor:$u, delegated_by:null, assurance:"interactive"},
      requestId:$r, mode:"restore", space:{kind:"personal", name:$u}, archiveId:$a}')"
```

**This block carried a flat `actor:$t` token until 2026-09-09, against its own section banner** —
built from it, the run is refused `unauthorized` and reads as a broken plane. `restore.ALLOWED_FIELDS`
is `{requestId, mode, actor, space, archiveId, identity, traceparent}`, so the flat field is still
*accepted*; it is simply no longer *read*, which is why the mistake is silent. `traceparent` is the
API's to stamp — omit it and the run is untraced, which is a fact about the vehicle rather than
about the plane.

**Before reaching for this section at all, check whether the API can send the request.** An enqueue
route reads no membership, types a name as a free `str` — `isinstance` and nothing more — and derives
its FIFO keys from the body, so a signed-in `POST /v1/enqueue/{plane}` can stage a body the UI has no
gesture for. An unregistered space is one: that is how SPEC-227 FR-002's half (b) was driven on
2026-09-09, with no assumed role and no queue write. The same holds on **file-send**, where
`ShareRecipient.name` is a free string and the plane really does answer `unknown_space`. **Rows in §1
that call for a hand-crafted envelope predate this and several are stale — check the route contract
before believing one.** What genuinely still needs this section is a body the *route contract*
rejects: an unknown top-level field, a body that is not the envelope at all, a `mode` the route does
not own, or two messages contending on one group id.

**These three no longer need staging by hand, and the paragraph above is why:** `RestoreEnqueueRequest.archiveId`
is a bare `str`, so an id with a trailing space, one containing `/`, and one in UPPER CASE all pass
`POST /v1/enqueue/restore` untouched and are decided inside the plane. The UI cannot send them; the
API can. What they should show is unchanged — the first two are refused **`invalid_request`**
before any bucket is touched (no listing in `logs/service=archive/` for that request) — the code
is `invalid_request`, not `malformed_event`, and in a row whose lesson is *check the reason* the
loose word was worth replacing, and the third resolves
normally, because the id is lowercased. A nonexistent id and a real id in a space you are a member of both return the *same*
`archive_not_found` — the second must not hint that the archive exists elsewhere.

### 2.3 The data-quality state order, including the poll

The one recipe that proves the `WaitForQuery → CheckQuery → Choice` loop iterates. Drive a check
from the UI, take its execution ARN, then:

```bash
aws stepfunctions get-execution-history --execution-arn "$EXEC_ARN" \
  --query "events[?type=='TaskStateEntered' || type=='WaitStateEntered'].stateEnteredEventDetails.name" \
  --output text
```

Expect, in order: `ValidateAuthorize InspectSource CreateTempTables StartProfileQuery WaitForQuery
CheckQuery WaitForQuery CheckQuery ByteScan AssembleReport DropTempTables`. **`WaitForQuery` and
`CheckQuery` must each appear twice** — a single pass is a poll that never polled, and it reads as a
pass.

### 2.4 Reading the archive audit trail

`RestoreObject` is a **data** event, invisible in CloudTrail Event history — SPEC-186 FR-004 added a
dedicated trail. **Prove the trail is logging first.** A trail that is off returns an empty result,
which reads exactly like a `RestoreObject` that never happened:

```bash
aws cloudtrail get-trail-status --name dat-prod-archive-audit --query 'IsLogging'   # expect true
```

Data events arrive in batches — **wait ~10 minutes** before concluding anything.

```bash
aws s3 ls "s3://dat-prod-archive-audit/AWSLogs/" --recursive \
  | awk '{print $4}' | while read -r key; do
      aws s3 cp "s3://dat-prod-archive-audit/$key" - | gunzip
    done \
  | jq -r --arg id "$ARCHIVE_ID" '
      .Records[]
      | select(.eventName == "RestoreObject")
      | select(.requestParameters.key // "" | contains($id))
      | "\(.eventTime)  \(.requestParameters.key)"'
```

The archive key layout is `{personal|shared}/{space}/{archiveId}/…`, so the id is in every key a run
would touch.

- **After a refused restore: expect NO OUTPUT.** That is the assertion.
- **During a real retrieval: expect exactly the archive's object count** (`| sort -u | wc -l`).

### 2.5 EventBridge timeout doors, and share-at-scale reads

```bash
# The rule matches TIMED_OUT only — a FAILED in the pattern double-notifies every caught failure.
aws events describe-rule --name dat-prod-table-share-orchestrator-timed-out --query 'EventPattern' --output text
aws events list-targets-by-rule --rule dat-prod-table-share-orchestrator-timed-out --query 'Targets[].Arn'
```

Then prove the two halves separately. **Do NOT reach for `put-events` first** — the obvious recipe
is a trap, and this section carried it for months:

**The rule half is READ-ONLY and an agent session can run it.** `test-event-pattern` answers the
"what proves the rule matched" question without publishing anything:

```bash
PAT=$(aws events describe-rule --name dat-prod-table-share-orchestrator-timed-out \
        --query EventPattern --output text)
# Build an event with source aws.states, detail-type "Step Functions Execution Status Change",
# and detail.{executionArn,stateMachineArn,status}; then, three times:
aws events test-event-pattern --event-pattern "$PAT" --event "$EV" --query Result --output text
```

Measured 2026-09-09 against the deployed table-share rule: the correct `stateMachineArn` with
`TIMED_OUT` → **`True`**; a different machine's ARN → **`False`**; `status: FAILED` → **`False`**.
That last one is this row's real worry — a `FAILED` in the pattern double-notifies every caught
failure — and it is now measured rather than read off the JSON.

**The handler half needs a write, and `put-events` is the WRONG write.** `Source` must not begin
with `aws.` — that prefix is reserved for AWS's own services, and `PutEvents` refuses such an entry
**per entry**: HTTP 200, `FailedEntryCount: 1`, `ErrorCode: NotAuthorizedForSourceException`. So the
call exits 0, `check=True` never fires, no notification arrives, and the negative control "passes"
too — **both assertions pass having published nothing.** If you use `put-events` anyway, read
`FailedEntryCount`; an exit code proves nothing here. The direct way to exercise the handler is to
invoke it:

```bash
aws lambda invoke --function-name dat-prod-table-share-notify-failure \
  --payload file://event.json /dev/stdout        # keep detail-type: the handler dispatches on it
```

The body inside `detail.input` needs an **`identity` block, not a token** — since SPEC-201
(`ff3a76b6`, 2026-08-30) `cpactor.trusted_actor` reads only that block and imports no JWT code, so a
flat `actor` token is refused `unauthorized: the request carries no identity block` before `source`
is read. Build it in Python rather than by hand; the SQS-shaped `input` is a string inside a string:

```python
import json
body = {"requestId": "probe", "tableName": "probe",
        "identity": {"actor": "<your-username>", "delegated_by": None, "assurance": "interactive"},
        "source": {"database": "<you>", "table": "sales"}}
detail = {"executionArn": "arn:aws:states:us-east-1:<acct>:execution:M:probe",
          "stateMachineArn": "<state-machine-arn>", "status": "TIMED_OUT",
          "inputDetails": {"included": True},
          "input": json.dumps([{"body": json.dumps(body)}])}
event = {"source": "aws.states",
         "detail-type": "Step Functions Execution Status Change", "detail": detail}
with open("event.json", "w") as f:
    json.dump(event, f)
```

Expect the notification in **your own** inbox; repeat with a `username` in the body naming someone
else and confirm it **still** arrives in yours — the actor comes from the `identity` block, which is
the whole point of this second assertion. **An agent session cannot do the invoke half**: the
harness refuses an agent's production AWS writes. `events:PutEvents` measured `allowed` for the
operator CLI identity on 2026-09-09, so the block is the harness, not the grant.

The scale reads:

```bash
# The fixture really is over the old caps.
aws s3 ls --recursive --summarize "s3://dat-prod-user-space/$USERNAME/<source-prefix>/" | tail -3

# One event per run carries the recipient and item counts.
aws s3 cp "s3://dat-prod-athena-admin/logs/service=table-share/year=<Y>/month=<M>/day=<D>/data.jsonl" - \
  | grep 'transfer manifest built'

# The 100-column clone survived the pointer, comments and all.
aws glue get-table --database-name "<recipient-db>" --name "<result-name>" \
  --query 'Table.{cols: length(StorageDescriptor.Columns), props: Parameters}'
aws glue get-table --database-name "<recipient-db>" --name "<result-name>" \
  --query 'length(StorageDescriptor.Columns[?Comment!=`null`])'      # expect 100
```

### 2.6 The verification role

**Do not apply it locally.** No human identity here can `tofu apply` from a laptop: the IAM user is
not on the data buckets' policy allowlists, so tofu reads them as **absent** and plans to destroy
and recreate them (measured: `25 to add, 3 to change, 13 to destroy`, both data buckets in the
replace set). The value is a **repo variable** applied by CI:

```bash
gh variable set TF_VAR_verification_principal_arns --body '["arn:aws:iam::<account>:user/<you>"]'
```

Then run **Deploy Infrastructure**. Expect a red first apply — IAM is eventually consistent — and
re-run. Once green:

```bash
aws sts assume-role --role-arn "arn:aws:iam::<account>:role/dat-prod-verification" --role-session-name livecheck
```

The role is audit-shaped, not a data grant: no `SELECT`, no `DATA_LOCATION_ACCESS`, no
`lakeformation:GetDataAccess`, no `Resource: "*"`, no `iam:PassRole`. It exists only once
`verification_principal_arns` names a principal, because delegating to the account root was
rejected by the plan scan (`CKV_AWS_61`) for the right reason.

### 2.7 The `username` principal tag, from the audit record

The tag is stamped **server-side** from the verified claim, which is the whole isolation model —
and it is unobservable from the app. Sign in on a **fresh** session (credentials are issued at token
exchange, so a cached one never fires the event), then read the record.

**Look for `AssumeRoleWithWebIdentity` from `sts.amazonaws.com`** — not the `CognitoAuthentication`
event, which is the Hosted UI login on `cognito-idp` and **never carries the principal tag**. Mixing
them up reads as a missing tag on a correct system. CloudTrail lags a few minutes.

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity \
  --max-results 5 --query 'Events[].CloudTrailEvent' --output text \
  | grep -o '"principalTags":{[^}]*}'
```

Expect `"username":"<the signed-in username>"`. In the browser, `GetId` and
`GetCredentialsForIdentity` both return **200** on the `cognito-identity` host — that is the
User-Pool-token → AWS-credentials exchange, and without it there is no STS event to find.

### 2.8 IAM policy simulation

The pattern, whenever a grant is tightened or widened. **Every denial needs an `allowed` control on
the same bucket** — an `implicitDeny` alone cannot tell an ungranted action from a wrong resource
ARN, which is how a mistyped bucket name once read as a pass.

```bash
ROLE=arn:aws:iam::<account>:role/dat-prod-<plane>-execution-role
run() { printf '%-24s %-64s ' "$1" "$2"; aws iam simulate-principal-policy \
  --policy-source-arn "$ROLE" --action-names "$1" --resource-arns "$2" \
  --query 'EvaluationResults[0].EvalDecision' --output text; }
```

**Three ways this returns a confident wrong answer.**

- **Everything comes back `explicitDeny`.** The user-space bucket policy denies on
  `StringNotLike aws:PrincipalArn`, and a **missing** context key makes that condition **true** — so
  a simulator that never populated the principal ARN denies everything, uniformly and plausibly. Add
  `--context-entries ContextKeyName=aws:PrincipalArn,ContextKeyValues=$ROLE,ContextKeyType=string`.
- **`simulate-principal-policy` does not consult a bucket policy on its own.** Pass
  `--resource-policy`, or the run is silently only testing the identity half. Add
  `--resource-owner <account-id>` if the call errors on the resource policy (same-account should not
  need it).
- **`simulate-custom-policy` caps each `--policy-input-list` member at 2,000 characters, and the
  `file://` form is rejected as "invalid content".** Pass it inline
  (`--policy-input-list "$(cat policy.json)"`) over a minimal extract that reuses the same condition
  pattern.

Run it **after** the apply, against the deployed role. A row that moves `implicitDeny` →
**`explicitDeny`** across a widening is the strongest evidence there is: once the widening grants
the action broadly, the only thing still refusing it is the Deny you are testing, and a mis-scoped
one would read `allowed`.

---

### 2.9 Which principal ELB actually delivers access logs as

The admin bucket's policy grants **two** identities `s3:PutObject` under
`alb-access-logs/AWSLogs/{account}/`: the log-delivery service principal
(`logdelivery.elasticloadbalancing.amazonaws.com`) and the region's own load-balancing account.
**Only one of them is used, and which was never isolated.**

Three applies were refused with `InvalidConfigurationRequest: Access Denied for bucket` before the
policy landed in this shape, and each refusal names neither a principal nor a condition. What the
sequence established is that **conditions** were the problem — `StringEquals aws:SourceAccount` and
`ArnLike aws:SourceArn` were each refused on their own, because ELB validates the policy with a
`PutObject` of its own at `ModifyLoadBalancerAttributes` time and a condition on a key that call
does not populate fails closed. What it did **not** establish is whether the service principal alone
would then have sufficed.

Isolating it means putting candidate policies on the bucket between attempts, which is a live write
to a production bucket policy — so it did not run, and both principals ship. **The narrowing is
worth doing once, and it is cheap when it happens:** drop one statement, apply, read
`describe-load-balancer-attributes` back; if access logging survives, delete the other statement for
good. Until then the grant is wider than it needs to be by exactly one AWS-owned identity, bounded
by the account id in the Resource path — a foreign balancer writes under its own account's id and
matches nothing here.


### Discharged 2026-08-26 — the container platform

| Settled | Evidence |
|---|---|
| **A Fargate task pulls from ECR with NO NAT gateway** | `runningCount == 1`, no `CannotPullContainerError`, read beside `describe-route-tables` showing local + `pl-63a5400a` and **no `0.0.0.0/0`** |
| The gateway endpoint's association set | `RouteTableIds` **equals** the private route tables |
| `/healthz` through the load balancer | `HTTP/2 200`, body `ok`; target health `healthy` |
| The HTTP→HTTPS redirect | `301`, `Server: awselb/2.0` — **curl only**, `.app` is HSTS-preloaded |
| Both certificates | issued per host, and **both `ELIGIBLE`** for renewal once attached |
| The CORS trio | one ACAO for each allowed origin, **zero** for a foreign one, no credentials header |
| Both origins in both Cognito lists, and `api_origin` in CloudFront's `connect-src` | read back from the deployed client and a `curl -sSI` |
| ALB access-log delivery | `ELBAccessLogTestFile` written; its `Expiration` header names the `expire-alb-access-logs` rule, which proves the cross-module prefix agreement at runtime |
| `RegisterTaskDefinition` with **tmpfs** on FARGATE | accepted; the mounts came back `drwxrwxrwt nginx nginx` |
| `ecs:RegisterTaskDefinition` scoped by resource TYPE | works — the task definition was created on the first apply |

## SPEC-212 — the Lambda image reaches the registry (2026-09-01, TWO OF THREE DISCHARGED)

**Not runnable from a signed-in browser session, and not runnable from a laptop either** — the
deploy role is GitHub-OIDC-only, and the local CLI identity is on no data bucket's allowlist. Every
claim about the image itself is settled in CI against the built artefact (86 handler imports, the
layout set-equalities, the collision and shadowing guards), so what was owed here was only the part
needing the real account. Two of the three settled on the merge runs, and the evidence is a read
against the account rather than a green tick:

| Was owed | Discharged by |
|---|---|
| The deploy role's registry grants work against the real ECR | **Settled.** `Deploy Infrastructure` applied the grant on the grants PR's merge, then created `dat-prod-lambda` on the repository PR's. `describe-repositories` reads back `IMMUTABLE`, `scanOnPush: true`, `AES256` — the three settings the module declares |
| `docker push` actually lands an image under a commit-sha tag | **Settled.** The first `Deploy Lambda image` run on `main` pushed 234 MB under the tag `d3d8b865…`, which is `main`'s head at that commit. `describe-images` reads the tag and its digest back. The workflow asserts this itself for the same reason it is recorded here: nothing consumes the image yet, so a push that silently did nothing would go unnoticed until the cutover |

**Still owed, and it belongs to the next spec:**

| Owed | Why it cannot be run here | What discharges it |
|---|---|---|
| ~~That the image can actually be **run** by Lambda~~ **DISCHARGED 2026-09-02 by SPEC-213** | It named SPEC-213 as the condition, and that spec shipped: all 86 functions run the image | Run [33666840335](https://github.com/agriffi10/data-analysis-prototype/actions/runs/33666840335) invoked 14 of them on the **deployed** artefact and all reached their handler — recorded in full above |

## SPEC-200 — the enqueue paths (2026-08-29, PARTLY RUN 2026-08-30 and 2026-09-10)

**G.5 and two of G.1's ten rows ran on 2026-08-30**, and most of the rest on 2026-09-10; evidence
for both is in [`sessions.md`](sessions.md), and each row below says what is still owed. The steps
were written in full at the arc script's §G — see the note at the top of §1.

| Owed | Why it matters |
|---|---|
| §G.1 — **seven more rows DISCHARGED 2026-09-10** (2, 3, 4, 5, 6, 7 and 10 — mark-read persisting across a reload, build, refresh, share, the data-quality report link, a send landing in `shared_files/agriffith/`, a folder copy); **row 1, create a shared space, is the one still owed** — Andrew chose not to create a throwaway space. Before that: **eight of ten rows.** ~~Row 8, archive~~ and ~~row 9, restore~~ **DISCHARGED 2026-08-30**, each end to end: `POST /v1/enqueue/archive` → 200 → the plane → the notification → the receipt → the source gone. The enqueue body carried **no `actor` and no `identity`**, which is the delegated-actor claim observed. | This is every plane's first real request through the API. A wrong FIFO group still answers 200. |
| ~~§G.2 — the double-submit guard, and table-share's across a forced token refresh~~ **DISCHARGED 2026-09-10**: the same `requestId` twice gave one execution on results-conversion and on file-ops. For table-share, two submits in one clock minute — the old token at 20:55:02, a new token issued 20:55:14 at 20:55:25 — gave one execution. **Both submits must fall in the same 60-second bucket** (`fifo.DEDUP_BUCKET_MS`): two minutes apart is two shares, by design, and so is a double-click that straddles a minute boundary. | The only place the actor-keyed dedup digest is observable live; the change it makes is one share where there used to be two. |
| §G.3 — **five more planes DISCHARGED 2026-09-10** from records already in the log (shared-space, data-quality, file-send, notifications — whose `body_request_id` is `null` because its body has no id — and file-ops): every required field present, and no bearer, email, presigned-URL token, object key or recipient. **Table-builder and results-conversion followed the same evening** once the sweep caught up to 19:24Z: all 3 `tableBuild.create` and all 8 accepted `resultsConversion.enqueue` records up to then, the same fields and absences. **Table-share is still owed**: read the first `tableShare.enqueue` `span.end` in `logs/service=api/year=2026/month=09/day=10/` once that partition runs past 19:52Z, and apply the same field list and absence sweep. Before that: **one plane done, nine owed.** ~~The archive plane's record~~ **DISCHARGED 2026-08-30** with every required field present (`route_id`, `queue`, `actor`, `message_group_id`, `dedup_id` = `body_request_id`, `body_bytes`, `env`, a real `version`) and a **mechanical nine-way absence sweep** over all 470 records in the window returning zero on each. | The field rule at a boundary that now holds a bearer and a user's file selection. |
| ~~§G.4 — the 401, the forged-identity 400 and the 413, each with zero sends~~ **DISCHARGED 2026-09-10**: 401 `SessionExpired`, 400 `InvalidRequest`, 413 `PayloadTooLarge` (the whole-message bound, 380,302 B). **Zero sends shown through the planes, not the lagging log**: no execution carries any of the three body ids, and the same listing over a wider window returns the six executions known to be there. | A refusal issued AFTER a successful send looks identical from outside. |
| ~~§G.5 — the IAM simulation against both DEPLOYED roles~~ **DISCHARGED 2026-08-30** — portal role `implicitDeny` on all eight request queues with an `allowed` control (`s3:GetObject` under the caller's own prefix); API role `allowed` on all eight. **Simulate one resource per call** — `--output text` over a multi-resource simulate prints the decision on the first row only. | The only evidence the browser's grants are actually gone rather than merely absent from the templates. |
| A shared space where the submitter is a non-owner member | Needs a second account. |

## SPEC-211 — Give feedback (2026-09-01) — BROWSER HALF RUN; the CLI half DISCHARGED 2026-09-10

**All six rows below ran on 2026-09-10** — evidence in the 2026-09-10 section of
[`sessions.md`](sessions.md) — **and the blocker this section gave was false**: the laptop identity
READS the admin bucket, which `sessions.md` had recorded on 2026-08-15. The fixture below settled
the first four rows in one read; the over-limit row went through an in-page `fetch` carrying the
page's own bearer.

**The browser half of `e2e.md` §4.17 ran in full on 2026-09-01 and every row passed** — placement
beside the help control and its move into the ☰ drawer below 900px, the unselected/empty opening
state, the disabled gate including a whitespace-only message, Enter making a newline in the message
and Enter from the category select submitting, exactly **one** `POST /v1/feedback` carrying
`category`/`message`/`route` and **no username of any kind**, a **200** whose body is exactly
`{submittedAt}`, the thank-you toast, an empty message on reopen, and `route` naming the page the
dialog was **opened** on rather than the one it was sent from. Evidence in [`sessions.md`](sessions.md).

~~**The half that proves a submission actually landed is still owed**~~ **That half was discharged on 2026-09-10 by the rows below.** It had been owed for a reason that was structural
rather than an omission: the feature is write-only by design, so the only way to see the record is
to read `<admin-bucket>/feedback/YYYY/MM/DD.json` with the CLI — ~~and the local CLI identity is an
IAM user on no data bucket's policy allowlist, so it reads that bucket as absent. One session
cannot hold both halves.~~ **False, measured 2026-09-10:** the admin bucket is readable from the
laptop identity; the user-space and archive buckets are the ones it cannot read.

**A fixture is waiting, so the CLI half is now one command.** Three submissions were made on
**2026-09-01** specifically to satisfy the three-in-one-object row without staging anything:
`bug` from `/query`, `idea` opened on `/query` and sent from `/files`, and `other` from `/files` at
**`2026-09-01T20:22:52Z`**. All three say *"Please ignore"* and name themselves as live checks.
Read `feedback/2026/09/01.json` and the ordering, `version`, attribution and CAS-append rows below
can all be settled at once — but note the date is fixed, so this shortcut expires if the object is
ever pruned.

| Owed | Why it matters |
|---|---|
| ~~The day's object exists after a real submission, with `version` 1 and the entry's `username` taken from the token~~ **DISCHARGED** — `version: 1`, `username: agriffith` on all three entries | The whole attribution claim. A wrong username still answers 200, and nothing in the browser would show it. |
| ~~Three submissions in one day land in ONE object, in order~~ **DISCHARGED** — one object, in `submittedAt` order, the writer's `entries` counting 1 → 2 → 3 | The compare-and-swap append preserving what is there. The unit tests drive a fake S3 with real precondition semantics; only S3 itself proves the real one. |
| ~~The `MessageGroupId` the API stamps and the key the writer derives agree~~ **DISCHARGED** — `message_group_id: "2026-09-01"` against key `feedback/2026/09/01.json` on all three | They are derived from the same `submittedAt` in two languages. Disagreement is silent — two groups writing one object, and the serialization guarantee gone. |
| ~~The writer's structured record carries `message_chars` and **no message text**~~ **DISCHARGED** — `message_chars` 97, 98 and 120; the message text appears 0 times in either day-01 log, and 3 times in the object as the positive control | Asserted in both suites, but the suites read a captured sink; the live check reads the log store a wider audience can. |
| ~~A submission over 4000 characters is refused with `InvalidRequest`, and nothing is sent~~ **DISCHARGED** — 4,001 characters → 400 `InvalidRequest`, *"the feedback message is 4001 characters, over the 4000-character limit"*; the day's object, written earlier by someone else, was untouched | The refusal half, which coverage is close to blind to. **Not reachable from the browser** — the textarea's `maxLength` caps typing and trimming only shortens — so this one needs a hand-rolled `curl` carrying a bearer, not a click. |
| ~~The DLQ stays empty through all of the above~~ **DISCHARGED** — `dat-prod-feedback-requests-dlq.fifo` 0 visible, 0 in flight, 0 delayed, with 14-day retention covering 09-01 | It is undrained and unalarmed by decision, so its depth is the only signal that anything died. |

**What it took, in the end:** the laptop identity's ordinary read of the admin bucket, plus one
in-page `fetch`. ~~**What it would take:** an operator session with `s3:GetObject` on the admin bucket's `feedback/`
prefix, run alongside a signed-in browser.~~ The CLI half is three commands (`e2e.md` §4.17); the
coupling is that they have to be the same submission.

## SPEC-215 — deleting the retired repository variables (2026-09-01)

**Not a browser check — a settings-page edit only the repository owner can make**, which is why it
is recorded here rather than closed on the PR. The workflows no longer read these; leaving them is
not a fault, but a stale value nobody reads is exactly what the next operator will trust.

Sixteen to delete, listed by name in
[`SPEC-215`'s delivery doc](../spec-delivery/SPEC-215-configuration-from-terraform-state.md). Six
were retired by this spec (`API_BASE_URL`, the three `VITE_COGNITO_*`, the two bucket names); ten
were already unread before it (the eight queue URLs, `VITE_ATHENA_WORKGROUP`,
`VITE_COGNITO_IDENTITY_POOL_ID`).

**Order matters and only one way round.** Delete them **after** a green post-merge `Deploy SPA
image` and `Publish Config` — `Deploy App` was the gate when this was written and no longer exists
— never before: if the resolver were wrong about a value, the variables are what the revert falls
back to. To discharge: delete the sixteen, then re-run both workflows and confirm the served
`/config.json` is unchanged. **`VITE_COGNITO_IDENTITY_POOL_ID` is in the sixteen and its pool is
now deleted**, so that one names nothing at all.

**The survivors are not up for deletion** — each is a genuine input, with its reason tabled in
[`.github/workflows/README.md`](../../.github/workflows/README.md). Fourteen `vars.*` names are
referenced after this change, of which **eleven are actually set**; the other three
(`TF_VAR_project_name`, `TF_VAR_environment`, `TF_VAR_verification_principal_arns`) are deliberately
unset and every reference supplies a `||` fallback. `VITE_APP_URL` is the one that reads like a
leftover and is not: Cognito's callback list is built from it.

## Arc B's recipes that outlived their script (ported 2026-09-02)

These were the arc script's own steps, and each is owed with the recipe that makes it runnable.
Without the recipe every one of them is a check somebody would design badly a second time.

| Owed | The recipe, and why the obvious version does not work |
|---|---|
| ~~**A ZAP baseline against the container origin** (SPEC-194 §C.7, non-blocking)~~ **DISCHARGED 2026-09-10 from CI** — the scheduled Security run 34121971677 (2026-09-07) scanned `https://portal.dataquarry.app`: FAIL-NEW 0, WARN-NEW 9, and every alert ID has a disposition in `security-baseline.md`; 10055 and 90004 persist by decision; 10036 passes (no `Server` version). | Diff against `security-baseline.md` **per alert ID, never by total** — a clearing and an appearing finding once cancelled at 305 and made the total look untouched. Expect the `style-src 'unsafe-inline'` **Medium** and the COEP **Info** to persist **by decision**. Expect **no new *Server Leaks Version Information*** row: that alert fires on a version, and `server_tokens off` is what keeps it clear. |
| **A rolling deployment, watched** (SPEC-194 §C.5) | A task serves exactly one image's file set, so a browser holding the **old** shell routed to a **new** task 404s a lazily-imported chunk. Leave a tab open, merge any change under `apps/portal/`, let `Deploy SPA image` run, then navigate to a lazy route in the old tab: it may 404 inside the Suspense boundary, and **a reload recovers**, because the shell is `no-cache`. |
| **The health check doing its job** (SPEC-194 §C.6) | The break has to be **env-only, on the task-definition side, in a variable the image defaults** — add `PORTAL_LOG_LEVEL = "chatty"` to the container definition's `environment` and apply. Two obvious alternatives prove nothing: an entrypoint that exits 1 reddens at the **matrix** and never reaches the deploy gate, and adding a key to the entrypoint's `REQUIRED` list (or removing one from `local.spa_runtime_config`) reddens `pytest` before anything builds. Expect the ECS deployment **not** to reach `COMPLETED` and the workflow to go red **on `rolloutState`**, not on a timeout. Revert and confirm green. Before writing any new recipe here, confirm no test pins what you are about to change. |
| **A genuinely expired token against the API** (SPEC-195 §D.3) | **Do NOT mint it from a throwaway app client**: `oidc_audience` is a *single* client id, so a second client's token is refused on **audience** — the verifier never reaches the expiry check, and `verification_failed` is one reason code covering signature, issuer, audience and expiry alike, so the check passes while proving the opposite. What works is temporarily shortening the **existing** app client's ID-token validity to its 5-minute minimum, signing in fresh, and waiting six minutes. **Restore the validity afterwards**, or every session in the environment expires in five minutes. Expect 401 with a body hashing identically to the no-token refusal. |
| **The stack scrub against a REAL token** (SPEC-195 §D.6) | **It has to be driven by a refusal.** The success path emits no `error` at all, so grepping after a 200 returns 0 for the same reason an empty file does; and a query parameter forces nothing, because the handler passes only the method, path and headers. Send a bit-flipped real token, then sweep the day's `logs/service=api/` for the token's **header** and **signature** segments — with `'"reason": "verification_failed"'` counted **≥ 1** as the positive control, or the two zeros mean the window was empty. |

---

## SPEC-202 — the retirement's checks: the CLI half run 2026-09-02, the browser half owed

**Merge 2 was taken with five checks WAIVED — not passed** (user decision, 2026-09-01): the fresh
sign-in, the deep link and its clocks, the archive row, 400px, and the first half of membership
propagation. *(The waiver was first written as four; the execution log's own row names five, and
five is what this table carries.)* Nothing below was observed at the time it would have gated the
merge. The arc script's §12 said to re-run the fresh sign-in **after** merge 2 — that re-run is the
first row of *Still owed* here, and this ledger is the only live instruction for it.

**Discharged 2026-09-02, from the CLI, against the account** — every one a positive absence rather
than "gone from the plan":

| Check | Result |
|---|---|
| The distribution is destroyed | `cloudfront get-distribution --id E63PRJKNACLDP` → **`NoSuchDistribution`** |
| The static bucket is destroyed | `head-bucket` → **404**; `list-buckets` shows four app buckets plus artifacts, audit and state |
| The Identity Pool is destroyed | `cognito-identity list-identity-pools` → **`[]`** |
| The Cognito lists are narrowed | callback **and** logout are exactly `http://localhost:5173` and `https://portal.dataquarry.app` |
| The API's CORS is narrowed | `allow_origins` is `["https://portal.dataquarry.app"]`, `allow_credentials` false |
| Both buckets' CORS are narrowed | `localhost:5173` and `spa_origin` only, on user-space and shared-space alike |
| The served header set and `connect-src` | the full set present and enforcing-shaped, `connect-src` = `'self'`, `cognito-idp`, the Hosted UI host, both buckets, `api.dataquarry.app` — no `cognito-identity.`, `athena.`, `glue.` or `sqs.` |
| The runtime document | `/config.json` carries **no** `cognitoIdentityPoolId`. It carries eleven keys, not the arc's ten — `maxUploadBytes` arrived with SPEC-216 after the arc's count was written |
| The deploy role's retired grants | inline policy is **22 statements**, `S3StaticBucket` and `CloudFront` both absent (applied by #614) |

**Still owed, and the first one is the one that matters:**

| Check | Why it is not run | What discharges it |
|---|---|---|
| **A fresh sign-in from a clean, signed-out profile** against the narrowed callback and logout lists — **the callback half RAN 2026-09-10 in a normal profile**: a cold Hosted UI cookie, the password screen, `redirect_uri=https://portal.dataquarry.app` accepted with no `redirect_mismatch`, the code exchange 200. **Still owed:** a clean profile or private window, and the logout list, which nothing exercised | Needs a sign-in an agent cannot perform in a clean profile. **Merge 2 narrowed exactly the lists this exercises, and a broken fresh sign-in is invisible to every signed-in session** — this repo lost a day to precisely that shape. | `e2e.md` §4.1, in a private window, in a browser. The `redirect_mismatch` page is the distinguishing symptom. |
| **The deep link and the two clocks** — landing back on `/query?db=…` **after** sign-in, the private-browsing repeat, and a genuinely expired token — **the restore half DISCHARGED 2026-09-10**: `/query?db=agriffith` was captured before sign-in and landed on after it, with the return path consumed. The private-browsing repeat and the expired token are still owed | The capture half was observed 2026-08-31 (`portal.returnPath` is stored); the restore half needs a completed sign-in, and the expiry needs the app client's token validity shortened, which is a change to the environment nobody asked for. | The sign-in above, plus a deliberate token-validity change **restored afterwards** — left at five minutes, every session in the environment expires in five minutes. |
| **The archive plane through the API** | The only irreversible gesture in the pass: a restore is 3–5 billed, uncancellable hours. Held for an explicit go-ahead. | `e2e.md` §4.11's approval gate. |
| **400px** | Not reachable by window resize on macOS (floor 606px), and both breakpoints already read `false` at 606, so 400 and 606 are the same CSS branch — what is unproven is overflow at the narrower width. | DevTools device toolbar, asserting on `matchMedia`. Same row as the responsive pass above. |
| ~~**A real presigned upload AND download from the browser, against the narrowed bucket CORS**~~ **DISCHARGED 2026-09-10 in Chromium, both buckets** — see the SPEC-198 FR-011 row | Merge 2 narrowed both buckets' CORS to `spa_origin` + `localhost:5173`. Nothing since has redeemed a presigned URL in a browser, and `curl` cannot settle a preflight. | `e2e.md` §4.2's upload and download rows, run from `$APP_URL`. A failure here is an opaque `TypeError` with no AWS text — it does **not** look like a CORS problem. |
| **Membership propagation's pre-refresh REFUSAL** | Observed only in its second half: the added member shows Pending and, after a fresh sign-in, the space appears and queries. Switching accounts mints a token that already carries the membership, so the refusal and the fix are indistinguishable from one browser. | Two concurrent sessions, or a membership change made while a session is held. |
| **table-build and table-share notifications carry no `link`** — found 2026-09-01 | Not a failure of the run: it is a real finding against the section's "with a link" clause. Deliberate in code (`tbcommon/notify.py`'s `emit_created` passes none, while the same module passes one for `columns_removed`). | A decision, not a check: either the two planes gain a link or the clause goes. Not load-bearing the way data-quality's is — its reports folder is hidden, these two land where the user can already see the result. |

---

## SPEC-220 — the migration ran, and what the post-`finish` read could and could not see (2026-09-09)

**The one-shot is complete.** `report` `34415568703` (788 keys, no conflicts), `copy` `34234219110`
(788 keys, 0 conflicts), `verify` `34234773116` (40 keys), **`finish` `34415666578` — 788 deleted,
0 absent, 0 refused**, and **`prove-empty` `34415782105` — "every old prefix is empty across every
space"**, run under the deploy role from `main`, which is the identity and the ref the workflow
requires. The proved-empty run is FR-005's evidence and it is recorded here rather than in
[`e2e.md`](e2e.md) because no signed-in session can make it: it enumerates both space buckets.

**The post-`finish` catalog read, and the population it could not reach.** FR-004 left one row owed
after the pre-`finish` pass: re-read every table's `LOCATION` once the sources were gone. Run this
session through the portal's own API, by wrapping `fetch` in the signed-in page and driving the
schema rail, so the session's bearer was never read out of the browser.

| What | Result |
|---|---|
| The three real shared tables | Still `{space}/shared_tables/{table}`. `shared_tables/` did not move, and did not. |
| Tables pointing into a moved prefix | **One of 16 located tables** — `dwb_testing_all.lotto_draws_by_year` → `s3://dat-prod-user-space/admin/system_settings/athenaresults/tables/89cfcb49-…`. It is at the **new** home, and its uuid appears in **zero** of the record's 788 keys, so `finish` did not touch it: a table created after the write switch. |
| Did `finish` delete any table's data? | **No.** The 788 deleted sources are 331 `.csv`, 348 `.metadata`, 107 `.txt` and 2 `.json`, with **zero** keys under any `athenaresults/tables/` subfolder — Athena result artifacts, not table backing data. |

**The 09-09 pre-`finish` reading of "zero located tables point at these prefixes" was true of that
day's population and is NOT a durable invariant.** A table created from query results legitimately
lives under `system_settings/athenaresults/tables/`, and one now does. Anything written later that
repeats the absence as a rule is wrong.

| Still owed | Why one signed-in session cannot close it |
|---|---|
| The same `LOCATION` read across **every** Glue database, not the nine this session can see | `agriffith` sees its own database and the eight shared spaces it belongs to. A table in another user's personal database could in principle have been located under their old prefix. What bounds the risk is the extension-and-population evidence above — the deleted set contains no table data of any kind — rather than a sweep. A full sweep needs the deploy role, which is a Lake Formation data-lake admin; no workflow currently exposes a Glue read, and adding one for a check whose risk is already bounded was not worth a new dispatchable surface. |

---

## SPEC-219 — the new `system_settings/` Denies, proved either side of the apply (2026-09-06)

**DISCHARGED.** FR-004's IAM half. The route half is **not** here: it runs from a signed-in session,
so by this file's own scope it belongs in [`e2e.md`](e2e.md)'s API table. Both halves were run on
2026-09-09 and both answered `explicitDeny` / 403; SPEC-220's narrowing then made the
`{root}archive/` twin an ordinary writable path, and that row now expects **200**.

| Check | Before the apply | After |
|---|---|---|
| `s3:PutObject` on `alice/system_settings/archive/x` | `allowed` | **`explicitDeny`** |
| `s3:DeleteObject` on `alice/system_settings/athenaresults/x` | `allowed` | **`explicitDeny`** |
| `s3:PutObject` on `alice/system_settings/notes.txt` — the control | `allowed` | `allowed` |

**The BEFORE column is the evidence, and it is why this was measured twice.** Read only afterwards,
an `explicitDeny` proves nothing: `UserPrefixObjects` grants the whole personal prefix, so the
before-value had to be `allowed` for the after-value to mean the sibling did it. The third row is the
control that the Deny is not wider than its resource — a bare key under the same prefix stays
writable.

Run from the operator's CLI identity (`arn:aws:iam::696000197480:user/tofu-deploy-user`) against
`arn:aws:iam::696000197480:role/dat-portal-user-role`, bucket `dat-prod-user-space`, **one resource
per call** — `--output text` over a multi-resource simulate prints the verdict for row one only.

```
aws iam simulate-principal-policy --policy-source-arn "$R" --action-names <action> \
  --resource-arns "arn:aws:s3:::dat-prod-user-space/<key>" \
  --context-entries ContextKeyName=aws:PrincipalTag/username,ContextKeyValues=alice,ContextKeyType=string \
  --query 'EvaluationResults[0].EvalDecision' --output text
```

## 3. Discharged, and worth not re-litigating

Kept short on purpose — the reasoning lives in `docs/decisions/` and the delivery docs. These are
here so a reader does not re-open them as gaps.

| Settled | When |
|---|---|
| The `sqlLiteral` path (`O''Brien`) against the real engine; the disclosed SQL is byte-identical to Athena's `QueryString`; a filter apply is a new execution while a cache hit issues zero | 2026-08-15 |
| Data Explorer paging (0 executions), copy/export (the export held 150 rows to the page's 100), the `.sql` round trip in both directions | 2026-08-16 |
| The refresh arc's add / refuse-naming-the-column / link / opt-in sequence, flat **and** partitioned, and the casing control | 2026-08-14, 2026-08-16 |
| `saved_queries/` client-side refusal, personal and shared, byte-exact with no confirm reachable | 2026-08-15, 2026-08-16 |
| `env` and a real build sha on 809 post-deploy log records across four services | 2026-08-15 |
| The archive execution role's 13-row policy simulation, four rows moving to `explicitDeny` | 2026-08-12 |
| The username directory read; the cross-bucket saved-query `PutObject`; the disagreeing-files data-quality finding | 2026-08-14 |
