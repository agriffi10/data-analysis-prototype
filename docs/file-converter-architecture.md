# Architecture Decision: Convert Files to Parquet (the "File Converter" control plane)

**Status:** Proposed — **re-architected 2026-07-11 (v3)** after the 250 GB file-size requirement landed; **corrected to v3.1** after an adversarial review verified every Athena claim against AWS documentation (§0.1); **Excel deferred 2026-07-13** (see the note below §0). Drives the file-converter spec arc (SPEC-115→121, +122 optional, last).
**Last Updated:** 2026-07-13
**Related:** `docs/architecture-review-2026-07-11.md` (the review that drove v2; **its "no catalog access" praise is superseded here — see §0**), `docs/table-builder-architecture.md` (the control-plane pattern, the DDL/partition-projection machinery this now reuses directly, and the CSV/single-sample-file limitations this pipeline removes upstream of), `docs/data-quality-architecture.md` (the sibling diagnostic pipeline, same engine choice), `docs/shared-spaces-architecture.md`, `docs/best-practices/lambdas/lambdas.md`, SPEC-032 (Athena/Glue/Lake Formation foundation — **now a hard dependency**), SPEC-056/057, SPEC-058 (notifications), SPEC-066→072 (table-builder), SPEC-107 (`control-plane-common` layer).

> Read this before writing or implementing any file-converter spec. It records *why* the feature looks the way it does. Implementation detail lives in the arc specs (SPEC-115→121, +122 optional, last) and the code.

> **2026-07-13 — Excel is deferred entirely (user decision).** The `convert-excel` Lambda branch, the format `Choice`, and the `fastexcel` half of the polars layer were **removed from the spec drafts**; `.xlsx` is now a terminal `unsupported_format` in both arcs, like any other unsupported extension. The Excel sections below (§4.3, §5.1, and the related notes) are **kept as a record** — the reasoning (Lambda-bound, safe only because Excel's own format caps at ~1.05M rows, compressed-size memory trap) is what a revival will need.

---

## 0. What changed in v3, and why (read this first)

v1 and v2 of this doc specified a **Lambda pipeline**: polars reading and rewriting each file, one invocation per file, fanned out by a Step Function `Map`. v2 also made a virtue of the fact that the execution role needed **no Glue, Athena, or Lake Formation grant at all** — the narrowest control plane in the project.

**Both of those are now wrong, because the real file sizes are up to 250 GB.**

Lambda's hard ceiling is **900 seconds**. Reading and rewriting 250 GB inside that window would require sustaining roughly 285 MB/s end-to-end — S3 read, CSV parse, cast, Parquet encode, S3 write — on a single function. Realistic throughput is 50–150 MB/s, which puts a single 250 GB file at **30 to 80 minutes**. No memory tier (the real max is 10,240 MB, not the 3008 MB v2 assumed), no ephemeral-storage setting, and no amount of polars lazy-streaming changes this: `sink_parquet` solves the *memory* problem elegantly but cannot solve the *time* problem, because the bytes still have to move. **Lambda is definitively out for a full pass.**

**Fargate was considered and rejected** (§9). It would work, but it means introducing a VPC to a project that has none, plus ECR, a Docker build pipeline, and an ECS cluster — in order to get a *single big box* doing serially what a distributed engine would parallelize.

**Athena is that distributed engine, and this project already owns it.** SPEC-032 shipped Athena, Glue and Lake Formation; SPEC-066→072 shipped the DDL, partition-projection and Athena run-and-poll machinery. Turning a large pile of CSV into typed Parquet is precisely what Athena is built for, and it does 250 GB in minutes rather than tens of minutes.

**The cost of that decision, stated plainly:** the execution role now needs **Glue + Athena + Lake Formation admin**, exactly as table-builder's `execute-ddl` role already does. The "zero catalog access, tiny blast radius" property that v2 was proud of is **gone**. That was a good property. It is not worth 250 GB of unconvertible data.

The v2 review's structural findings that **still stand and are carried forward**: the hashed `MessageGroupId` (§2.3), the reserved-prefix blocklist including `user_settings/` and the IAM `Deny` (§6), the S3-manifest-between-states rule (§2.2), and the empty-destination requirement (§5).

## 0.1 Corrections in v3.1 — verified against AWS documentation

The v3 draft asserted several Athena behaviours from memory. An adversarial review checked each against AWS docs. **Four were wrong**, and they were load-bearing. They are corrected throughout, and recorded here so the errors are not reintroduced.

- **There is NO workgroup query-timeout setting.** v3 said "a dedicated workgroup with its query timeout set to the maximum permitted." No such field exists on `WorkGroupConfiguration`. The DML query timeout is an **account- and Region-level Service Quota**: **30 minutes by default, raisable to 240 minutes only by a quota-increase request** (a support ticket, not Terraform). This is a **hard ceiling on the whole feature**, and it must be treated as a deployment prerequisite, not a config value (§6.2).
- **`UNLOAD` does NOT require an empty destination when `partitioned_by` is used.** v3 claimed the empty-destination rule was "enforced twice — once by us, once by the engine." AWS documents the emptiness requirement **"except when writing to partitions"** — which is exactly the path this pipeline uses for partitioned sources. So **our own pre-check is the only guard**, and it must be treated that way (§3.1, §5).
- **`StartQueryExecution` needs a `ClientRequestToken`.** Without it, a Step Functions `Retry` after a transient error that arrived *post-submission* starts a **second** `UNLOAD` into the same destination. Combined with the point above, both would succeed and the destination would **silently double-count every row** — the exact disaster §5.1 guarded against on the (now-deferred) Excel path, left wide open on the Athena path. `ClientRequestToken = requestId` makes submission idempotent (§5.2).
- **Table names must be safe identifiers.** v3's literal DDL used `_fc_{requestId}` — a leading underscore (which Athena requires backticks for) containing a **UUID with hyphens** (which parse as subtraction). It would not run. Table names are now `fc_tmp_{hex32}` (the request UUID with hyphens stripped): no leading underscore, no hyphens, no quoting needed.

Two further AWS facts the v3 draft simply didn't know, both now designed for:

- **`UNLOAD` writes a data manifest** listing every object it created, to the **query-results** location (`Statistics.DataManifestLocation`) — *not* to the output location. That manifest is the correct basis for `finalize`'s completeness check (§5.3), and it is far better than counting objects in a prefix.
- **Partition columns must come LAST in the `SELECT` list** of an `UNLOAD` with `partitioned_by`.

And one performance trap: **compressed text is not splittable.** A single 250 GB `.csv.gz` would be processed by **one worker** and would certainly exceed the DML timeout. Source files must be uncompressed, or split across many objects (§10).

---

## 1. What we're building

From the **file browser**, on a **file or a folder** of CSV/TXT or JSON/NDJSON files (personal space or a shared space), a user can press **"Convert to Parquet."** The pipeline reads the source with **real type inference** — dates and numbers come out typed, not as strings — and writes the result as Parquet files to a destination **within the same space**. The user is told via the notifications inbox (SPEC-058→060) where the output landed, so their next step is naturally Table Builder's existing "create table from this folder," now pointed at Parquet instead of the original messy input.

This pipeline exists because Table Builder's CSV path is a deliberate simplification: every CSV column comes out as a string (`table-builder-architecture.md` §4), and schema for a multi-file folder is taken from a single sample file (§10). Converting to Parquet **first** removes both limitations before the data ever reaches the catalog.

**Supported inputs (v1): CSV/TXT and JSON/NDJSON — everything goes through Athena.** Excel `.xlsx` was in the v3 design as a separate Lambda path (§4.3) but is **deferred entirely (user decision 2026-07-13)**: `.xlsx` is a terminal `unsupported_format` like any other unsupported extension. Format is classified by extension (one trailing `.gz` stripped first), a **deliberately larger set than Table Builder's** — its `_EXT_FORMAT` (`inspect_source.py:22-28`) has no `.txt`. A content/extension mismatch is undetected (§10).

## 2. Orchestration — a dedicated SQS → Pipe → Step Function, with the work done by Athena

```
Browser (scoped creds: sqs:SendMessage only, + the ID token in the body)
   │  request: { requestId, actor(idToken), space{kind,bucket,prefix}, source, destination }
   ▼
SQS (FIFO) ──▶ EventBridge Pipe ──▶ Step Function (Standard)
                                      │
                                      ├─ validate-authorize   (ID token → actor; authorize source; destination: same space, not reserved, EMPTY)
                                      ├─ inspect-source       (list; classify; probe EVERY file's header+schema; REJECT heterogeneous CSV headers; write a manifest to S3)
                                      ├─ reconcile-schema     (pure reduce → one target schema → a CAST list; no bulk I/O)
                                      ├─ create-temp-table    (external table over the SOURCE; CSV = all-string OpenCSVSerde)
                                      ├─ start-unload         (Athena UNLOAD … TO {destination} WITH format=PARQUET)
                                      │      ┌─ Wait(30s) ──▶ check-query ──┐   ◀── the poll lives in the STATE MACHINE,
                                      │      └──────── Choice(RUNNING) ◀────┘        not inside a Lambda (§2.1)
                                      ├─ finalize             (verify against the UNLOAD manifest; emit the summary the notification is built from)
                                      └─ drop-temp-table      (Glue only — safe on every path, §2.4) ──▶ Succeed
```

One path, one engine — there is **no format `Choice`** (Excel is deferred; note above §0), and the success order is `… → Finalize → DropTempTable → Succeed` (SPEC-115 FR-001).

**Decision — a NEW, dedicated pipeline.** Converting a file is an unrelated workflow from creating a catalog table, sharing one, or diagnosing one; folding it into an existing orchestrator would re-broaden that role (`lambdas.md` §1). A dedicated SQS+DLQ → Pipe → Step Function lives in `infra/modules/file-converter/`. It reuses the **pattern**, not the resources — and now also reuses table-builder's **DDL and partition-projection code** through `cpcommon`/`tbcommon`, rather than reimplementing it.

**Decision — single-task Lambdas** on the shared **`cpcommon`** layer (SPEC-107) plus an **`fccommon`** domain layer. Only `inspect-source` carries polars (the per-file schema probe, §6.3).

### 2.1 Decision — the Athena poll lives in the Step Function, not in a Lambda (NEW, and load-bearing)

Table-builder's `execute-ddl` runs an Athena query and polls for completion **inside** a 300-second Lambda (`infra/modules/table-builder/locals.tf:37`). That works for a `CREATE EXTERNAL TABLE` statement, which returns in seconds.

**It would be fatal here.** A 250 GB UNLOAD runs for minutes to tens of minutes, and no Lambda can hold a poll loop open that long. So the pipeline **starts** the query in one short Lambda, and the Step Function itself does the waiting: `Wait(30s) → check-query → Choice(RUNNING ? loop : done)`. Step Functions Standard executions run for up to a year, so **the time ceiling disappears entirely.** This is the single most important structural difference from every other control plane in this project, and it is why "just reuse execute-ddl" is not the answer.

### 2.2 Decision — states pass an S3 manifest pointer, not inline arrays (carried from v2)

Step Functions caps a state payload at **256 KB**. A large folder's file list plus per-file schemas will exceed it, and `States.DataLimitExceeded` is thrown **outside** any `Catch` — so the user would get **no notification at all**, the worst failure mode in the pipeline. `inspect-source` writes a manifest to S3 and passes its key; `reconcile-schema` reads it and writes back the target schema. Inline state stays small by construction.

### 2.4 Decision — the pipeline holds NO `s3:DeleteObject`, anywhere (v3.1 — this is a security fix)

The v3 draft had a `Cleanup` state, reached by a `Catch` on **every** state, which deleted "partial output under the destination" — and a claimed `s3:DeleteObject` "scoped to the destination prefix only."

**Both halves of that were wrong, and together they were a serious vulnerability.**

The scoping is **not expressible in IAM**. The destination is arbitrary user-chosen text, so the policy resource has to be `{bucket}/*`. There is no such thing as a delete grant scoped to a prefix the *message body* names.

And because the `Catch` covered **every** state — including `validate-authorize` — a failure *in the validator* still reached the destructive cleanup, acting on a `destination` that had **never been validated** and came straight from the request body. Every portal user holds `sqs:SendMessage` on this queue. So: enqueue a message with a garbage ID token and a *different user's* path as the destination; validation fails; cleanup fires; **their files are deleted.** An authenticated cross-user file-delete primitive, handed out by the cleanup path.

**The fix — remove the capability entirely rather than trying to scope it:**

- **`s3:DeleteObject` is granted nowhere in this pipeline.** Not on the destination, not on the scratch prefix, not anywhere.
- `drop-temp-table` touches **Glue only** — it is therefore safe to reach from any failure path, including a validator failure, because the worst it can do is drop a table the pipeline itself created.
- **Partial output is not cleaned up automatically.** If an `UNLOAD` fails partway, the notification tells the user that partial files may remain and names the path. They delete it themselves in the file browser (it is their own space, and it is not a protected prefix).
- **The empty-destination rule (§3.1) then blocks a retry until they do** — which turns a manual cleanup step into a *safety interlock*, not just a chore. It is impossible to retry into a half-populated destination and silently double the data.

This costs a manual step after a rare failure. It buys the removal of a delete grant that could not be safely scoped, on a pipeline every user can invoke. That is a trade worth making, and it is the reason the whole `Cleanup` state disappeared.

### 2.3 Decision — `MessageGroupId` is a HASH of the destination (carried from v2)

The queue is FIFO so two conversions targeting the same destination serialize. **`MessageGroupId` = the SHA-256 hex digest of the canonical destination location** — a fixed 64 characters, **never the raw location**. SQS caps `MessageGroupId` at **128 characters** and S3 keys reach 1024; every existing producer gets away with a raw id only because it uses a bounded catalog identifier (`tableShare.service.ts:66`, worst case 127 chars *by construction*). **`MessageDeduplicationId` = `requestId`.**

## 3. Authorization

The request carries the caller's Cognito **ID token**; `validate-authorize` verifies it offline against the User Pool JWKS and derives the actor from the `cognito:username` claim (`cpcommon.auth`), never from the body.

- **Source:** personal ⇒ the source must resolve inside the actor's own prefix. Shared ⇒ the registry record must have `status == "active"` **and** the actor must be in `members`.
  **Note:** "active" is the **space's** provisioning status, *not* SPEC-073's per-member Pending/Active join chip. SPEC-073 is explicit that access is granted at add time, so a **Pending member passes** this check.
- **Destination:** must resolve within the **same space** as the source (unlike Table Share, this pipeline never writes across spaces).

### 3.1 Destination policy — user-chosen, with a warning and hard backstops (user decision, 2026-07-11)

**The destination stays user-overridable.** A pipeline-owned reserved namespace was proposed and **rejected** in favour of user control. The risk that accepts is recorded here so nobody rediscovers it as a bug.

**The risk.** Athena reads **everything** under a table's `LOCATION`. Parquet landing inside a prefix an existing Glue table already points at means that table's next query either fails on a schema mismatch or — worse — **succeeds and returns silently-wrong unioned rows**.

**Three layers of mitigation, in order:**

1. **A non-empty destination is a terminal conflict** (§5), which is stronger than it sounds: a live table's `LOCATION` is by definition **not empty**, so the *direct* collision is already blocked.

   **v3.1 correction — this is our only guard, not a belt-and-braces one.** v3 claimed Athena enforced it too. It does not: AWS requires an empty `UNLOAD` destination **"except when writing to partitions"**, and the partitioned path is precisely the one this pipeline uses for partitioned sources. So `validate-authorize`'s pre-check is load-bearing and alone. Do not weaken it on the assumption that the engine will catch what it misses.
2. **A reserved-prefix blocklist** in `validate-authorize`: `athenaresults/`, **`user_settings/`**, `shared_tables/`, `_data-quality-reports/`, **`_fc-work/`** (this pipeline's own scratch prefix), plus the root `DO_NOT_DELETE.txt`. `user_settings/` was missing from v1 — see §6 for why that was a data-loss bug.
3. **A UI warning naming the residual case precisely** (SPEC-120): a destination **nested underneath** an existing table's folder is empty, passes every check, and *will* be picked up by that table's queries.

**Residual accepted risk:** a user who deliberately nests output under a live table's LOCATION can still poison that table's results. Detecting it would need a Glue `GetTables` on the actor's database — which, note, the role now *has* (§6). Using it is a **cheap follow-up**, not v1 scope; it was rejected in v2 because the role had no catalog access, and that rationale no longer holds. Recorded so the option isn't forgotten.

## 4. Source inspection, reconciliation, and the two engine paths

### 4.1 Inspection

`inspect-source` lists the source (`cpcommon.s3_listing`, segment-level hidden-path rule per SPEC-107), classifies by extension, fails on a **mixed-format** folder, and probes **every** file's header and schema — not one sample file, which is exactly the Table Builder limitation this arc removes. Probing is cheap: a polars `scan_*().collect_schema()` reads a Parquet footer or a bounded head, not the file.

Caps: a **max object count** (default 1000, mirroring `SHARE_MAX_OBJECTS`) and a **max partition-value count** (§4.2). There is **no max total size** on the Athena path — that ceiling was a Lambda artefact and no longer exists. The one byte count that still matters is the cap on compressed `.gz` objects (gzip is not splittable — §10).

### 4.2 Schema reconciliation — and what Athena can and cannot do

`reconcile-schema` unions the probed schemas into **one target schema**, which becomes the `CAST` list in the UNLOAD's SELECT.

**Type reconciliation gets *easier* with Athena, not harder.** Reading CSV through the OpenCSVSerde gives every column as a **string**, so the "file A infers Int64, file B infers Float64" conflict never arises at read time. You probe the files, decide the target type once, and express it as a `CAST`. The widening rules still apply (integer widths → the widest; int + float → float; date + datetime → datetime; any irreconcilable pair → **string fallback** for that column only, recorded and surfaced to the user), but they now produce a CAST list rather than a polars schema.

**Column union across mismatched CSV headers is the one thing Athena cannot do — and v1 rejects it (user decision).** An Athena external table has **one** schema for the whole folder, and for CSV it reads columns **by position**. Files that disagree on column names or order would be **silently misaligned** — the worst possible outcome. So: if `inspect-source` finds that the CSV files in a folder do not share a consistent header, the request is a **terminal `inconsistent_headers`** naming which file differs and how, and pointing the user at the data-quality check. Type widening still works fully; only column *union* is lost.

**JSON is unaffected.** Athena's JSON serde matches by **key name** and yields nulls for missing keys, so a JSON folder with drifting keys reconciles naturally — the one place the original union-by-name promise survives intact.

**Partition layout is preserved** where the source has Hive-style `key=value/` directories: the temp external table declares the partition columns with **partition projection** (reusing table-builder's exact machinery, SPEC-069), and the `UNLOAD` uses `partitioned_by` to reproduce them in the output. Athena caps this at **100 partitions per CTAS/UNLOAD**, so a source exceeding that is a terminal `too_many_partitions` with a clear message.

### 4.3 Excel — DEFERRED entirely (user decision 2026-07-13; design kept as a record)

**Excel is out of the arc.** `.xlsx` is a terminal `unsupported_format` like any other unsupported extension; there is no `convert-excel` verb, no format `Choice`, and no `fastexcel` in the polars layer. The v3 design below is kept as the record a revival will need.

**Athena cannot read `.xlsx` at all.** But Excel is bounded by its own format — roughly 1.05 million rows maximum — so it is *always* a small-file case. The deferred design routed `.xlsx` via a `Choice` state to **`convert-excel`**, a polars-in-Lambda verb: first sheet only, header on row one, a per-object size cap (default **250 MiB**, because Excel is materialized in memory rather than streamed — the compressed-size memory trap), and **deterministic output keys** (§5.1). It alone would have carried `fastexcel`. The path was safe as a Lambda precisely because Excel's own format caps the data.

A workbook with a title/legend row before the real header, or a trailing summary row, was out of v1; multi-sheet selection was deferred even within this path.

## 5. Output

The Athena path runs **`UNLOAD (SELECT …) TO '{destination}' WITH (format = 'PARQUET')`** — deliberately **`UNLOAD`, not `CTAS`**. Both write real Parquet objects to a prefix you choose; the difference is that CTAS *also* registers a table in the Glue catalog, which would then have to be dropped, whereas `UNLOAD` **creates no table at all**. Since the deliverable here is *files*, not a table, `UNLOAD` is the primitive that matches the requirement, and it removes an entire cleanup step.

**A non-empty destination is a terminal conflict** — no overwrite. **Enforced by us alone** (§3.1) — Athena does not enforce it on the partitioned path.

**Partition columns must come LAST in the `SELECT` list** of an `UNLOAD` with `partitioned_by`. Not optional; the statement fails otherwise.

**Output file names are engine-chosen.** Athena decides how many files to write and names them itself, so the v2 promise of a 1:1 `part-0.csv → part-0.parquet` mapping is **gone on the Athena path**. At 250 GB that is a feature, not a loss: you want the engine splitting output into sensibly-sized files rather than emitting one 40 GB Parquet blob.

### 5.2 Decision — replay-safety = `ClientRequestToken` + the empty-destination interlock (v3.1)

v3 said replay-safety came from "empty-destination + cleanup-on-failure." §2.4 removed the cleanup (it was a vulnerability), and §0.1 showed the empty-destination rule is **not** enforced by Athena when partitioning. So the mechanism is rebuilt:

- **`StartQueryExecution` carries `ClientRequestToken = requestId`.** A Step Functions `Retry` after a post-submission transient error then returns the *same* query execution rather than starting a second `UNLOAD`. Without this, two concurrent `UNLOAD`s into the same partitioned destination would both succeed and the data would be **silently doubled**.
- **A failed `UNLOAD` may leave partial output, and the pipeline does not delete it** (§2.4). The notification names the path; the user clears it.
- **The empty-destination pre-check is therefore an interlock**: a retry cannot start until the destination is empty again, so it is impossible to re-run into a half-populated folder and double the rows.

### 5.3 Decision — `finalize` verifies against the `UNLOAD` manifest, not by counting objects (v3.1)

`UNLOAD` writes a **data manifest** listing every object it created — to the **query-results** location, not the output location (`Statistics.DataManifestLocation`). `finalize` reads that manifest and asserts every listed object exists. This is strictly better than "is the destination non-empty," which cannot distinguish a complete conversion from a half-written one.

### 5.1 The Excel path kept deterministic keys (deferred — record only)

*(Deferred with the Excel path, 2026-07-13 — kept as the record a revival needs; nothing in the arc uses it.)* `convert-excel` would have written exactly one output object per input, at a key that is a **pure function of the source key** (`sales/book.xlsx → {destination}/book.parquet`) — no UUID, no timestamp, no engine part number. A replay overwrites byte-identically. This mattered because no verb in this codebase does request-id idempotency checking; on a Lambda path, deterministic keys **are** the replay-safety mechanism. (If output names were nondeterministic, a retry would write a *second* set of files and the table Table Builder later builds over the folder would **silently double-count every row**.)

## 6. Execution role — one shared role, now with catalog access

The Step Function and all verb Lambdas **share ONE execution role**, as in table-builder and table-share.

**It needs Glue, Athena, and Lake Formation admin.** Target databases are dynamic (per user, per shared space), so they cannot be statically LF-granted — the same reasoning that made table-builder's `execute-ddl` role an LF admin (SPEC-070). The role needs: Glue create/get/delete table (for the temp external table), Athena `StartQueryExecution`/`GetQueryExecution`, `lakeformation:GetDataAccess`, and the Athena results location.

**This is the property v2 gave up.** It is worth naming that the blast radius is now comparable to Table Builder's, and the compensating controls below are what keep it acceptable.

**S3 grants, and the `Deny` that makes them safe:**

- `s3:GetObject` + `s3:ListBucket` on the source.
- `s3:PutObject` on the destination; `s3:ListBucket` on the destination (the empty-destination check and `finalize` both need it).
- `s3:PutObject` **and `s3:GetObject`** on `_fc-work/`. **The read is not optional** — `reconcile-schema` reads the manifest and `start-unload` reads the target schema. (v3 granted write only. This is the identical bug the data-quality doc congratulates itself on having fixed, reproduced verbatim in the other arc. Caught by review.)
- Read/write on the **Athena results prefix**, including `s3:AbortMultipartUpload`, `s3:ListBucketMultipartUploads` and `s3:GetBucketLocation` — a 250 GB `UNLOAD` is certainly multipart, and Athena needs these to write its output at all.
- **`s3:DeleteObject` is granted NOWHERE** (§2.4). This is the security fix, and it is the reason the pipeline cannot clean up after itself.
- An explicit **`Deny s3:PutObject` on `*/user_settings/*` and `*/DO_NOT_DELETE.txt`** in **both** buckets.

**Why that `Deny` is not optional.** The user-space policy denies `s3:DeleteObject` on `user_settings/*` but leaves **`s3:PutObject` wide open** (`analytics/policies/portal-role-analytics.json.tftpl:67-72`). Any role that can write in a user's space can overwrite `user_settings/notifications.json` — **destroying the notification inbox permanently, with no way for the user to recover, because deleting the corrupt file is itself IAM-denied.** The empty-destination rule does not save you: on a fresh account `user_settings/` is empty before the first notification is written. The `Deny` is what makes the guarantee; the §3.1 blocklist is defence in depth on top of it. (Shape to copy: the cross-bucket deny at `table-share/policies/execution.json.tftpl:59-68`.)

### 6.2 The Athena workgroup — and the account quota that is the real ceiling (v3.1)

v3 said "a dedicated workgroup with its query timeout set to the maximum permitted." **No such setting exists.** Corrected:

- **The query timeout is an account/Region Service Quota**, not a workgroup property: **30 minutes by default**, raisable to **240 minutes** only via a quota-increase request. This is a **deployment prerequisite** — a support ticket, not Terraform — and it is the **real ceiling on the whole feature**. It must be requested and confirmed before the arc ships, and the value recorded.
- **`bytes_scanned_cutoff_per_query` must be unset (null) on this workgroup.** The existing portal workgroup carries a **10 GiB** cutoff as a cost guardrail (`infra/modules/analytics/athena.tf:36`). A 250 GB scan is **25× that**, so copying the existing module's shape would make every real conversion fail with "bytes scanned limit exceeded." Removing it is deliberate, and it removes the project's only cost guardrail on its most expensive operation — which is why §10 records the cost honestly.
- **Result location is set per query**, not on the workgroup: a workgroup has **one static** result location, so per-space routing requires `ResultConfiguration.OutputLocation` on each `StartQueryExecution` with `enforce_workgroup_configuration = false` — exactly what the existing portal workgroup already does (`infra/modules/analytics/athena.tf:24-27`).
- A query that exceeds the quota is a terminal `query_timeout` telling the user the source is too large — not a silent hang.

### 6.3 The layer stack (v3.1 correction; updated for the Excel deferral)

The **polars layer** attaches to **`inspect-source` only**, and declares polars only — **no `fastexcel`** (Excel is deferred, 2026-07-13). The v3.1 correction stands as a record: v3 said the heavy layer rode "only `convert-excel`" while simultaneously requiring `inspect-source` to probe every file's schema with `polars scan_*().collect_schema()` — a contradiction that made `inspect-source` unable to do its job. With Excel gone, `inspect-source` is the layer's sole carrier, and SPEC-107's **combined per-function size guard** must pass for it. (v3 claimed the layer-size risk had "largely evaporated" because only one function carried polars. That was wrong, and the guard exists precisely so the mistake surfaces in CI rather than at deploy.)

## 7. Async UX + notifications

The browser never blocks; after enqueueing it shows a transient "converting…" toast. The durable outcome reuses the SPEC-058 trusted-producer `create` contract: **one notification to the actor** (one recipient, like Table Builder) naming the **destination path** on success, or a friendly failure reason.

**A success notification must also report any string fallback** (§4.2). A conversion can succeed while quietly turning a column into text because two files disagreed irreconcilably; the notification is the only moment the user can learn that. "Converted 12 files" alone is not sufficient.

Failure text is **friendly, never raw Athena/AWS text** — `cpcommon.messages` (SPEC-106), with raw detail confined to CloudWatch and the SFN execution history. Emission is best-effort, and `@notifies_on_failure` ensures an unexpected crash still reaches the user. Terminal `RecordSuccess`/`RecordFailure` states are `Pass` → `Succeed`/`Fail`; **nothing durable is written to S3 by a terminal state** — the converted output is the artefact.

## 7.1 Optional chain — "create a table from the converted files" (decided 2026-07-12, user request)

The convert dialog carries an optional **"Create a table from the converted files"** checkbox. Ticked, the pipeline **enqueues a Table Builder request** on the user's behalf once the conversion succeeds. Detail: **SPEC-122**.

**Table building stays in Table Builder.** The converter enqueues; it does not generate DDL, infer schema, or create a table. There remains exactly one implementation of "create a table from a folder," and it is the one already shipped.

**The hard part is the trust boundary, and it is infrastructural, not textual.** Table Builder derives the username from a verified Cognito ID token and never trusts a body-supplied actor. A Lambda cannot mint a token, so the converter must *assert* an identity — and that assertion must be **unreachable from the browser**, because a user who could forge it would make Table Builder create a table in **another user's database over another user's data**.

So Table Builder gains a **second, internal FIFO queue** that only the file-converter execution role may write to (the portal role gets no grant), fed into the **same** state machine by a **second EventBridge Pipe** whose **input transformer stamps the trust marker**. The public Pipe explicitly stamps that marker `null`. The marker is therefore set by infrastructure and can never be smuggled in a message body. A trusted producer asserts **identity only** — the asserted actor is still authorized against the space exactly as a token-derived one is.

**The shipped notifications pipeline is explicitly NOT the model here.** `notifications_writer.py::_resolve_username` takes `username` straight from the body for `create` actions with no verification, while the portal role holds `SendMessage` on that same queue — so a browser can inject a notification into any other user's inbox today. That is a real, low-severity, shipped hole, tracked separately. It is named here so nobody "follows the existing pattern" into a much worse one.

**Forwarding the user's ID token was considered and rejected:** a 250 GB conversion can outlive a default one-hour token, so the build would fail with a confusing `unauthorized` *after* the conversion succeeded — and a live bearer token would sit in Step Functions execution history for the duration.

## 8. Key decisions

- [x] **Athena `UNLOAD` is the engine** for CSV/JSON — not Lambda, not Fargate, not CTAS. 250 GB in minutes; `UNLOAD` writes files without creating a table.
- [x] **The Athena poll lives in the Step Function** (`Wait → check → Choice`), not inside a Lambda — this is what removes the time ceiling (§2.1).
- [x] **The execution role takes Glue + Athena + LF admin.** The v2 "zero catalog access" property is deliberately surrendered; 250 GB is worth more.
- [x] **Heterogeneous CSV headers are rejected**, with a message naming the offending file (user decision). Athena reads CSV positionally and would silently misalign them. Type widening still works; column *union* does not. JSON is unaffected.
- [x] **Excel is deferred entirely** (user decision 2026-07-13) — `.xlsx` is a terminal `unsupported_format`; the polars-in-Lambda path a revival would need is recorded in §4.3.
- [x] **Destination is user-chosen** (§3.1); the nested-under-a-table-LOCATION risk is accepted, warned about in the UI, and now *cheaply fixable later* since the role has Glue read.
- [x] **The pipeline holds NO `s3:DeleteObject`** (§2.4) — a security fix. `drop-temp-table` is Glue-only and safe on every path; partial output after a failure is left for the user to delete, and the empty-destination rule makes that an interlock rather than a chore.
- [x] **Non-empty destination = conflict, enforced by US alone** (§3.1 — Athena does *not* enforce it when partitioning). Replay-safety = **`ClientRequestToken`** + that interlock (§5.2).
- [x] **`finalize` verifies against the `UNLOAD` data manifest** (§5.3), not by counting objects in a prefix.
- [x] **The 30-minute DML timeout is an account quota**, not a workgroup setting (§6.2) — a support ticket, and the real ceiling on the feature.
- [x] **Partition layout preserved** via projection + `partitioned_by`, capped at Athena's 100-partition limit.
- [x] **An S3 manifest between states** (§2.2) and a **hashed `MessageGroupId`** (§2.3) — both carried from v2.
- [x] **An explicit IAM `Deny`** on `user_settings/*` and the marker object (§6).

## 9. Alternatives considered

**Lambda + polars (v1/v2 — rejected).** The original design. Killed by the 900-second ceiling at 250 GB (§0). It survived, in miniature, as the Excel path — which is itself now deferred (2026-07-13, §4.3), so nothing in the arc uses it.

**Fargate + polars streaming (rejected).** It would work: up to 16 vCPUs, 120 GB RAM, running for hours, with `scan_csv → sink_parquet` streaming in bounded memory. It would also handle every format — including the now-deferred Excel — with one code path, and preserve the zero-catalog role. Rejected because it means **introducing a VPC to a project that has none** — Fargate's only network mode is `awsvpc`, so every task needs a subnet — plus ECR, a Docker build pipeline in CI, an ECS cluster, two more IAM roles, and a 30–60 second cold start on a workload whose common case is a 40 MB file. All of that to get a *single big box* doing serially what Athena parallelizes. If Athena ever proves insufficient, this is the escape hatch, and the verb contract (S3 in, S3 out) is deliberately shaped so an `ecs:runTask.sync` state could replace a Task state without redesigning the machine.

**Athena CTAS (rejected in favour of `UNLOAD`).** Functionally equivalent for the data, but it also creates a Glue table that would immediately have to be dropped. `UNLOAD` produces the files and nothing else. Same engine, same speed, one less thing to clean up.

**AWS Glue ETL / EMR Serverless (rejected).** Both scale, both are purpose-built, both are far heavier than the problem — a new service family, new IAM, slower starts, higher cost, for a job Athena already does.

## 10. Known limitations and accepted risks

- **The 30-minute DML query timeout is the real ceiling** (§6.2). Until an account quota increase is granted (up to 240 minutes), any conversion that cannot finish in 30 minutes fails. This, not Lambda and not Athena's throughput, is what bounds the feature.
- **Compressed text is not splittable.** A single 250 GB `.csv.gz` would be processed by **one worker** and would certainly exceed the timeout. Sources must be uncompressed, or split across many objects — a `.gz` source over a size threshold is rejected with guidance rather than left to time out after 30 minutes.
- **Heterogeneous CSV headers are rejected, not unioned** (§4.2) — the one capability lost relative to the Lambda design.
- **Output file names are engine-chosen** on the Athena path (§5); no 1:1 source-to-output mapping.
- **A failed conversion leaves partial output for the user to delete** (§2.4). Deliberate: the pipeline holds no delete permission, and the empty-destination rule turns the manual cleanup into a safety interlock against double-writing.
- **Extension/content mismatch is undetected**, shared with Table Builder and the data-quality pipeline.
- **Nested-destination table poisoning** (§3.1) — accepted, warned, cheaply fixable later.
- **Excel (`.xlsx`) is deferred entirely** (user decision 2026-07-13) — a terminal `unsupported_format` in both arcs; §4.3 records the path a revival would need.
- **Cost, honestly.** Athena charges ~$5/TB scanned — roughly **$1.25 per 250 GB conversion**. The workgroup's scan cutoff is **removed** (§6.2), so this pipeline has **no cost guardrail**, and nothing caps how many conversions a user can run. That is the price of the engine choice. Acceptable at current scale (greenfield, no production users); revisit before real users arrive.
- **DLQ + `ExecutionsFailed` alarms are delivered by SPEC-121 FR-003** (`infra/modules/file-converter/alarms.tf`) — this arc closes, for itself, the no-alarm gap the earlier control-plane modules still carry.

## 11. New infrastructure (summary; detail in SPEC-115)

- **`infra/modules/file-converter/`**: FIFO SQS + FIFO DLQ; an EventBridge Pipe (SQS → SFN) + role; a **Standard Step Function** with the **query polling loop** (a single `UNLOAD` path — no format `Choice`; Excel is deferred); **nine** single-task Lambdas (`validate-authorize`, `inspect-source`, `reconcile-schema`, `create-temp-table`, `start-unload`, `check-query`, `finalize`, `drop-temp-table`, `notify-failure` — the last a placeholder SPEC-121 wires) on **one shared execution role** (**LF admin, and NO `s3:DeleteObject`**); an **`fccommon`** layer; a **polars layer attached to `inspect-source` only** (§6.3); a dedicated **Athena workgroup** (`${project_name}-${environment}-file-converter-wg`) with **`bytes_scanned_cutoff_per_query` unset**; CloudWatch log groups (14-day).
- **An Athena DML query-timeout quota increase** (§6.2) — an account-level Service Quota request, not IaC. **Ship-blocking prerequisite.**
- **Portal role**: `sqs:SendMessage` on the file-converter request queue **only**; `VITE_FILE_CONVERTER_QUEUE_URL` — **four** wiring points, one of them a **hand-set GitHub repo variable** (the documented "VITE_* deploy gotcha", `.env.example:61-62`).
- **Lake Formation**: the execution role is added to `aws_lakeformation_data_lake_settings.admins` as a **constructed string in root `locals`**, never a module output — an unknown element inside that `compact()` silently drops the admins change (`analytics/lakeformation.tf:19-22`; expect a first-apply re-run on a from-scratch deploy).
- **Deploy-role IAM** as a **separate customer-managed policy** (the inline-policy 6,144-char budget is exhausted, `base/iam.tf:134-136`), granted in a **PR that applies BEFORE** the module's resources (the deploy-perms-before-resources rule).
- **No new bucket** — output lands in `local.user_space_bucket_name` or `local.shared_space_bucket_name`, both **derived** from `var.project_name` (`infra/main.tf:16,50`) — never hardcode `dat-prod-shared-space`.

## 12. Spec arc

Build order **107 → 115 → 116 → 117 → 118 → 119 → 120 → 121 → 122 (optional, last)**. SPEC-107 is the shared prerequisite; the data-quality arc (108→114) is independent and either may go first; SPEC-122 is additive and droppable.

| Spec | Scope |
|---|---|
| SPEC-107 | **Shared `cpcommon` layer** — prerequisite for both arcs. |
| SPEC-115 | **Foundation infrastructure + layers + the Athena workgroup** — SQS+DLQ → Pipe → SFN skeleton **including the query polling loop** (no format `Choice` — Excel is deferred); nine Lambda stubs (incl. the `notify-failure` placeholder) on one shared role; `fccommon` + the polars layer (**`inspect-source` only**); the dedicated workgroup; deploy-role IAM (two PRs); a smoke test. Plumbing only. |
| SPEC-116 | **Request contract, browser enqueue & `validate-authorize`** — envelope + **hashed `MessageGroupId`**; portal-role grant + `VITE_FILE_CONVERTER_QUEUE_URL`; source authorization; the **destination rules** (same space, blocklist incl. `user_settings/`, empty); the execution role's S3 grants + the **`Deny`**. |
| SPEC-117 | **Source inspection + schema reconciliation** — list; classify; single-format; probe **every** file; **reject heterogeneous CSV headers**; the type-widening rule table → a CAST list; partition detection (100-partition cap); the manifest. |
| SPEC-118 | **The Athena `UNLOAD` path** — `create-temp-table` (external table over the source, projection for partitions); `start-unload` (`ClientRequestToken`); **the SFN `Wait`/`check-query`/`Choice` polling loop**; `drop-temp-table` (Glue-only) on **both** the success and failure paths; the LF-admin + Glue/Athena grants. |
| SPEC-119 | **`finalize` + terminal states** — verify against the **`UNLOAD` data manifest**; the summary payload incl. string fallbacks; `RecordSuccess`/`RecordFailure`. (The Excel path originally scoped here is deferred entirely — user decision 2026-07-13.) |
| SPEC-120 | **File-browser "Convert to Parquet" UI** — the action; an editable destination with the **nested-under-a-table-LOCATION warning**; pending/toast UX. Must satisfy SPEC-095 (responsive + `MobileActionBar`), SPEC-045 (`vitest-axe`), SPEC-106 (`toUserMessage`). |
| SPEC-121 | **Notification producer** — success naming the destination **and any string-fallback columns**; friendly failure reasons; `@notifies_on_failure` everywhere; wires the SPEC-115 `notify-failure` placeholder into the failure path (`ParseError → DropTempTable → NotifyFailure → Fail`); DLQ + `ExecutionsFailed` alarms (`alarms.tf`). Mirrors SPEC-072/094. |
| SPEC-122 | **Optional "create table from the converted files"** (§7.1) — Table Builder gains an **internal FIFO queue** (portal role has no grant) + a second Pipe that **stamps the trust marker**, and a trusted-producer path in its `validate-authorize`; the converter gains an optional `tableBuild` block, an `enqueue-table-build` verb on the **success path only**, and a dialog checkbox reusing Table Builder's **existing** partition-keys editor. **Additive and last** — nothing else in the arc depends on it. |
