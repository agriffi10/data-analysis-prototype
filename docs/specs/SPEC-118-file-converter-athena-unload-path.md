# Spec: File Converter — The Athena `UNLOAD` Path

**ID:** SPEC-118
**Status:** Draft
**Last Updated:** 2026-07-13
**Depends On:** SPEC-107 (`cpcommon`), SPEC-115 (foundation, incl. the polling loop + the workgroup env vars), SPEC-116 (authorization + S3 grants), SPEC-117 (the manifest + target schema), SPEC-032 (Athena/Glue/LF), SPEC-069/070 (table-builder's DDL + projection machinery, reused here)

> **Read `docs/file-converter-architecture.md` §0, §2.1, §5 and §6 first.** This is the spec that makes 250 GB possible, and the spec that spends the arc's IAM budget.

## Overview

The conversion path — CSV and JSON, the only formats in scope (Excel is deferred entirely, SPEC-115). **`create-temp-table`** builds a throwaway Glue external table over the source. **`start-unload`** runs an Athena `UNLOAD` that writes typed Parquet straight into the user's destination. **`check-query`** reports status while the **Step Function** does the waiting. **`drop-temp-table`** drops the table — **and nothing else.**

Five decisions, each preventing a specific disaster:

**`UNLOAD`, not `CTAS`.** Both write real Parquet objects to a prefix you choose. The difference is that `CTAS` **also registers a table in the Glue catalog**, which would immediately have to be dropped. The deliverable here is *files*, not a table, so `UNLOAD` is the primitive that matches the requirement and removes an entire cleanup step.

**The poll lives in the state machine.** Table-builder's `execute-ddl` polls Athena inside a 300-second Lambda (`infra/modules/table-builder/locals.tf:37`) — fine for a `CREATE TABLE`, **fatal** for an `UNLOAD` of 250 GB. No Lambda can hold a poll open past 900 seconds. The Step Function loops instead; Standard executions run for up to a year.

**`drop-temp-table` touches GLUE ONLY, and partial output is NOT removed.** An earlier draft had this state delete "partial output from the destination," and SPEC-116 granted a delete "scoped to the destination" to make it possible. **Both were wrong.** The scope is not expressible in IAM (the destination is body-supplied text, so the resource can only be `{bucket}/*`), and the `Catch` reaches this state from **every** state including `ValidateAuthorize` — so a validator failure would have deleted an **unvalidated, body-supplied path**, on a queue every portal user can write to. That is an authenticated **cross-user file-delete primitive** (`file-converter-architecture.md` §2.4). The capability is removed rather than re-scoped: partial `UNLOAD` output **stays**, SPEC-121's notification tells the user it may remain and **names the path**, and SPEC-116's empty-destination rule is the **interlock** that blocks a retry until they clear it — which is what makes it impossible to re-run into a half-populated destination and silently double the data.

**Query submission is idempotent (`ClientRequestToken`).** Without it, a Step Functions `Retry` after a transient error that arrived *post-submission* starts a **second `UNLOAD` into the same destination**. Because Athena does **not** enforce the empty-destination rule on the partitioned path (FR-002), **both would succeed** and the destination would **silently double-count every row** — wrong numbers, no error, no notification.

**The role becomes a Lake Formation admin.** Target databases are dynamic (per user, per shared space) so they cannot be statically LF-granted — the same reasoning that made table-builder's `execute-ddl` role an LF admin (SPEC-070). This is the largest privilege in the arc, and the architecture doc records that the earlier design's "zero catalog access" property is deliberately surrendered here.

## Scope

### In Scope

- **`create-temp-table`**: a Glue external table over the **source**, CSV via OpenCSVSerde (all-string, header skipped), JSON via the **Hive** JSON SerDe, partitions declared with **projection** (reusing table-builder's machinery).
- **`start-unload`**: `UNLOAD (SELECT <CASTs from the target schema> FROM <temp table>) TO '{destination}' WITH (format = 'PARQUET' [, partitioned_by = …])`, with an idempotent **`ClientRequestToken`**.
- **`check-query`** + the SFN `Wait`/`Choice` polling loop.
- **`drop-temp-table`**: drop the temp Glue table. **Glue only — it deletes no S3 object, on any path.**
- The execution role's **Glue + Athena + Lake Formation admin** grants and the LF-admins wiring.
- Terminal reasons: `query_failed`, `query_timeout`.

### Out of Scope

- `finalize`, the summary payload, and the terminal states — SPEC-119.
- Excel (`.xlsx`) — deferred entirely (user decision 2026-07-13); `.xlsx` never reaches this spec, being a terminal `unsupported_format` at inspection (SPEC-117 FR-001).
- Notifications — SPEC-121. UI — SPEC-120.
- Any **permanent** Glue table. Every table this spec creates is temporary and dropped; `UNLOAD` creates none at all.
- Deterministic output file names. Athena chooses them — see FR-003.

---

## Functional Requirements

### FR-001: `create-temp-table`

#### Acceptance Criteria:

- [ ] A Glue external table is created over the **source** location, in the actor's own database (personal) or the shared space's database (shared), named **`fc_tmp_{hex32}`** — where `{hex32}` is the request UUID **with its hyphens stripped**.
- [ ] A comment records why the name is shaped that way, because the obvious name **does not run**: a **leading underscore** forces Athena to require backticks around the identifier, and a raw **UUID's hyphens parse as subtraction**, so `_fc_{requestId}` is not a valid identifier — the DDL fails at query time. `fc_tmp_` + 32 hex characters needs no quoting, is unambiguously temporary, and is still a pure function of `requestId`. A test asserts the generated name matches `^fc_tmp_[0-9a-f]{32}$`.
- [ ] **The column list is explicit and comes from SPEC-117's per-file probes** (their reconciled union, in the target schema's deterministic order). A comment records why: **Athena does not auto-detect a schema** for a JSON or Parquet external table — every column must be named — which is why `inspect-source` carries a reader at all (SPEC-115 FR-003 / SPEC-117 FR-003).
- [ ] **CSV** uses **OpenCSVSerde with all-string columns** and `skip.header.line.count = 1`, matching table-builder's shipped behaviour. A comment records why all-string is right here: it is what makes the target schema's `CAST` list (SPEC-117) the single place types are decided.
- [ ] **JSON uses the Hive JSON SerDe — `org.apache.hive.hcatalog.data.JsonSerDe` — and NOT the OpenX SerDe** (`org.openx.data.jsonserde.JsonSerDe`). It matches by **key name** and yields nulls for missing keys, which is the reason SPEC-117 FR-004 exempts JSON from the header-consistency gate. A comment records why the SerDe choice is load-bearing: AWS documents that OpenX **"can be non-deterministic"** and can produce **"unexpected null values when none are present"** — and this pipeline's JSON story rests entirely on *"a null means the key was missing."* A SerDe that invents nulls would write those invented nulls into the user's Parquet, permanently, with no error.
- [ ] **Partitioned sources** (from SPEC-117's `partitionKeys`) declare partition columns with **Athena partition projection**, reusing table-builder's machinery (SPEC-069). No `MSCK REPAIR` anywhere.
- [ ] **The DDL runs via Athena `StartQueryExecution` in the dedicated workgroup** (`FC_ATHENA_WORKGROUP`, SPEC-115 FR-003) **with a short in-Lambda poll to completion.** A comment records the explicit carve-out: an in-Lambda poll is acceptable **here and only here** because DDL returns in seconds — mirroring table-builder's `execute-ddl` precedent — while the state-machine polling loop exists for the `UNLOAD`, whose runtime no Lambda can hold. Do not "fix" this into the SFN loop, and do not use it as licence to poll the `UNLOAD` in-Lambda.
- [ ] Creation uses `CREATE EXTERNAL TABLE IF NOT EXISTS`, so a retry is a no-op (the natural idempotence table-builder relies on, `lambdas/table-builder-execute-ddl/execute_ddl.py:46`).
- [ ] The table name and database are written into the state so `drop-temp-table` can find them **even if a later verb never ran**.

### FR-002: `start-unload`

#### Acceptance Criteria:

- [ ] The statement is **`UNLOAD`**, not `CTAS`. A comment records why: `CTAS` would also register a Glue table that must then be dropped; `UNLOAD` writes the files and nothing else, and files are the deliverable.
- [ ] The `SELECT` applies the **`CAST` list from SPEC-117's target schema** — one cast per column, to the reconciled type. String-fallback columns are cast to `VARCHAR`.
- [ ] **`StartQueryExecution` passes `ClientRequestToken` = the `requestId`.** A comment records the disaster this prevents, spelled out: without it, a Step Functions `Retry` after a transient error that arrived **post-submission** starts a **second `UNLOAD` into the same destination**; because Athena does **not** enforce the empty-destination rule on the partitioned path (below), **both succeed**, and the destination **silently double-counts every row** — wrong numbers, no error, no notification, discovered by a human noticing revenue doubled. With the token, the retry re-attaches to the *same* query execution. A test asserts a retried submission returns the original `QueryExecutionId` and does not start a second query.
- [ ] The token is the **36-character request UUID**, which sits inside Athena's documented **32–128 character** bound for `ClientRequestToken`. A test asserts the token length is within the bound.
- [ ] **The `UNLOAD` statement builder is byte-deterministic for a given target schema** — guaranteed by SPEC-117 FR-005's deterministic column order — so an idempotent retry submits an identical statement. A retry whose parameters *have* changed (same token, different statement) raises Athena's idempotency error, which is a terminal `query_failed`. A test pins both.
- [ ] Output format is `PARQUET`, written **directly to the request's destination**.
- [ ] When the source is partitioned, `partitioned_by` reproduces the partition columns, so `key=value/` segments appear at the same relative position in the output — ready for Table Builder's partition-declaration modal.
- [ ] **The partition columns must come LAST in the `SELECT` list** of an `UNLOAD` with `partitioned_by`. This is not a style preference — the statement **fails** otherwise. The statement builder enforces the ordering and a test asserts it.
- [ ] **`UNLOAD` does NOT require an empty destination when `partitioned_by` is used** — AWS documents the emptiness requirement *"except when writing to partitions"*, and the partitioned path is precisely the one this pipeline uses for partitioned sources. **SPEC-116 FR-005's pre-check is therefore the ONLY guard**, and this spec must not assume the engine will back it up. A comment records that an earlier draft claimed the rule was "enforced twice — once by us, once by the engine," and that the second enforcement **does not exist**. There is consequently **no `destination_not_empty` terminal raised from this verb**; the reason belongs to `validate-authorize` alone.
- [ ] The query runs in the **dedicated workgroup** from SPEC-115 FR-003 (**no `bytes_scanned_cutoff_per_query`**), with its result location supplied **per query** via `ResultConfiguration.OutputLocation` — the workgroup cannot route it, having only one static location. The results location is also where Athena writes the `UNLOAD` **data manifest** that SPEC-119's `finalize` reads.

### FR-003: Output naming — engine-chosen, and why that's accepted

#### Acceptance Criteria:

- [ ] The spec **does not** attempt to control output file names. Athena decides how many files to write and names them itself.
- [ ] A comment records that this is a **deliberate loss** relative to the earlier Lambda design's 1:1 `part-0.csv → part-0.parquet` mapping, and why it's acceptable: at 250 GB you *want* the engine splitting output into sensibly-sized files rather than emitting one enormous Parquet blob.
- [ ] Because output keys are therefore **not** deterministic, replay-safety comes from **`ClientRequestToken` (FR-002) + the empty-destination interlock (SPEC-116 FR-005)** — *not* from key determinism, and **not** from cleanup-on-failure, which no longer exists (FR-004). A comment states this explicitly. It is also why `finalize` verifies against the `UNLOAD` **data manifest**, never by predicting names (SPEC-119 FR-001).

### FR-004: `check-query`, the polling loop, and `drop-temp-table` (Glue only)

#### Acceptance Criteria:

- [ ] `check-query` calls `GetQueryExecution` and returns `{ status, dataManifestLocation?, reason? }` — nothing else. It does **not** wait, sleep, or loop.
- [ ] On `SUCCEEDED` it returns **`Statistics.DataManifestLocation`** — the `UNLOAD` **data manifest**, which lists every object the query wrote and which SPEC-119's `finalize` verifies against (SPEC-119 FR-001). A comment records that this manifest lives in the **query-results** location, **not** the output location, so `finalize` cannot find it by looking under the destination.
- [ ] The Step Function drives the loop: `StartUnload → WaitForQuery (Wait, 30 s) → CheckQuery → Choice`, looping while `QUEUED`/`RUNNING`.
- [ ] A comment records why the poll is not inside the Lambda: an in-Lambda poll cannot survive a query longer than the 900-second ceiling, and a 250 GB `UNLOAD` routinely will.
- [ ] `FAILED`/`CANCELLED` is a terminal `query_failed` whose friendly message carries **no raw Athena `StateChangeReason`** — that text stays in CloudWatch and the SFN execution history (SPEC-106 FR-008).
- [ ] A query killed by the **account-level DML query-timeout Service Quota** (30 minutes by default; SPEC-115 FR-003) is a terminal **`query_timeout`** telling the user the source is too large — not a silent hang. A comment records that this timeout is an **account/Region quota, not a workgroup setting**: there is no field to raise, only a support request (240 minutes maximum).
- [ ] **The `query_timeout`-vs-`query_failed` distinction has a named mechanism:** `check-query` inspects `GetQueryExecution`'s **`Status.AthenaError`** (`ErrorCategory`/`ErrorType`) to recognise the quota kill, with a **`StateChangeReason` pattern match as the fallback**; anything unrecognised stays `query_failed`. A test pins the mechanism with a timeout-shaped and a failure-shaped response — without it the criterion silently degrades to everything-is-`query_failed`.
- [ ] **`drop-temp-table` drops the temp Glue table** and is **idempotent** (dropping a table that never existed is a success). It must tolerate being reached before `create-temp-table` ran.
- [ ] **`drop-temp-table` deletes NO S3 object — not partial output, not scratch, nothing. The pipeline holds `s3:DeleteObject` nowhere** (SPEC-116 FR-006). A comment records the vulnerability that removing the delete closed: the `Catch` reaches this state from **every** state including `ValidateAuthorize`, so a destructive cleanup would have run against a **body-supplied, never-validated `destination`** — and every portal user can enqueue. Garbage token + another user's path ⇒ validation fails ⇒ cleanup fires ⇒ **their files are deleted.** The scope could not be fixed in IAM (the resource can only be `{bucket}/*`), so the capability was removed instead.
- [ ] **Partial output after a failed `UNLOAD` is left in place**, and that is the accepted trade. SPEC-121's notification **tells the user partial files may remain and names the path**; SPEC-116 FR-005's empty-destination rule then **blocks a retry until they clear it**. A comment records that this turns the manual cleanup into a **safety interlock**: it is impossible to retry into a half-populated destination and silently double the data — which matters more here than convenience, because Athena does **not** enforce the empty-destination rule on the partitioned path (FR-002).
- [ ] A test forces a mid-`UNLOAD` failure and asserts (a) the temp Glue table is gone and (b) **the pipeline made no `DeleteObject` call** — the destination's partial objects are still present, and the failure notification names the path.
- [ ] A failure *inside* `drop-temp-table` is logged and does not mask the original failure reason the user is notified about.

### FR-005: The execution role — Glue, Athena, and Lake Formation admin

#### Acceptance Criteria:

- [ ] The role gains Glue `CreateTable` / `GetTable` / `DeleteTable` / `GetDatabase`, Athena `StartQueryExecution` / `GetQueryExecution` / `GetWorkGroup` **scoped to the dedicated workgroup** (SPEC-115 FR-003), and `lakeformation:GetDataAccess`.
- [ ] Those Athena grants cover **both** query kinds this spec submits — `create-temp-table`'s in-Lambda-polled DDL (FR-001) and the `UNLOAD` (FR-002) — and the Glue-side effect of the DDL arrives via the **LF-admin execution role** (below), not via extra statically-granted databases. A comment reconciles the two so nobody adds a per-database grant "to make the DDL work."
- [ ] `lambda.tf` wires **`FC_ATHENA_WORKGROUP`** and **`FC_ATHENA_RESULTS_PREFIX`** (SPEC-115 FR-003) onto the querying functions; `fccommon.config` validates them at import.
- [ ] The role is added to `aws_lakeformation_data_lake_settings.admins`, with a comment recording why: target databases are **dynamic** (per user, per shared space) and cannot be statically LF-granted — the same reasoning as SPEC-070.
- [ ] The admins entry is a **constructed string in root `locals`**, never a module output. A comment records the trap: an unknown element inside that `compact()` **silently drops the admins change** (`infra/modules/analytics/lakeformation.tf:19-22`), and a from-scratch first apply may need one re-run (`lakeformation.tf:26-30`).
- [ ] The role gains read/write on the **Athena results prefix** in both buckets, **including `s3:AbortMultipartUpload`, `s3:ListBucketMultipartUploads` and `s3:GetBucketLocation`** (SPEC-116 FR-006) — a 250 GB `UNLOAD` is certainly multipart, and Athena cannot write its output or its data manifest without them.
- [ ] **`s3:DeleteObject` remains granted NOWHERE** (SPEC-116 FR-006), and the `Deny` on `*/user_settings/*` and `*/DO_NOT_DELETE.txt` remains in force. A plan assertion confirms the rendered policy contains **no `s3:DeleteObject` action at all** — this spec must not reintroduce one to "clean up after itself."
- [ ] A comment on the policy template records that this spec deliberately surrenders the earlier design's "zero catalog access" property, so the next reader knows it was a decision and not drift.

---

## Data Model

```sql
-- create-temp-table (CSV, partitioned)
-- Safe identifier: NO leading underscore (Athena would demand backticks) and NO UUID hyphens
-- (they parse as subtraction). {hex32} = the requestId with hyphens stripped.
CREATE EXTERNAL TABLE IF NOT EXISTS alice.fc_tmp_7f3ac1904e2b4d5f8a6c0e1d2b3a4c59 (
  id string, amount string, note string          -- all-string; types are decided by the CAST list
)
PARTITIONED BY (region string)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
LOCATION 's3://…/alice/sales/'
TBLPROPERTIES ('skip.header.line.count' = '1', 'projection.enabled' = 'true', …);

-- JSON sources use the HIVE serde — NOT OpenX, which can invent nulls where none exist:
--   ROW FORMAT SERDE 'org.apache.hive.hcatalog.data.JsonSerDe'

-- start-unload  (ClientRequestToken = requestId — without it a Retry starts a SECOND UNLOAD
--                and, on the partitioned path, both succeed and the rows are doubled)
UNLOAD (
  SELECT CAST(id AS BIGINT)     AS id,
         CAST(amount AS DOUBLE) AS amount,
         CAST(note AS VARCHAR)  AS note,          -- string fallback (SPEC-117 FR-005)
         region                                   -- PARTITION COLUMNS MUST COME LAST
  FROM alice.fc_tmp_7f3ac1904e2b4d5f8a6c0e1d2b3a4c59
)
TO 's3://…/alice/sales_parquet/'
WITH (format = 'PARQUET', partitioned_by = ARRAY['region']);
```

```jsonc
// The SFN state after CheckQuery succeeds
{
  "requestId": "…",
  "database": "alice",
  "tempTable": "fc_tmp_7f3ac190…",
  "destination": "alice/sales_parquet/",
  "queryStatus": "SUCCEEDED",
  // Athena writes the UNLOAD data manifest to the QUERY-RESULTS location, not the output
  // location. SPEC-119's finalize verifies against it (SPEC-119 FR-001).
  "dataManifestLocation": "s3://…/athenaresults/…-manifest.csv"
}
```

## File & Folder Structure

```
lambdas/file-converter-create-temp-table/create_temp_table.py   (+ tests)
lambdas/file-converter-start-unload/start_unload.py             (+ tests)
lambdas/file-converter-check-query/check_query.py               (+ tests)
lambdas/file-converter-drop-temp-table/drop_temp_table.py       (+ tests)   # Glue only — no S3 delete
lambdas/file-converter-common/fccommon/
├── ddl.py        # temp-table DDL (safe fc_tmp_{hex32} names, Hive JSON serde) + projection
└── unload.py     # the UNLOAD statement builder (CAST list, partition cols LAST, ClientRequestToken)
infra/modules/file-converter/policies/execution.json.tftpl      # + Glue/Athena/LF grants; still NO s3:DeleteObject
infra/modules/file-converter/lambda.tf                          # + FC_ATHENA_WORKGROUP / FC_ATHENA_RESULTS_PREFIX env
infra/modules/file-converter/state-machine.asl.json.tftpl       # the Wait/Check/Choice loop + DropTempTable
infra/main.tf                                                    # LF admins (constructed string in locals)
```

## Implementation Phases

### Phase 1: IAM + LF admin

- The Glue/Athena/LF grants; the LF-admins entry as a constructed string in root `locals`. Apply, and expect the documented first-apply re-run on a from-scratch deploy.

### Phase 2: Temp table + UNLOAD

- `create-temp-table` (safe `fc_tmp_{hex32}` identifiers; **DDL via `StartQueryExecution` in the dedicated workgroup with the short in-Lambda poll — FR-001**; the explicit column list from SPEC-117's target schema; CSV OpenCSVSerde all-string; the **Hive** JSON SerDe; partition projection) and `start-unload` (the CAST list from the target schema; `partitioned_by`; **partition columns LAST in the `SELECT`**; **`ClientRequestToken = requestId`**, a byte-deterministic statement builder).
- Tests: CSV; JSON; a partitioned source; the generated name matching `^fc_tmp_[0-9a-f]{32}$`; **a retried submission returning the original `QueryExecutionId` rather than starting a second `UNLOAD`**; the token within Athena's 32–128 bound; a changed-parameter retry surfacing the idempotency error as `query_failed`; a partitioned statement putting the partition columns last; a retry finding the table already present; a string-fallback column casting to `VARCHAR`.

### Phase 3: The loop + `drop-temp-table` + end-to-end

- `check-query`; the SFN `Wait`/`Choice` loop; `query_failed` and `query_timeout` terminals **with the `AthenaError`/`StateChangeReason` detection mechanism pinned by a test**; `drop-temp-table` (**Glue only — no S3 delete anywhere**).
- **The cleanup test: force a mid-`UNLOAD` failure, assert the temp Glue table is gone, assert NO `DeleteObject` call was made, and assert the failure notification names the destination path where partial output may remain.**
- End-to-end: convert a real multi-file partitioned CSV folder and confirm Table Builder can create a correctly-typed table over the Parquet output. Completion ritual.
