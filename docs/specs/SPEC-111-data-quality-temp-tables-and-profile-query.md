# Spec: Data Quality — Temp Tables + the Athena Profile Query

**ID:** SPEC-111
**Status:** Draft
**Last Updated:** 2026-07-13
**Depends On:** SPEC-107 (`cpcommon`), SPEC-108 (foundation, incl. the polling loop), SPEC-109 (authorization), SPEC-110 (the manifest), SPEC-032 (Athena/Glue/LF), SPEC-069/070 (table-builder's DDL + projection machinery, reused here)

> **Read `docs/data-quality-architecture.md` §0, §2.1, §5.1 and §7 first.** This is the spec that makes the arc work at 250 GB, and the spec that spends the arc's IAM budget.

## Overview

Four verbs and a loop. **`create-temp-tables`** builds throwaway Glue external tables over the source. **`start-profile-query`** launches the Athena queries that compute the exact checks. **`check-query`** reports their status, and the **Step Function** — not a Lambda — does the waiting. **`drop-temp-tables`** tears the tables down, on the success path *and* the failure path.

Five decisions here are load-bearing, and each prevents a specific disaster:

**The poll lives in the state machine.** Table-builder's `execute-ddl` polls Athena inside a 300-second Lambda (`infra/modules/table-builder/locals.tf:37`). That works for a `CREATE TABLE` returning in seconds and would be **fatal** for a profiling query over 250 GB that runs for minutes to tens of minutes — no Lambda can hold a poll open past 900 seconds. The Step Function loops instead, and Standard executions run for up to a year, so the time ceiling disappears.

**Cleanup runs on every path.** These are temporary tables in the *user's own* Glue database. A failure path that skips `drop-temp-tables` leaks a table into the database they browse in the Query workspace's schema rail, where it will accumulate and eventually collide with a real table name.

**The role becomes a Lake Formation admin.** Target databases are dynamic — one per user, one per shared space — so they cannot be statically LF-granted. This is the same reasoning that made table-builder's `execute-ddl` role an LF admin (SPEC-070). It is the largest privilege in this arc and it is unavoidable; §7 of the architecture doc records that the "zero catalog access" property of the earlier design is deliberately surrendered here.

**Three queries, separately degradable.** The **profile query** over the typed table is the check's backbone — its failure is terminal. The **ragged-rows query** (over the raw-line table) and the **duplicates query** are each allowed to fail: a `GROUP BY` over every column of a 250 GB table is a full shuffle — the most expensive thing Athena does, and a realistic way to exhaust query resources — and a pathological line can kill the raw-line read. Folded into one statement, either failure would take **every other finding down with it**. Isolated, each degrades to `not_computed` and the user still gets their report.

**Every query submission is idempotent (`ClientRequestToken`).** Without it, a Step Functions `Retry` after a transient error that arrived *after* submission starts a **second** query. Here that means polling a query nobody is watching; on the sibling `UNLOAD` path it means silently doubling the output data. The token is `requestId`-derived, so a retry re-attaches to the original execution.

## Scope

### In Scope

- **`create-temp-tables`**: a typed external table over the source (reusing table-builder's DDL and partition-projection machinery), **plus**, for CSV, a **single-column raw-line table** over the same folder — the trick that makes ragged-row detection possible at full scale (SPEC-112 consumes it).
- **`start-profile-query`**: starts **three** queries — the **profile query** computing the exact checks (§5.1 of the architecture doc) over the typed table, the **ragged-rows query** over the raw-line table, and the **duplicate-rows query** — the latter two degrading the report on failure rather than killing the check.
- **`check-query`**: returns all three queries' statuses as a map; the SFN `Wait`/`Choice` loop drives it.
- **`drop-temp-tables`**: idempotent teardown, reached on **both** the success and failure paths.
- The execution role's **Glue + Athena + Lake Formation admin** grants, and the LF-admins wiring.
- Terminal reasons: `query_failed`, `query_timeout`, `too_many_columns`.

### Out of Scope

- The **encoding** check and **cross-file column agreement** — SPEC-112. Neither can be done in SQL (see that spec).
- Report assembly and the report file — SPEC-112.
- Notifications — SPEC-114. UI — SPEC-113.
- Any *permanent* Glue table. Every table this spec creates is temporary and dropped. The pipeline never leaves a catalog artifact behind.
- Excel — unsupported in this arc.

---

## Functional Requirements

### FR-001: `create-temp-tables` — the typed source table

#### Acceptance Criteria:

- [ ] A Glue external table is created over the source location, in the **actor's own database** (personal) or the **shared space's database** (shared), named **`dq_tmp_{hex32}`** — where `{hex32}` is the request UUID **with its hyphens stripped**.
- [ ] A comment records why the name is shaped that way, because the obvious name does not work: a **leading underscore** forces Athena to require backticks around the identifier, and a raw **UUID's hyphens parse as subtraction**, so `_dq_{requestId}` is not a runnable identifier — it fails at query time, after the table exists. `dq_tmp_` + 32 hex characters needs no quoting, is unambiguously temporary, sorts away from real tables, and is still a pure function of `requestId`. A test asserts the generated name matches `^dq_tmp_[0-9a-f]{32}$`.
- [ ] **The column list is explicit and comes from SPEC-110's per-file probes** (their union, in the manifest's deterministic order). A comment records why: **Athena does not auto-detect a Parquet schema** — a `CREATE EXTERNAL TABLE` over Parquet or JSON must name every column and type, which is exactly why `inspect-source` carries a Parquet reader (SPEC-108 FR-003 / SPEC-110 FR-005).
- [ ] **`DQ_MAX_COLUMNS` (default 200)** caps the column count; a wider source is a terminal **`too_many_columns`** with a friendly message. A comment records the disaster this prevents: Athena caps a **query string at 262,144 bytes**, and FR-003 emits four `TRY_CAST`s plus a null-ratio and a sample aggregate **per column** — a pathological source would otherwise produce an unparseable query and a raw engine error instead of a clear one.
- [ ] CSV uses **OpenCSVSerde with all-string columns** and `skip.header.line.count = 1`, matching table-builder's shipped CSV behaviour (`table-builder-architecture.md` §4). Reading everything as string is what makes the `TRY_CAST` checks in FR-003 possible.
- [ ] **JSON uses the Hive JSON SerDe — `org.apache.hive.hcatalog.data.JsonSerDe` — and NOT the OpenX SerDe** (`org.openx.data.jsonserde.JsonSerDe`). A comment records why this is not a stylistic choice: AWS documents that OpenX **"can be non-deterministic"** and can produce **"unexpected null values when none are present."** This arc's entire JSON story is *"a null means the key was missing"* (FR-003's key-drift check falls out of the null ratios), so a SerDe that invents nulls would poison every JSON report **silently** — the report would look clean and be wrong. Parquet uses its native reader.
- [ ] **Partitioned sources** (from SPEC-110's `partitionKeys`) declare partition columns with **Athena partition projection**, reusing table-builder's machinery (SPEC-069). No `MSCK REPAIR` anywhere.
- [ ] Table creation uses `CREATE EXTERNAL TABLE IF NOT EXISTS`, so a retry is a no-op (the same natural idempotence table-builder relies on, `lambdas/table-builder-execute-ddl/execute_ddl.py:46`).
- [ ] The table name and database are written into the state so `drop-temp-tables` can find them **even if a later verb never ran**.

### FR-002: `create-temp-tables` — the raw-line table (CSV only)

#### Description

Ragged rows — rows whose field count doesn't match the header — are invisible to a normal SQL read, because the serde has already parsed them away. A second table over the same folder, with **one column and a delimiter that never occurs**, makes each row available as a raw string that SQL can split and count.

#### Acceptance Criteria:

- [ ] For CSV sources only, a second external table **`dq_tmp_raw_{hex32}`** (the same safe-identifier rule as FR-001) is created over the **same** location with a **single string column**, using **`LazySimpleSerDe` with `FIELDS TERMINATED BY '\001'`** — the ASCII SOH control character, which cannot occur in the text data — and **no** header skip, so every physical line, including the header, arrives as one raw string.
- [ ] The delimiter is written in the DDL as the **escape sequence `\001`**, never as a literal control byte. A comment records why: an invisible `0x01` pasted into a `.py` or `.md` file survives no diff review, no copy-paste and no editor round-trip — it silently becomes something else, and the ragged-row check then splits on a delimiter that *does* occur in the data. (This spec itself carried a literal `0x01` byte until it was caught in review.)
- [ ] For JSON and Parquet sources, this table is **not** created (rows are not line-delimited fields; the concept doesn't apply).
- [ ] A comment records what this table is for and why the alternative (reading bytes in a Lambda) is impossible at 250 GB.
- [ ] A comment records the **two** reasons the resulting count is approximate, not one: `split(line, ',')` over-reports on a **quoted comma**, *and* it over-reports on an **embedded newline inside a quoted field** — which makes one logical row look like two physical lines. SPEC-112 labels the figure with **both** caveats.
- [ ] A comment records Athena's **200 MB limit on a single line of text**: a file with a pathologically long line fails the raw-line table. That failure **degrades the ragged-row check** (reported as not computed, with a reason) rather than failing the whole request — a ragged-row count is not worth losing the null ratios, the type consistency and the duplicate count over.
- [ ] `drop-temp-tables` removes it too.

### FR-003: `start-profile-query` — the exact checks

#### Description

The checks a SQL engine can see exactly, at any scale — issued as **three separately-degradable queries**, because they fail differently and only one deserves to kill the check: **(1) the profile query** over the typed table (failure = terminal), **(2) the ragged-rows query** over the raw-line table `dq_tmp_raw_{hex32}` (failure degrades that figure to `not_computed`; the run continues), **(3) the duplicates query** over the typed table (failure degrades to `not_computed`). The honest scan-cost implication: the typed table is scanned **once** for the profile, the raw-line table **once** for ragged, and the typed table **again** for duplicates — the second typed-table scan is the price of not letting a full-shuffle failure destroy the report.

#### Acceptance Criteria:

- [ ] **Per-column type consistency (the headline check):** for each column, `TRY_CAST(col AS BIGINT)`, `AS DOUBLE`, `AS TIMESTAMP` and `AS DATE` are used to count the values that **fail** to parse while being non-null. The result identifies each column's dominant parseable type and the **exact count** of values that don't fit it, plus a capped sample (10) of offending values.
- [ ] **The offending-value sample aggregation is bounded regardless of how many values offend** — a naive `array_agg`-then-truncate accumulates O(rows) and is not acceptable. `dqcommon.sql` uses a bounded construct (e.g. Trino's n-ary **`max_by(col, salt, DQ_OFFENDING_VALUE_SAMPLE)`**, whose accumulator holds only N values).
- [ ] A column is reported as having a type-consistency issue when its dominant parseable type covers **≥ 90%** of its non-null values but not 100% — i.e. a mostly-numeric column with stray garbage. Columns below 90% are reported as `text` with no issue. The threshold is a named `dqcommon.config` constant, not a literal.
- [ ] **Type-consistency checks are SKIPPED entirely for Parquet sources**, and the report records that they were skipped and why. A comment records the reasoning: Parquet **enforces types in the format**, so a numeric column *cannot* contain stray text — every `TRY_CAST` would trivially succeed and the check is **vacuous**, not merely redundant. Emitting four `TRY_CAST`s per column over 250 GB of Parquet would scan the data to prove something the format already guarantees. Parquet sources still get null ratios, duplicates, row counts and — the one that matters most for Parquet — cross-file schema drift (SPEC-112 FR-002).
- [ ] **Null/blank ratio per column** — exact. (For JSON this is also the **key-drift** check: the Hive SerDe yields null for a missing key, per FR-001.)
- [ ] **Row counts** — exact, in total and **per file** via Athena's `$path` pseudo-column. Producing the per-file and global aggregates in **one** statement requires **`GROUP BY GROUPING SETS ((), ("$path"))`** (or a `UNION`) — noted here so the implementer does not false-start on a plain `GROUP BY`.
- [ ] **Ragged rows (CSV only) run as their OWN, SEPARATE query** over the FR-002 raw-line table: the count of rows where `cardinality(split(line, ',')) <> {headerColumnCount}`, excluding the header row. Its failure (e.g. Athena's 200 MB line limit, FR-002) degrades the figure to `not_computed`; the run continues.
- [ ] **Duplicate rows run as their OWN, SEPARATE Athena query** — never merged into the profile query. A comment records why: a `GROUP BY` over every column of a 250 GB table is a **full shuffle**, the single most expensive operation Athena offers and a realistic way to exhaust query resources. Isolating it means its failure **degrades the report instead of destroying it**.
- [ ] **The duplicates query's result shape is pinned to ONE row:** `SELECT COALESCE(SUM(cnt - 1), 0) AS duplicate_rows FROM (SELECT COUNT(*) AS cnt FROM {table} GROUP BY <all columns> HAVING COUNT(*) > 1)`.
- [ ] **Every query's result set is O(columns), never O(rows)** — the profile query aggregates per column, the ragged query returns counts, the duplicates query returns exactly one row. `assemble-report` (SPEC-112) reads these result files whole; this criterion is what makes that safe.
- [ ] **If the ragged or duplicates query fails on resources or times out, the report records that figure as `not_computed` with the reason, and the request still SUCCEEDS.** Everything else — type consistency, null ratios, row counts, cross-file agreement — still lands. A test forces each to fail and asserts the report is written, the verdict is produced, and only the failed figure is marked `not_computed`.
- [ ] **Every `StartQueryExecution` passes `ClientRequestToken` = the `requestId`** (suffixed per query — `{hex32}-profile` / `{hex32}-ragged` / `{hex32}-dupes` — so the three queries have distinct tokens that are still pure functions of `requestId`). A comment records the disaster this prevents: without it, a Step Functions `Retry` after a transient error that arrived **post-submission** submits a **second** query — the pipeline then polls one execution while another runs unwatched, and on the sibling file-converter's `UNLOAD` path the same bug silently doubles every row in the output. Idempotent submission is not optional.
- [ ] The queries write their results to the Athena results location **in the requesting space**, supplied **per query** via `ResultConfiguration.OutputLocation` (the workgroup cannot do this — it has one static result location, SPEC-108 FR-003). The result-location keys are returned in the state for SPEC-112 to read.
- [ ] **A shared-space check lands its results under `{spaceName}/athenaresults/` in the shared bucket — a new prefix convention, introduced here deliberately** (until now `athenaresults/` existed only as `{username}/athenaresults/` in the user-space bucket). SPEC-110 FR-001's listing exclusion covers `athenaresults/` in **both** buckets, so these results are never treated as source data.
- [ ] The queries are issued to the **dedicated workgroup** from SPEC-108 FR-003, which carries **no `bytes_scanned_cutoff_per_query`**.

### FR-004: `check-query` and the state-machine polling loop

#### Acceptance Criteria:

- [ ] `check-query` calls `GetQueryExecution` for **each** execution id in the state and returns a map — `{ profile: { status, resultLocation?, reason? }, ragged: { … } | null, duplicates: { … } }` (`ragged` is `null` for JSON/Parquet, which have no raw-line table) — nothing else. It does **not** wait, sleep, or loop.
- [ ] The Step Function drives the loop: `StartProfileQuery → WaitForQuery (Wait, 30 s) → CheckQuery → Choice`, looping back to `WaitForQuery` while **any** query's status is `QUEUED` or `RUNNING`.
- [ ] A comment on the loop records why the poll is not inside the Lambda: table-builder's in-Lambda poll pattern cannot survive a query longer than Lambda's 900-second ceiling, and this arc's queries routinely will.
- [ ] The **profile** query's `FAILED` or `CANCELLED` is a terminal `query_failed` whose friendly message carries **no raw Athena `StateChangeReason`** — that text stays in CloudWatch and the SFN execution history (SPEC-106 FR-008, matching `tbcommon/messages.py`).
- [ ] A **profile** query killed by the **account-level DML query-timeout Service Quota** (30 minutes by default; SPEC-108 FR-003) is a terminal **`query_timeout`** whose friendly message tells the user the source is too large — not a silent hang.
- [ ] A comment records that this timeout is an **account/Region Service Quota, not a workgroup setting** — there is no workgroup timeout field to raise, and the quota can only be increased (to a maximum of 240 minutes) by a support request. The handler must not go looking for a config value that does not exist.
- [ ] The **ragged** and **duplicates** queries' failure or timeout is **not** a terminal for the request — each degrades to `not_computed` (FR-003) and the run completes. Only the **profile** query's failure is terminal. A test asserts the handling differs.

### FR-005: `drop-temp-tables` — cleanup on every path

#### Acceptance Criteria:

- [ ] It drops both `dq_tmp_{hex32}` and (if created) `dq_tmp_raw_{hex32}`.
- [ ] It is **idempotent**: dropping a table that does not exist is a success, not an error. It must tolerate being reached before `create-temp-tables` ran at all.
- [ ] It is reached on the **success path** and, via the state machine's `Catch`, on **every failure path** (SPEC-108 FR-001).
- [ ] A test forces a failure in `start-profile-query` and asserts both temp tables are gone afterwards.
- [ ] A failure *inside* `drop-temp-tables` is logged and does not mask the original failure reason the user is notified about.

### FR-006: The execution role — Glue, Athena, and Lake Formation admin

#### Acceptance Criteria:

- [ ] The role gains Glue `CreateTable` / `GetTable` / `DeleteTable` / `GetDatabase`, Athena `StartQueryExecution` / `GetQueryExecution` / `GetWorkGroup`, and `lakeformation:GetDataAccess`.
- [ ] The role is added to `aws_lakeformation_data_lake_settings.admins`. A comment records why: target databases are **dynamic** (per user, per shared space) so they cannot be statically LF-granted — the same reasoning as SPEC-070's `execute-ddl` role.
- [ ] The admins entry is a **constructed string in root `locals`**, never a module output. A comment records the trap: an unknown element inside that `compact()` **silently drops the admins change** (`infra/modules/analytics/lakeformation.tf:19-22`), and a from-scratch first apply may need one re-run (`lakeformation.tf:26-30`).
- [ ] The role gains read/write on the **Athena results prefix** in both buckets.
- [ ] `s3:DeleteObject` is still granted **nowhere** in this arc.
- [ ] The `Deny` on `*/user_settings/*` and `*/DO_NOT_DELETE.txt` from SPEC-109 FR-006 remains in force.
- [ ] The architecture doc's §0 note — that this spec deliberately surrenders the "zero catalog access" property — is reflected in a comment on the policy template, so the next reader knows it was a decision and not drift.

---

## Data Model

```python
# lambdas/data-quality-common/dqcommon/config.py
DQ_TYPE_DOMINANCE_THRESHOLD: float = 0.90   # ≥90% parseable ⇒ report the stragglers as an issue
DQ_OFFENDING_VALUE_SAMPLE: int = 10         # capped sample of non-parsing values per column
DQ_QUERY_POLL_SECONDS: int = 30             # the SFN Wait interval
DQ_MAX_COLUMNS: int = 200                   # Athena caps a query STRING at 262,144 bytes
```

```sql
-- Safe identifiers: no leading underscore (Athena would need backticks), no UUID
-- hyphens (they parse as subtraction). {hex32} = requestId with hyphens stripped.
CREATE EXTERNAL TABLE IF NOT EXISTS alice.dq_tmp_7f3a…c19 (…explicit column list…)
-- JSON: org.apache.hive.hcatalog.data.JsonSerDe  (Hive — NOT OpenX, which can invent nulls)

-- CSV only — the raw-line table for ragged detection (SPEC-112 consumes it)
CREATE EXTERNAL TABLE IF NOT EXISTS alice.dq_tmp_raw_7f3a…c19 (line string)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe'
WITH SERDEPROPERTIES ('field.delim' = '\001')   -- ASCII SOH: never a literal 0x01 byte in source
LOCATION 's3://…/alice/sales/';
```

```jsonc
// The SFN state after CheckQuery reports every query done — one block per query (FR-003/FR-004).
// The Choice loops back to WaitForQuery while ANY block is QUEUED/RUNNING; a FAILED profile is
// terminal; a FAILED ragged/duplicates becomes not_computed and the run completes.
{
  "requestId": "…",
  "database": "alice",
  "tempTable": "dq_tmp_7f3ac19…",
  "tempRawTable": "dq_tmp_raw_7f3ac19…",   // null for json/parquet
  "profile": {                             // terminal on failure
    "status": "SUCCEEDED",
    "resultLocation": "s3://…/athenaresults/…/profile.csv"
  },
  "ragged": {                              // null for json/parquet; failure degrades, not kills
    "status": "SUCCEEDED",                 // | "not_computed"
    "resultLocation": "s3://…/athenaresults/…/ragged.csv",
    "reason": null                         // e.g. "a line exceeded Athena's 200 MB limit"
  },
  "duplicates": {                          // failure degrades, not kills
    "status": "SUCCEEDED",                 // | "not_computed"
    "resultLocation": "s3://…/athenaresults/…/dupes.csv",
    "reason": null                         // e.g. "query exhausted resources" when not_computed
  }
}
```

## File & Folder Structure

```
lambdas/data-quality-create-temp-tables/create_temp_tables.py   (+ tests)
lambdas/data-quality-start-profile-query/start_profile_query.py (+ tests)
lambdas/data-quality-check-query/check_query.py                 (+ tests)
lambdas/data-quality-drop-temp-tables/drop_temp_tables.py       (+ tests)
lambdas/data-quality-common/dqcommon/
├── sql.py       # the three query builders (FR-003) — bounded aggregates only (n-ary max_by, never bare array_agg)
└── config.py    # thresholds + the poll interval
infra/modules/data-quality/policies/execution.json.tftpl        # + Glue/Athena/LF grants
infra/modules/data-quality/state-machine.asl.json.tftpl         # the Wait/Check/Choice loop
infra/main.tf                                                    # LF admins (constructed string in locals)
```

## Implementation Phases

### Phase 1: IAM + LF admin

- The Glue/Athena/LF grants; the LF-admins entry as a constructed string in root `locals`. Apply, and expect the documented first-apply re-run on a from-scratch deploy.

### Phase 2: Temp tables

- `create-temp-tables` (safe `dq_tmp_{hex32}` identifiers; the explicit column list from SPEC-110's probes; the **Hive** JSON SerDe; partition projection, reusing table-builder's DDL helpers; the CSV raw-line table with `\001` + LazySimpleSerDe) and `drop-temp-tables` (idempotent).
- Tests: CSV, JSON, Parquet; the generated name matching `^dq_tmp_[0-9a-f]{32}$`; a >`DQ_MAX_COLUMNS` source producing `too_many_columns`; a partitioned source; a retry finding the table already present; dropping a table that was never created.

### Phase 3: The queries + the loop

- `dqcommon.sql` builds **the three queries — profile, ragged-rows, duplicates** (FR-003), with the bounded offending-value aggregate; `start-profile-query` starts all three with **distinct `ClientRequestToken` suffixes** and a **per-query `ResultConfiguration.OutputLocation`**; `check-query` returning the per-query status map; the SFN `Wait`/`Choice` loop over **any** running query; the `query_failed` and `query_timeout` terminals.
- Tests: **Parquet skipping the `TRY_CAST` checks** (and the report saying so); **the ragged and duplicates queries each failing and degrading to `not_computed` while the request still succeeds**; a retry re-attaching to the same query executions rather than starting second ones.
- **A cleanup test that forces a mid-query failure and asserts both temp tables are gone.**
- An end-to-end run against a real multi-file folder with a deliberately dirty column, asserting the exact counts. Completion ritual.
