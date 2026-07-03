# Completed Spec — SPEC-070: Table Builder Execute DDL & Terminal States

## What was completed?

`execute-ddl` — real logic replacing the SPEC-066 stub: run the `infer-schema`
`CREATE EXTERNAL TABLE IF NOT EXISTS` DDL via **Athena** against the target database, poll
to a terminal state, return the structured success outcome. Plus the state machine's
success/failure **terminal states** (shared `Catch` across all verbs) and the execute-ddl
role's **Lake Formation + IAM** finalization. This closes the **end-to-end create** (sans
notifications/UI). Projection (SPEC-069) means partitioned tables are queryable on the
single `CREATE` — **no `MSCK REPAIR`**, no partition-load step.

- **`athena_run.py`** — shared start+poll helper: `StartQueryExecution` (context DB,
  workgroup, results location) → poll `GetQueryExecution` to terminal under a wall-clock
  cap (`MAX_POLL_DURATION_SECONDS`, SPEC-034 pattern; `_now`/`_sleep` seams for tests).
  `SUCCEEDED` ⇒ return qid; `FAILED`/`CANCELLED` ⇒ `TerminalError("ddl_execution_failed",
  <StateChangeReason>)`; cap exceeded ⇒ `ddl_timeout`; throttling/5xx ⇒ **`TransientError`**
  (SFN Retry, not terminal).
- **`execute_ddl.py`** (handler) — runs the single CREATE (`config.ATHENA_WORKGROUP`,
  results = `s3://{space.bucket}/{space.database}/athenaresults/{actor}/` — personal own
  prefix / shared under the space, consistent with SPEC-055 routing), returns
  `{…event, status:"created"}`. Idempotent replay (`IF NOT EXISTS` + SPEC-068 pre-check) =
  no-op `created`.
- **`tbcommon`** (layer) — `errors.TransientError` (retryable; its type name is in the
  ExecuteDdl `Retry`), `clients.athena()`, `config.ATHENA_WORKGROUP`.
- **State machine** (`state-machine.asl.json.tftpl`) — `ExecuteDdl → RecordSuccess →
  Succeeded` (Pass shapes `{requestId, actor, database, tableName, status:"created"}`);
  every verb's `Catch` funnels to a single recorded-failure path `ParseError →
  RecordFailure → Failed` shaping `{…, status:"failed", reason}` (reason = the decoded
  Lambda error `errorMessage`, e.g. `"ddl_execution_failed: SYNTAX_ERROR …"`). A
  validate-authorize failure (before identity exists — array input) routes via
  `ValidateFailureSeed` (null identity) into the same `RecordFailure`. ExecuteDdl's `Retry`
  gains `TransientError`.
- **execute-ddl role** (`policies/execute-ddl.json.tftpl`) — Athena on the workgroup; Glue
  `CreateTable`/`GetTable`/`GetDatabase`/`BatchCreatePartition`/`GetPartitions` on the
  account catalog (`database/*` + `table/*/*` — target DBs are dynamic); `lakeformation:
  GetDataAccess`; S3 read on both data buckets; `PutObject` to `*/athenaresults/*`; explicit
  **deny** on `s3:DeleteObject`. `ATHENA_WORKGROUP` env wired (locals `table_builder_verb_env`).
- **Lake Formation** — execute-ddl is made an **LF admin** (analytics
  `data_lake_settings.admins`, root-wired constructed ARN) so it can CREATE in the dynamic
  per-user / per-shared-space target DBs (user decision — they can't be statically
  enumerated, so per-DB Terraform grants aren't possible).

## What changed from earlier specs?

- The SPEC-066 `execute-ddl` **stub** became real; the SPEC-066 `Failed` plain `Fail` state
  became the finalized `RecordSuccess`/`RecordFailure` terminal states carrying the
  structured outcome SPEC-072 will notify from.
- `analytics` gains a `table_builder_execute_ddl_role_arn` var, added to the LF admins
  `compact()` list (root-wired constructed string, like the shared-space orchestrator).
  *(Superseded: the per-verb roles were later consolidated into one shared execution
  role, and the var renamed `table_builder_execution_role_arn` — that single role is now
  the LF admin. See the Post-072 amendment in `docs/table-builder-architecture.md`.)*
- **No deploy-role IAM change** — the deploy role already carries `PutDataLakeSettings` and
  scoped `iam:PassRole` on `*-table-builder-*` roles (the LF-admin approach adds no new
  resource type).

## Design decision — LF admin (not per-DB grants)

Target databases are created dynamically (one per user by the SPEC-033 post-confirmation
Lambda; one per shared space by the SPEC-062 create verb), so static Terraform can't grant
`CREATE_TABLE` per DB. The user chose to make execute-ddl a **catalog-wide LF admin**
(contained in this spec — no cross-Lambda changes / backfill) over threading per-DB grants
through the DB-creating Lambdas. Its Glue/S3 IAM stays scoped; the deny-delete keeps it a
creator, not a destroyer.

**First-apply ordering:** `module.table_builder` depends_on `module.analytics`, so on a
from-scratch apply the execute-ddl role may not exist when `data_lake_settings` is written
→ LF rejects the unknown admin → **re-run the apply** (documented in `main.tf` + the e2e
doc). The live env already has the role (SPEC-066), so this apply is clean.

## Verification

**11** unit tests — `python3 lambdas/table-builder-execute-ddl/test_execute_ddl.py`: flat +
partitioned success (assert **exactly one** query — no MSCK), personal/shared results
routing + workgroup/context DB, `ddl_execution_failed` (FAILED / CANCELLED / bad-start,
reason carried), transient start/poll → `TransientError`, `ddl_timeout`, replay no-op. Other
table-builder Lambda tests still pass (infer-schema's polars tests need the layer, run in
CI). `tofu -chdir=infra validate` clean; rendered ASL is valid JSON with no dangling
transitions. Live e2e (flat-Parquet + partitioned-CSV via projection, bad-DDL failure,
`simulate-custom-policy`) is the runbook in `docs/testing/table-builder-e2e.md` — run
post-deploy.

## Next

**SPEC-071** — file-browser "Create table from this folder" UI (enqueue via the SPEC-067
contract). **SPEC-072** — the notification producer reads the terminal outcomes this spec
records.
