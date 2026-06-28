# Spec: Table Builder — Execute DDL, Load Partitions & Terminal States

**ID:** SPEC-070
**Status:** Draft
**Last Updated:** 2026-06-27
**Depends On:** SPEC-069 (generated DDL + resolved columns), SPEC-068 (partition keys), SPEC-067 (validated target DB/location), SPEC-066 (control plane + execute-ddl function/role), SPEC-032 (Athena workgroup + Lake Formation hybrid registration), SPEC-033 (per-DB LF grant pattern)

> **Reference:** `docs/table-builder-architecture.md` §5. Fifth of the arc — completes the **end-to-end** create
> (sans notifications/UI). Implements **`execute-ddl`**: run the generated `CREATE EXTERNAL TABLE` via **Athena**
> against the target database, then **`MSCK REPAIR TABLE`** for partitioned data, and record terminal success;
> finalizes the state machine's success/failure terminal states + `Catch` across all verbs and the execute-ddl
> role's LF/Glue/Athena/S3 grants. Follows `docs/best-practices/lambdas/lambdas.md`.

## Overview

Run the table into existence. `execute-ddl` takes the `infer-schema` payload (the `CREATE EXTERNAL TABLE IF NOT
EXISTS` DDL + the target database/location), submits it through **Athena `StartQueryExecution`** in the shared
analytics workgroup (SPEC-032), and polls to a terminal state — the user's stated "use the create statement to
run against the database." When the source is **Hive-partitioned**, it then runs **`MSCK REPAIR TABLE`** so the
existing partitions are loaded and the table is immediately queryable. On success the request reaches the state
machine's **succeed** state; on any Athena failure it routes (via `Catch`) to the **recorded-failure** state with
the reason. Because the table is created over an LF-registered location in another concern's database, this spec
also finalizes the execute-ddl role's Lake Formation / Glue / Athena / S3 permissions (the broad role of the
arc), scoped as tightly as the model allows.

## Scope

### In Scope

- **`execute-ddl` Lambda** — `StartQueryExecution(QueryString=ddl, QueryExecutionContext={Database: database},
  WorkGroup=<analytics workgroup>, ResultConfiguration → the space's `athenaresults/{actor}/`)`; poll
  `GetQueryExecution` to terminal (reuse the polling cadence/cap constants pattern from SPEC-034). `SUCCEEDED` ⇒
  proceed; `FAILED`/`CANCELLED` ⇒ terminal `ddl_execution_failed` (carry Athena's `StateChangeReason`).
- **Partition load** — when `partitioned=true`, after a successful `CREATE`, run **`MSCK REPAIR TABLE
  \`{database}\`.\`{tableName}\``** via Athena and poll to terminal; a repair failure is terminal
  `partition_load_failed` (the table exists but partitions weren't loaded — reason recorded).
- **Idempotency / replay-safety** — `CREATE … IF NOT EXISTS` (SPEC-069) + the SPEC-068 pre-check make a re-run a
  no-op success; `MSCK REPAIR` is naturally idempotent. A replayed terminal request is a no-op success
  (`lambdas.md` §3).
- **Terminal states across the machine** — finalize the SFN **succeed** state (after execute/repair) and the
  shared **recorded-failure** state that every verb's `Catch` targets, carrying `{ requestId, actor, database,
  tableName, status:'failed', reason }` (and `status:'created'` on success) — the structured outcome SPEC-072
  reads to notify.
- **execute-ddl role (the broad verb role)** — finalize its `.tftpl` policy: Athena
  `StartQueryExecution`/`GetQueryExecution`/`StopQueryExecution`/`GetWorkGroup` on the workgroup; Glue
  `CreateTable`/`GetTable`/`GetDatabase`/`BatchCreatePartition`/`GetPartitions` on the target catalog DBs; S3
  `GetObject`/`ListBucket` on both data buckets (Athena reads the data + the table location) and
  `GetObject`/`PutObject` on the `athenaresults/` results prefixes; **Lake Formation** as required to create over
  the registered locations. Non-scopable actions isolated to `"*"`; `simulate-custom-policy`-verified.
- **Lake Formation wiring** — the execute-ddl role is made an LF principal with `CREATE_TABLE` on target databases
  + `DATA_LOCATION_ACCESS` on the registered data locations (mirroring SPEC-033's per-DB grant for the portal
  role), so a table can be created over the LF-registered (hybrid) buckets under enforcement.
- **Deploy-role IAM** — finalized for the execute-ddl role's grants incl. the LF `GrantPermissions` wiring +
  scoped `iam:PassRole`.

### Out of Scope

- **Notifications** of success/failure — **SPEC-072** (this spec records the structured terminal outcome; the
  inbox message is the producer spec).
- **The browser UI / enqueue** — SPEC-071.
- **DDL generation / schema inference / inspection** — SPEC-068/069 (consumed here).
- **`ALTER TABLE ADD PARTITION` projection / partition projection tuning** — v1 uses `MSCK REPAIR TABLE`;
  partition projection is a future optimization.

---

## Functional Requirements

### FR-001: Execute the CREATE via Athena

#### Acceptance Criteria:

- [ ] The Lambda runs the `infer-schema` DDL via `StartQueryExecution` with `QueryExecutionContext.Database =
  space.database`, the analytics `WorkGroup`, and `ResultConfiguration.OutputLocation` =
  `s3://{space.bucket}/{space-root}/athenaresults/{actor}/` (personal user-space or shared-space results prefix,
  per `table-builder-architecture.md` §5); it polls `GetQueryExecution` to terminal.
- [ ] `SUCCEEDED` ⇒ proceed (to partition load or success); `FAILED`/`CANCELLED` ⇒ terminal
  `ddl_execution_failed` carrying Athena's `StateChangeReason`. A throttling/transient Athena error is **raised**
  for the SFN `Retry` (not terminal).
- [ ] Polling honors a max duration cap (as SPEC-034's `MAX_POLL_DURATION_MS` pattern); exceeding it is a terminal
  `ddl_timeout` (the query may still finish in Athena — recorded, not silently lost).

### FR-002: Load partitions for partitioned tables

#### Acceptance Criteria:

- [ ] When `partitioned=true`, after a successful `CREATE` the Lambda runs `MSCK REPAIR TABLE
  \`{database}\`.\`{tableName}\`` via Athena and polls to terminal; success ⇒ proceed to the succeed state.
- [ ] A repair failure ⇒ terminal `partition_load_failed` (reason recorded; the created table is left in place —
  the next run's `IF NOT EXISTS` + repair can recover).
- [ ] A **flat** source (`partitioned=false`) skips the repair entirely.

### FR-003: Idempotency / replay-safety

#### Acceptance Criteria:

- [ ] Re-running a request whose table already exists is a **no-op success** (the `IF NOT EXISTS` create succeeds
  trivially; `MSCK REPAIR` is idempotent) — not a `table_exists` error (that guard is the *pre-create*
  SPEC-068 check; a replay after creation must not fail).
- [ ] A replay of an already-terminal request reaches the same terminal state without duplicate side effects
  (`lambdas.md` §3).

### FR-004: Terminal states + structured outcome

#### Acceptance Criteria:

- [ ] The state machine has a **succeed** state reached after execute (+ repair) and a single **recorded-failure**
  state that every verb's `Catch` targets; both carry a structured outcome `{ requestId, actor, database,
  tableName, status, reason? }` (`status` ∈ `created|failed`) — the object SPEC-072 consumes.
- [ ] All five terminal failure reasons from the arc (`unauthorized`/`forbidden`/`invalid_table_name`,
  `table_exists`, `ambiguous_layout`/`no_data_files`/`mixed_formats`/`unsupported_format`,
  `schema_inference_failed`/`unmappable_type`, `ddl_execution_failed`/`partition_load_failed`/`ddl_timeout`) land
  in the recorded-failure state with their reason.

### FR-005: execute-ddl role + Lake Formation + deploy IAM

#### Acceptance Criteria:

- [ ] The execute-ddl role's `.tftpl` policy grants exactly the Athena/Glue/S3 actions in Scope, scoped to the
  workgroup, the target catalog DB ARNs, and the two data buckets' data + results prefixes; non-scopable actions
  isolated to `"*"`; `simulate-custom-policy` confirms it can create/repair a table in a target DB and write
  results, and **cannot** delete data objects or touch the admin registry.
- [ ] The role is granted LF `CREATE_TABLE` on target databases + `DATA_LOCATION_ACCESS` on the registered
  locations (SPEC-033 pattern); the deploy-role fragment is extended for these grants + scoped `iam:PassRole`;
  document the expected first-apply LF self-grant-propagation re-run (architecture.md `time_sleep` caveat).
- [ ] `tofu -chdir=infra validate` + `plan` clean.

### FR-006: Tests + e2e

#### Acceptance Criteria:

- [ ] Python unit tests (Athena/Glue stubbed): a `SUCCEEDED` create on a flat source reaches `created`; a
  partitioned source runs `MSCK REPAIR` then `created`; an Athena `FAILED` → `ddl_execution_failed` (reason
  carried); a repair failure → `partition_load_failed`; a transient Athena error is **raised** (retry), a timeout
  → `ddl_timeout`; a replay of an existing table → no-op `created`.
- [ ] `docs/testing/table-builder-e2e.md`: a real end-to-end run (flat-Parquet **and** partitioned-CSV) creates a
  queryable table in the target DB (visible in the schema rail / `SHOW TABLES`); a deliberately bad DDL records
  `ddl_execution_failed`. `simulate-custom-policy` output for the execute-ddl role is captured.

---

## Data Model

```python
# execute-ddl terminal outcome (recorded in the SFN succeed / recorded-failure state; read by SPEC-072)
{ "requestId": "f3a1…", "actor": "alice", "database": "alice", "tableName": "sales_2026",
  "status": "created" }                       # success
{ "requestId": "f3a1…", "actor": "alice", "database": "alice", "tableName": "sales_2026",
  "status": "failed", "reason": "ddl_execution_failed: SYNTAX_ERROR …" }   # any step's terminal failure
```

## Environment Variables

Server-side (`execute-ddl`): `ATHENA_WORKGROUP`, `USER_SPACE_BUCKET`, `SHARED_SPACE_BUCKET` (results-prefix
construction) — module env vars; no `VITE_*`.

## File & Folder Structure

```
lambdas/table-builder-execute-ddl/
├── execute_ddl.py            # run CREATE via Athena + poll; MSCK REPAIR if partitioned; emit terminal outcome
├── athena_run.py             # shared start+poll helper (cadence/cap constants, SPEC-034 pattern)
└── test_execute_ddl.py       # NEW

infra/modules/table-builder/
├── policies/execute-ddl.tftpl      # Athena + Glue table ops + S3 read/results + logs (FR-005)
├── lakeformation.tf                # LF CREATE_TABLE + DATA_LOCATION_ACCESS grants for the execute-ddl role (FR-005)
└── state-machine.asl.json.tftpl    # execute-ddl Task + succeed/recorded-failure terminal states (FR-004)

infra/modules/base/policies/        # deploy-policy-table-builder: execute-ddl grants + LF + PassRole (FR-005)
docs/testing/table-builder-e2e.md   # end-to-end create (flat + partitioned) (FR-006)
```

## Implementation Phases

### Phase 1: Execute + repair + terminal outcome

- `execute_ddl` (Athena start+poll; MSCK REPAIR when partitioned; idempotent replay) + the SFN succeed /
  recorded-failure states carrying the structured outcome; unit tests (FR-001, FR-002, FR-003, FR-004, FR-006
  partial).

### Phase 2: Role + Lake Formation + deploy IAM

- Finalize the execute-ddl role policy; LF `CREATE_TABLE` + `DATA_LOCATION_ACCESS` grants; deploy-role IAM +
  `iam:PassRole`; `simulate-custom-policy`; full e2e (FR-005, FR-006).
