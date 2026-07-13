# Architecture Decision: Check Data Quality on Source Files (the "Data Quality" control plane)

**Status:** Proposed — **re-architected 2026-07-11 (v3)** after the 250 GB file-size requirement landed; **corrected to v3.1** after an adversarial review verified every Athena claim against AWS documentation (§0.1). Drives the data-quality spec arc (SPEC-108→114).
**Last Updated:** 2026-07-11
**Related:** `docs/architecture-review-2026-07-11.md` (the review that drove v2; **its "no catalog access" praise is superseded here — see §0**), `docs/file-converter-architecture.md` (the sibling pipeline that *fixes* what this one only reports on — same engine choice, same reasoning), `docs/table-builder-architecture.md` (the control-plane pattern, and the DDL/projection machinery this now reuses), `docs/shared-spaces-architecture.md`, `docs/best-practices/lambdas/lambdas.md`, SPEC-032 (Athena/Glue/Lake Formation foundation — **now a hard dependency**), SPEC-056/057, SPEC-058 (notifications), SPEC-066→072 (table-builder), SPEC-107 (`control-plane-common` layer).

> Read this before writing or implementing any data-quality spec. It records *why* the feature looks the way it does. Implementation detail lives in the arc specs (SPEC-108→114) and the code.

---

## 0. What changed in v3, and why (read this first)

v1 and v2 specified a **Lambda pipeline** streaming each file and computing checks in Python, fanned out by a per-file `Map`. v2 also celebrated that the execution role needed **no Glue, Athena, or Lake Formation grant at all**.

**The real files are up to 250 GB, and that breaks both claims.**

Lambda's hard ceiling is **900 seconds**. A Python pass over 250 GB — decode, tokenize, per-column checks — runs at roughly 10–50 MB/s and would take **hours**. Polars lazy scanning fixes the *memory* problem but not the *time* problem; the bytes still have to move. A full pass in Lambda is impossible at this scale.

Two escapes were considered. **Sampling** (read a bounded window plus ranged samples, label every figure as approximate) would have worked with no new infrastructure — but it gives up exact counts, and **the user chose exactness**. **Fargate** would give a full pass, at the cost of introducing a VPC to a project that has none (§9).

**The chosen answer is Athena** — a distributed engine this project already owns (SPEC-032), which computes exact null ratios, exact duplicate counts, exact row counts, and exact type-consistency over 250 GB in minutes. Better still, the headline check ("this column looks numeric but has stray garbage in it") becomes a `TRY_CAST` that returns null on exactly the values that don't parse — a *cleaner and more exact* implementation than the hand-rolled sampling one.

**The cost, stated plainly:** the execution role now needs **Glue + Athena + Lake Formation admin**, exactly as table-builder's `execute-ddl` role does. The "narrowest control plane in the project" property from v2 is **gone**. That was a real virtue and it is being deliberately surrendered.

**Two checks do not survive the move intact**, because a SQL engine never sees raw bytes — by the time Athena hands you a row, the encoding and the line structure are already gone. **Invalid UTF-8** and **ragged rows** are therefore handled by approximation (§5.3), and this is a deliberate, user-approved trade rather than an oversight.

**Excel is dropped from this arc** (user decision). Athena cannot read `.xlsx` at all. The path is: convert Excel to Parquet with the file converter, then run the quality check against the Parquet.

Structural findings from the v2 review that **still stand**: the hashed `MessageGroupId` (§2.3), the S3-manifest-between-states rule (§2.2), the reserved-prefix protections and the IAM `Deny` (§7), and the segment-level hidden-path rule (SPEC-107).

## 0.1 Corrections in v3.1 — verified against AWS documentation

The v3 draft asserted Athena behaviour from memory, and an adversarial review checked each claim against AWS docs. The corrections below are woven through the sections that follow; they are collected here so they are not reintroduced.

- **There is NO workgroup query-timeout setting.** The DML query timeout is an **account/Region Service Quota** — **30 minutes by default, raisable to 240 only by a quota-increase request** (a support ticket, not Terraform). It is a **deployment prerequisite** and the real ceiling on the feature (§7.2).
- **`bytes_scanned_cutoff_per_query` must be unset.** The existing portal workgroup carries a **10 GiB** scan cutoff as a cost guardrail (`infra/modules/analytics/athena.tf:36`). A 250 GB check is **25× that**, so copying the existing shape would make every real check fail. Removing it is deliberate and removes the project's only cost guardrail (§10).
- **`StartQueryExecution` needs a `ClientRequestToken`** (= `requestId`), or a Step Functions `Retry` after a post-submission transient error starts a **second** query.
- **Temp-table names must be safe identifiers.** v3's `_dq_{requestId}` had a leading underscore (Athena requires backticks) containing a **UUID with hyphens** (which parse as subtraction). Corrected to `dq_tmp_{hex32}` — the request UUID with hyphens stripped.
- **Use the Hive JSON SerDe, not OpenX.** AWS explicitly warns that OpenX "can be non-deterministic… unexpected null values when none are present." The entire JSON story here rests on *"nulls mean the key was missing"*, so the wrong SerDe would poison it silently.
- **Athena needs an explicit column list for Parquet and JSON tables** — it does not auto-detect a Parquet schema. That column list comes from `inspect-source`'s per-file probe, which means **`inspect-source` needs a Parquet reader** (§4). v3 said `dqcommon` carried "no polars"; that made the arc's own Parquet support impossible. Corrected: `inspect-source` carries the polars layer.
- **`byte-scan`'s budget was ~200× too small** (§5.3). v3 bounded the encoding scan *per file* (256 MiB × up to 1000 files ≈ 276 GB through one Lambda). It is now bounded **per request**.
- **The duplicate-row check runs as its own query** (§5.1). A `GROUP BY <every column>` over 250 GB is a full shuffle — the single most expensive operation Athena offers, and a reliable way to exhaust query resources. Isolating it means its failure degrades the report rather than killing the check.
- **Compressed text is not splittable.** A single 250 GB `.csv.gz` is processed by **one worker** and will exceed the timeout. Sources must be uncompressed or split across many objects.

---

## 1. What we're building

From the **file browser**, on a **file or a folder** of data files (personal space or a shared space the user belongs to), a user can press **"Check data quality."** The system reads the data **without changing anything** and produces a **quality report**: whether every column's values are internally consistent (a column that looks numeric with a handful of stray non-numeric values), how many blank/null values each column has, whether rows repeat, whether rows are structurally ragged, whether the content decodes cleanly, and — for a folder of several files — whether every file agrees on the same columns. The user is notified (SPEC-058→060) the moment the check finishes, with a link to the full report.

This is a **diagnostic tool, not a repair tool**. It never rewrites a source file. Its sibling, the **file converter**, is the repair tool.

**Supported inputs (v1): CSV/TXT, JSON/NDJSON, and Parquet.**

- **Parquet is newly supported** in v3 — and it matters, because the natural workflow is *convert, then verify*. A user who converts a messy CSV to Parquet must be able to check the result. In v2, that failed with `unsupported_format`.
- **`.txt` is supported** (classified as CSV), which is a **deliberately larger extension set than Table Builder's** — its `_EXT_FORMAT` (`inspect_source.py:22-28`) has no `.txt`. This is a new decision for the two new pipelines, not inherited behaviour.
- **Excel is not supported** (§0). Convert it first.

Classification is by **extension**, so a content/extension mismatch (a tab-delimited file named `.csv`) is undetected — a known limitation shared by all three pipelines (§10).

## 2. Orchestration — a dedicated SQS → Pipe → Step Function, with the work done by Athena

```
Browser (scoped creds: sqs:SendMessage only, + the ID token in the body)
   │  request: { requestId, actor(idToken), space{kind,bucket,prefix}, location }
   ▼
SQS (FIFO) ──▶ EventBridge Pipe ──▶ Step Function (Standard)
                                      │
                                      ├─ validate-authorize   (ID token → actor; authorize read access; validate the report destination)
                                      ├─ inspect-source       (list; classify by extension; single consistent format; probe every file's header; write a manifest to S3)
                                      ├─ create-temp-tables   (external table over the SOURCE; + for CSV, a single-column RAW-LINE table for ragged detection, §5.3)
                                      ├─ start-profile-query  (one Athena query computing every exact check, §5.1)
                                      │   ┌─ Wait(30s) ──▶ check-query ──┐   ◀── the poll lives in the STATE MACHINE,
                                      │   └──────── Choice(RUNNING) ◀────┘        not inside a Lambda (§2.1)
                                      ├─ byte-scan            (Lambda: a BOUNDED, SAMPLED encoding check — the one thing SQL cannot see, §5.3)
                                      ├─ assemble-report      (join the Athena results + the byte-scan + cross-file agreement → report.json)
                                      └─ drop-temp-tables     (always — reached via Catch on the failure path too)
```

**Decision — a NEW, dedicated pipeline** (not folded into Table Builder, Table Share, or the file converter). A quality check is an unrelated workflow; folding it in would re-broaden that role (`lambdas.md` §1). A dedicated SQS+DLQ → Pipe → Step Function lives in `infra/modules/data-quality/`. It reuses the **pattern**, not the resources — and now also reuses table-builder's **DDL and partition-projection code** rather than reimplementing it.

**Decision — single-task Lambdas** on the shared **`cpcommon`** layer (SPEC-107) plus a **`dqcommon`** domain layer. **No polars, no Excel engine** — every heavy computation is Athena's; the only Lambda that touches bytes is `byte-scan`, and it reads a bounded window.

### 2.1 Decision — the Athena poll lives in the Step Function, not in a Lambda (NEW, and load-bearing)

Table-builder's `execute-ddl` polls Athena **inside** a 300-second Lambda (`table-builder/locals.tf:37`) — fine for a `CREATE TABLE` that returns in seconds. **It would be fatal here.** A profiling query over 250 GB runs for minutes to tens of minutes.

So a short Lambda **starts** the query, and the Step Function does the waiting: `Wait(30s) → check-query → Choice(RUNNING ? loop : done)`. Standard executions run for up to a year, so **the time ceiling disappears entirely.** This is the most important structural difference from every other control plane here, and it is why "just reuse execute-ddl" is not the answer.

**The per-file `Map` from v2 is gone.** Athena does the fan-out internally. There is nothing left to parallelize by hand.

### 2.2 Decision — states pass an S3 manifest pointer, not inline arrays (carried from v2)

Step Functions caps a state payload at **256 KB**. A large folder's file list will exceed it, and `States.DataLimitExceeded` is thrown **outside** any `Catch` — so the user would get **no notification at all**, the worst failure mode in the pipeline. `inspect-source` writes a manifest to S3 and passes its key; every later state passes pointers, never payloads.

### 2.3 Decision — `MessageGroupId` is a HASH of the location (carried from v2)

The queue is FIFO so two checks of the same source serialize. **`MessageGroupId` = the SHA-256 hex digest of the canonical target location** — a fixed 64 characters, **never the raw location**. SQS caps `MessageGroupId` at **128 characters** and S3 keys reach 1024; the existing producers get away with raw ids only because they use bounded catalog identifiers. **`MessageDeduplicationId` = `requestId`.**

## 3. Authorization

The request carries the caller's Cognito **ID token**; `validate-authorize` verifies it offline against the User Pool JWKS and derives the actor from the `cognito:username` claim (`cpcommon.auth`), never from the body.

- **Personal space:** the target location must resolve inside the actor's own prefix.
- **Shared space:** the registry record must have `status == "active"` **and** the actor must be in `members` (`cpcommon.registry.is_active_member`).
  **Note:** "active" is the **space's** provisioning status, *not* SPEC-073's per-member Pending/Active join chip. SPEC-073 is explicit that access is granted at add time, so a **Pending member passes** this check. (v2's phrasing invited the opposite reading.)
- The **report destination** must resolve inside the same space — this pipeline never writes outside the space it read from.

## 4. Source inspection

`inspect-source` lists the location (`cpcommon.s3_listing`, segment-level hidden-path rule per SPEC-107 — so the pipeline's own `_data-quality-reports/` folder is never treated as source data), classifies every object by **extension** (`.csv`/`.txt` → csv, `.json`/`.jsonl`/`.ndjson` → json, `.parquet` → parquet), and fails on a **mixed-format** folder.

It also **probes every file's header/schema** — cheap (a Parquet footer or a bounded head read), and the input to the one genuinely cross-file check (§5.2).

Caps: a **max object count** (default 1000, mirroring `SHARE_MAX_OBJECTS`). There is **no max total size** — that ceiling was a Lambda artefact and no longer exists.

**Partitioned sources** (Hive-style `key=value/` directories) are read via a temp external table with **partition projection**, reusing table-builder's exact machinery (SPEC-069).

## 5. The checks

### 5.1 Exact, computed by Athena, at any scale

One profiling query per request, over the temp external table:

- **Per-column type consistency — the headline check.** `TRY_CAST(col AS BIGINT)` (and `DOUBLE`, `TIMESTAMP`, `DATE`) returns **null on exactly the values that don't parse**. So "this column is 99.97% numeric with 412 stray values" is an exact count, and the offending values can be sampled for the report. This is a *better* implementation than v2's hand-rolled pattern matching, not a compromise.

  **This check is skipped for Parquet sources, and the report says so** (v3.1). Parquet enforces types in the format, so a numeric column *cannot* contain stray text — the check is vacuous there. Parquet checks are still worth running for null ratios, duplicates, row counts and, above all, **cross-file schema drift** (§5.2), which is very much a real Parquet problem.
- **Null / blank ratio per column** — exact.
- **Row counts** — exact, per file (via the `$path` pseudo-column) and in total.
- **JSON key drift** — the **Hive** JSON SerDe (not OpenX — §0.1) yields nulls for missing keys, so "records missing a key most other records have" falls out of the null-ratio computation for free.

- **Duplicate rows — exact, but in a SEPARATE query** (v3.1). `GROUP BY <every column> HAVING COUNT(*) > 1` is a **full shuffle** across the whole dataset: the single most expensive operation Athena offers, and at 250 GB a realistic way to exhaust query resources. v3 asserted this was "a straight upgrade… full stop, and means it" — confidence that was unearned. So it runs as its **own** query, and if it fails on resources the report records `duplicates: not_computed` with the reason **rather than failing the whole check**. Everything else still lands. (It *is* still an upgrade on the Lambda design, which had to sample duplicates to avoid a memory bomb — just not an unconditional one.)

**The query has a size limit.** Athena caps a query string at **262,144 bytes**. Four `TRY_CAST`s plus a null-ratio and a sample aggregate per column approaches that on a very wide table, so a `DQ_MAX_COLUMNS` cap (default 200) rejects pathological sources with a clear message rather than emitting an unparseable query.

**The source is scanned more than once** — once for the profile query, once for the raw-line ragged check (§5.3), once for duplicates. The cost estimate in §10 accounts for this; v3's did not.

### 5.2 Cross-file column agreement

Whether every file in the folder presents the same columns. Computed in `assemble-report` as a cheap reduce over the per-file schemas from `inspect-source` (§4) — not in SQL, because an Athena external table has one schema for the whole folder and would *hide* exactly this disagreement. This is the check most likely to explain why a Table Builder table came out wrong, and why it must be computed from the probe rather than the query.

### 5.3 Approximate — the two checks SQL cannot see (user-approved trade)

A SQL engine never sees raw bytes. By the time Athena hands you a row, the encoding and the line structure are gone. So:

- **Ragged rows** (a row whose field count doesn't match the header) are detected with a **second external table over the same folder, with a single column** — LazySimpleSerDe with a one-byte field delimiter that cannot occur in the data (`\001`), so each physical line is one raw string. Then `cardinality(split(line, ',')) <> {headerColumns}` counts them at full scale. **Two caveats the report must state:** quoted delimiters confuse `split` (a CSV with commas inside quotes over-reports), **and so do embedded newlines inside quoted fields** (v3 listed only the first). The figure is labelled *approximate* for both reasons. It is still enormously more useful than not having it. Note Athena's **200 MB limit on a single text line** — a pathological file exceeding it fails the raw-line table, and that degrades the ragged check rather than the whole request.
- **Invalid UTF-8** is checked by **`byte-scan`**, a small Lambda reading a bounded window plus ranged samples.

  **v3.1 — the budget was ~200× too small, and this is the correction.** v3 bounded the scan *per file*: a 256 MiB window plus samples, across up to 1000 files, is roughly **276 GB pulled through a single 1024 MB Lambda in 300 seconds** — about 920 MB/s sustained, against a real-world ~60–100 MB/s. It would have timed out in production while passing on a three-file test fixture. That is the *exact* error class this whole re-architecture exists to eliminate, reproduced in the one Lambda that survived it.

  So the scan is bounded **per request**, not per file: a **total byte budget** (`DQ_SCAN_TOTAL_BYTES`, default 2 GiB) is divided across the files in the manifest, and every encoding figure is **explicitly labelled as sampled with its coverage percentage**. A number that silently means "of the first 0.8%" is worse than no number.

Everything else in the report is exact. The report distinguishes the two classes; the notification says so too.

## 6. The report

`assemble-report` writes `{space}/_data-quality-reports/{requestId}/report.json`: the source location, format, file count, the exact findings (§5.1), the cross-file agreement (§5.2), the approximate findings clearly marked (§5.3), a short human-readable top-issues list, and an overall verdict (**clean** or **issues found**). The key is a **pure function of `requestId`**, so a retry overwrites it byte-identically — which is how this pipeline is replay-safe, since no verb in this codebase does request-id idempotency checking.

### 6.1 The runs index — how a report is found later (SPEC-123)

Alongside the per-run report, each successful check appends a small entry to a **per-space `{space}/_data-quality-reports/index.json`**: the location, verdict, file count, timestamp, and whether anything was sampled. Nothing else — the findings stay in the report.

**Why an index exists at all.** Without it, a "past checks" list would have to list the reports prefix and **GET every report to build a row** — and S3 lists **lexicographically by key**, so ordering by `requestId` (a UUID) gives **no chronology at all**. The list would be both slow and randomly ordered, and it would get slower the more the feature is used. The index makes the dashboard **one GET**.

**The write races, and the fix is precedented.** Checks of *different* locations run in parallel (the queue's `MessageGroupId` is the hashed location, so only same-location checks serialize), so two `assemble-report` invocations can append at once and one would **silently lose the other's run**. This is the same lost-update race SPEC-082 fixed in the shared-space registry, and it takes the same fix: **optimistic ETag compare-and-swap with retry**.

**The index is a convenience, never a dependency.** If the CAS retries are exhausted, the failure is logged and swallowed: the report is still written and the notification still fires, and the run is merely missing from the dashboard. The report is the artefact.

**The report must be findable.** The report is the arc's only durable artefact, so:

1. **The folder is hidden in the file browser** (`_data-quality-reports` added to `HIDDEN_BROWSER_FOLDERS`). The `_`-prefix convention is a **Lambda-side convention only** — the SPA has no such filter (`fileBrowser.service.ts:81-99`; `protectedFolders.ts:11` hides only `user_settings`), so without this the user would see, move and delete their own reports.
2. **The notification deep-links to an in-app report view** (SPEC-113). Hiding the folder without providing a viewer would produce a file the user is told about and cannot open — six specs of infrastructure delivering nothing. The viewer is read-only and renders the JSON; it is **in scope**, not a follow-up.
3. **A `/data-quality` dashboard lists past runs** (SPEC-123), reachable from the primary nav. Without it, a report is reachable **only** from its notification — so dismissing the notification effectively loses the report. The dashboard reads the §6.1 index, aggregates across the user's personal space and their shared spaces, and drills into the SPEC-113 view.

## 7. Execution role — one shared role, now with catalog access

The Step Function and all verb Lambdas **share ONE execution role**.

**It needs Glue, Athena, and Lake Formation admin.** Target databases are dynamic (per user, per shared space), so they cannot be statically LF-granted — the same reasoning that made table-builder's `execute-ddl` role an LF admin (SPEC-070). The role needs Glue create/get/delete table (for the temp tables), Athena `StartQueryExecution`/`GetQueryExecution`, `lakeformation:GetDataAccess`, and the Athena results location.

**S3 grants, and the `Deny` that makes them safe:**

- `s3:GetObject` + `s3:ListBucket` on the source; `s3:PutObject` **and `s3:GetObject`** on the report prefix (`assemble-report` must *read* the intermediate results it wrote — v2 granted write only, which would have failed at the last verb).
- Read/write on the **Athena results prefix**, including `s3:AbortMultipartUpload`, `s3:ListBucketMultipartUploads` and `s3:GetBucketLocation` — Athena needs these to write query output at all at this scale.
- **`s3:DeleteObject` is granted NOWHERE.** `drop-temp-tables` touches **Glue only**, which is what makes it safe to reach from any failure path — including a validator failure — because the worst it can do is drop a table the pipeline itself created. (The sibling file-converter arc had to *remove* a delete grant for exactly this reason; see `file-converter-architecture.md` §2.4. This arc never needed one.)
- An explicit **`Deny s3:PutObject` on `*/user_settings/*` and `*/DO_NOT_DELETE.txt`** in both buckets.

**Why that `Deny` is not optional.** The user-space policy denies `s3:DeleteObject` on `user_settings/*` but leaves **`s3:PutObject` wide open** (`analytics/policies/portal-role-analytics.json.tftpl:67-72`). Any role that can write in a user's space can overwrite `user_settings/notifications.json` — **destroying the notification inbox permanently, with no way for the user to recover, because deleting the corrupt file is itself IAM-denied.** The `Deny` is what makes the guarantee; destination validation is defence in depth. (Shape to copy: `table-share/policies/execution.json.tftpl:59-68`.)

### 7.2 The Athena workgroup — and the account quota that is the real ceiling (v3.1)

v3 said "a dedicated workgroup with its query timeout set to the maximum permitted." **No such setting exists.** Corrected:

- **The query timeout is an account/Region Service Quota**, not a workgroup property: **30 minutes by default**, raisable to **240 minutes** only via a quota-increase request. That is a **support ticket, not Terraform**, it is a **ship-blocking prerequisite** for this arc, and it — not Athena's throughput — is the real ceiling on the feature.
- **`bytes_scanned_cutoff_per_query` must be unset (null).** The existing portal workgroup carries a **10 GiB** cutoff (`infra/modules/analytics/athena.tf:36`); a 250 GB check is 25× that, so copying the existing module's shape would make every real check fail with "bytes scanned limit exceeded."
- **Result location is set per query**, not on the workgroup — `ResultConfiguration.OutputLocation` on each `StartQueryExecution`, with `enforce_workgroup_configuration = false`, exactly as the existing portal workgroup already does (`infra/modules/analytics/athena.tf:24-27`). A workgroup has only **one static** result location, so per-space routing is impossible any other way.
- A query exceeding the quota is a terminal `query_timeout` telling the user the source is too large — not a silent hang.

### 7.3 `inspect-source` carries the polars layer (v3.1 correction)

v3 said `dqcommon` declares "no polars, no Excel engine." But **Athena requires an explicit column list for Parquet and JSON external tables** — it does not auto-detect a Parquet schema — and that list comes from `inspect-source`'s per-file probe. Reading a Parquet footer needs a Parquet reader. With no polars, the arc's own newly-added Parquet support was impossible.

So **`inspect-source` carries the polars layer** (no Excel engine — this arc doesn't support Excel). Every other verb stays metadata-weight. SPEC-107's combined per-function size guard must pass for `inspect-source`.

## 8. Async UX + notifications

The browser never blocks; after enqueueing it shows a transient "checking data quality…" toast. The durable outcome reuses the SPEC-058 trusted-producer `create` contract: **one notification to the actor** (one recipient, like Table Builder — not Table Share's fan-out) with the verdict, the top issues, and a **link to the report view**; or a friendly failure reason.

**When any figure is approximate or sampled, the notification says so.** An unqualified "clean" over a sampled encoding check would be a lie.

Failure text is **friendly, never raw Athena/AWS text** — `cpcommon.messages` (SPEC-106), raw detail confined to CloudWatch and the SFN execution history. Emission is best-effort; `@notifies_on_failure` ensures an unexpected crash still reaches the user. Terminal `RecordSuccess`/`RecordFailure` are `Pass` → `Succeed`/`Fail`; **nothing durable is written by a terminal state** — the report object is the artefact.

## 9. Alternatives considered

**Lambda + streaming Python (v1/v2 — rejected).** Killed by the 900-second ceiling: hours for 250 GB (§0).

**Lambda + rigorous sampling (rejected — user decision).** Would have worked at any size with **no new infrastructure and no catalog access**, keeping the narrow blast radius v2 prized. Rejected because it gives up exact counts, and exactness was chosen. Recorded because it remains the cheapest fallback if the catalog dependency ever becomes a problem.

**Fargate + polars streaming (rejected).** A full byte-level pass at any scale, keeping the zero-catalog role and handling Excel too. Rejected because Fargate's only network mode is `awsvpc` — every task needs a subnet — so it means **introducing a VPC to a project that has none**, plus ECR, a Docker pipeline, and an ECS cluster, to get a *single big box* doing serially what Athena parallelizes. If Athena ever proves insufficient, this is the escape hatch, and the verb contract (S3 in, S3 out) is deliberately shaped so an `ecs:runTask.sync` state could replace a Task state.

## 10. Known limitations and accepted risks

- **The 30-minute DML query timeout is the real ceiling** (§7.2). Until an account quota increase is granted (up to 240 minutes), a check that cannot finish in 30 minutes fails.
- **Compressed text is not splittable.** A single 250 GB `.csv.gz` is processed by one worker and will exceed the timeout. Sources must be uncompressed or split across many objects; a `.gz` source over a size threshold is rejected with guidance rather than left to time out.
- **Two checks are approximate** (§5.3): ragged-row counts over-report when delimiters **or newlines** appear inside quotes; encoding checks are sampled, with the coverage percentage stated. Everything else is exact.
- **Duplicate counting can fail on resources at extreme scale** (§5.1) and degrades to `not_computed` rather than failing the check.
- **Type-consistency checks are skipped for Parquet** (§5.1) — the format enforces types, so the check is vacuous. Parquet checks still cover nulls, duplicates, row counts and cross-file schema drift.
- **No Excel** (§0). Convert first, then check the Parquet.
- **Extension/content mismatch is undetected**, shared with Table Builder and the file converter.
- **The role is now an LF admin** (§7) — the blast radius is comparable to Table Builder's. This is the deliberate cost of exactness at 250 GB.
- **Cost, honestly.** Athena charges ~$5/TB scanned, and this pipeline **scans the source more than once** (profile query, raw-line ragged check, duplicates) — so a 250 GB check is roughly **$2.50–$3.75**, not the $1.25 a single scan would suggest. The workgroup's scan cutoff is **removed** (§7.2), so there is **no cost guardrail**, and nothing caps how many checks a user can run. Revisit before real users arrive.
- **Report retention.** Reports are ordinary files in the user's space and count toward their storage. No lifecycle/TTL policy in v1.
- **The DLQ has no consumer or alarm** — a pre-existing gap across every control-plane module, inherited not introduced.

## 11. New infrastructure (summary; detail in SPEC-108)

- **`infra/modules/data-quality/`**: FIFO SQS + FIFO DLQ; an EventBridge Pipe (SQS → SFN) + role; a **Standard Step Function** with the **query polling loop** and a `Catch` that always reaches `drop-temp-tables` (safe on every path — it touches **Glue only**); single-task Lambdas (`validate-authorize`, `inspect-source`, `create-temp-tables`, `start-profile-query`, `check-query`, `byte-scan`, `assemble-report`, `drop-temp-tables`) on **one shared execution role** (**LF admin, and NO `s3:DeleteObject`**); a **`dqcommon`** layer; a **polars layer attached to `inspect-source`** (§7.3 — needed to read Parquet footers; no Excel engine); a dedicated **Athena workgroup** with **`bytes_scanned_cutoff_per_query` unset**; CloudWatch log groups (14-day).
- **An Athena DML query-timeout quota increase** (§7.2) — an account-level Service Quota request, not IaC. **Ship-blocking prerequisite.**
- **Portal role**: `sqs:SendMessage` on the data-quality request queue **only**; `VITE_DATA_QUALITY_QUEUE_URL` — **four** wiring points, one a **hand-set GitHub repo variable** (the "VITE_* deploy gotcha").
- **Lake Formation**: the execution role added to `aws_lakeformation_data_lake_settings.admins` as a **constructed string in root `locals`**, never a module output — an unknown element inside that `compact()` silently drops the admins change (`analytics/lakeformation.tf:19-22`; expect a first-apply re-run from scratch).
- **Deploy-role IAM** as a **separate customer-managed policy** (the inline budget is exhausted, `base/iam.tf:134-136`), granted in a **PR that applies BEFORE** the module's resources.

## 12. Spec arc

Build order **107 → 108 → 109 → 110 → 111 → 112 → 113 → 114**. SPEC-107 is the shared prerequisite; the file-converter arc (115→121) is independent and either may go first.

| Spec | Scope |
|---|---|
| SPEC-107 | **Shared `cpcommon` layer** — prerequisite for both arcs. |
| SPEC-108 | **Foundation infrastructure + `dqcommon` layer + the Athena workgroup** — SQS+DLQ → Pipe → SFN skeleton **including the query polling loop and the always-cleanup `Catch`**; Lambda stubs on one shared role; deploy-role IAM (two PRs); a smoke test. Plumbing only. |
| SPEC-109 | **Request contract, browser enqueue & `validate-authorize`** — envelope (incl. `requestId`) + **hashed `MessageGroupId`**; portal-role grant + `VITE_DATA_QUALITY_QUEUE_URL`; personal/shared authorization; the execution role's S3 grants (**read *and* write on the report prefix**) + the **`Deny`**. |
| SPEC-110 | **Source inspection** — list; classify by extension (**incl. `.parquet`**); single consistent format; probe every file's header; object-count cap; partition detection; the manifest. |
| SPEC-111 | **Temp tables + the Athena profile query** — `create-temp-tables` (typed external table + the raw-line table for ragged detection); `start-profile-query` (the exact checks, §5.1); the **SFN `Wait`/`check-query`/`Choice` polling loop**; `drop-temp-tables` on **both** paths; the LF-admin + Glue/Athena grants. |
| SPEC-112 | **`byte-scan` + report assembly** — the bounded, sampled encoding check (labelled); cross-file column agreement from the probe; the report write (deterministic key); the summary payload. |
| SPEC-113 | **File-browser UI + the report view** — the "Check data quality" action; hide `_data-quality-reports`; a **read-only report view the notification deep-links to**. Must satisfy SPEC-095 (responsive + `MobileActionBar`), SPEC-045 (`vitest-axe`), SPEC-106 (`toUserMessage`). |
| SPEC-114 | **Notification producer** — verdict + top issues + a link to the report; **says so when any figure is sampled or approximate**; friendly failure reasons; `@notifies_on_failure` everywhere. Mirrors SPEC-072/094. |
| SPEC-123 | **Runs dashboard** (§6.1) — the per-space `index.json` written under **ETag CAS** by `assemble-report`; a `/data-quality` list page (aggregated across spaces, newest first, 10/page, verdict + sampled chips) and a **primary nav entry**. Closes the gap where a report was reachable *only* from its notification. |
