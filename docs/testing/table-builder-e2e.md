# Table Builder — control-plane e2e / smoke test

Manual verification for the table-builder control plane (`infra/modules/table-builder/`).
Grows with the arc; **SPEC-066** covers the foundation smoke test (the message flows
through the Pipe → Step Function → the five stub Lambdas, no table created). Later specs
(SPEC-067→072) add the request-contract, per-step, and notification checks.

The pipeline:

```
Browser → SQS (FIFO requests.fifo) → EventBridge Pipe (batch 1) → Step Function (Standard)
   validate-authorize → check-table-absent → inspect-source → infer-schema → execute-ddl → Succeed
   (any step's failure → Catch → Fail)
```

Resource names (defaults; `dat`/`prod`):

| Resource | Name |
|---|---|
| Request queue | `dat-prod-table-builder-requests.fifo` |
| DLQ | `dat-prod-table-builder-requests-dlq.fifo` |
| Pipe | `dat-prod-table-builder-pipe` |
| State machine | `dat-prod-table-builder-orchestrator` |
| Verb Lambdas | `dat-prod-table-builder-{validate-authorize,check-table-absent,inspect-source,infer-schema,execute-ddl}` |
| polars layer | `dat-prod-table-builder-polars` (attached to infer-schema only) |

---

## SPEC-066 — foundation control-plane smoke test

**Goal:** a message placed on the FIFO request queue drives the Pipe → Step Function and
runs the five **stub** Lambdas in order (each echoes its input + logs to CloudWatch); no
table is created and nothing is validated yet.

### Request envelope (SPEC-067 contract)

The full envelope is defined in SPEC-067; for the SPEC-066 smoke test any JSON body works
(the stubs echo). A representative body:

```json
{
  "idToken": "<not verified yet — stub>",
  "space": { "kind": "personal", "bucket": "dat-prod-user-space", "prefix": "alice/sales/2026/", "database": "alice" },
  "tableName": "sales_2026",
  "partitionKeys": [],
  "requestId": "smoke-0001"
}
```

### Steps

1. **Enqueue** a message on the FIFO request queue (`MessageGroupId` = the target
   database; `MessageDeduplicationId` = the `requestId`). The browser can't yet send
   (the portal-role grant is SPEC-067); for the smoke test enqueue with the deploy/admin
   identity:

   ```bash
   QURL=$(aws sqs get-queue-url --queue-name dat-prod-table-builder-requests.fifo --query QueueUrl --output text)
   aws sqs send-message \
     --queue-url "$QURL" \
     --message-group-id alice \
     --message-deduplication-id smoke-0001 \
     --message-body '{"idToken":"stub","space":{"kind":"personal","bucket":"dat-prod-user-space","prefix":"alice/sales/2026/","database":"alice"},"tableName":"sales_2026","partitionKeys":[],"requestId":"smoke-0001"}'
   ```

2. **Confirm an execution started** on the state machine and **SUCCEEDED**:

   ```bash
   SM_ARN=$(aws stepfunctions list-state-machines \
     --query "stateMachines[?name=='dat-prod-table-builder-orchestrator'].stateMachineArn" --output text)
   aws stepfunctions list-executions --state-machine-arn "$SM_ARN" --max-results 1
   ```

   Expect status `SUCCEEDED`. Open the execution (console or `get-execution-history`) and
   confirm the states ran in order: `ValidateAuthorize → CheckTableAbsent → InspectSource
   → InferSchema → ExecuteDdl → Succeeded`.

3. **Confirm each stub logged** in CloudWatch (`/aws/lambda/dat-prod-table-builder-*`):
   each function emits `table-builder-<verb> stub invoked: …`.

4. **Confirm no table was created** — the stubs touch nothing; `SHOW TABLES` in the
   target database is unchanged.

### Expected result

- One state-machine execution per message, `SUCCEEDED`, all five states visited in order.
- Five CloudWatch log streams, one per verb, each with the stub line.
- No Glue table, no S3 writes.

### polars layer size (FR-003)

Recorded from the `polars_layer` job in the **Deploy Lambdas** workflow
(`table-builder-polars layer unzipped size: <N> MB`). The job fails if the unzipped
layer exceeds **240 MB** (headroom under Lambda's 250 MB unzipped limit).

- Measured unzipped size: **107 MB** (polars `1.12.0`; published `dat-prod-table-builder-polars:1`, 2026-06-30) — well under the 250 MB Lambda limit and the 240 MB CI cap.

### Notes

- The five verbs share **one execution role** (`dat-prod-table-builder-execution-role`),
  consolidated from the SPEC-066 per-verb roles (user decision). Its union policy is
  `policies/execution.json.tftpl`, and it is the table-builder **Lake Formation admin**
  (analytics `data_lake_settings`) so `check-table-absent` can Describe and `execute-ddl`
  can CREATE in the dynamic per-user / per-shared-space target databases.
- The `Failed` state is a plain `Fail` here; SPEC-070 finalizes the structured
  recorded-failure outcome that SPEC-072's notifications read.

---

## SPEC-067 — request contract + validate-authorize

### Request envelope (the contract)

The browser enqueues this JSON body (FIFO: `MessageGroupId = space.database`,
`MessageDeduplicationId = requestId`). The send helper lands in SPEC-071; the portal
role gains `sqs:SendMessage` on the queue here.

```jsonc
{
  "idToken": "<cognito ID token>",       // REQUIRED; actor derived from the verified claim
  "space": {
    "kind": "personal",                  // 'personal' | 'shared'
    "bucket": "dat-prod-user-space",     // user-space bucket | 'dat-prod-shared-space'
    "prefix": "alice/sales/2026/",       // the folder, within the space
    "database": "alice"                  // Glue DB the space maps to (username | shared name)
  },
  "tableName": "sales_2026",             // catalog-safe (CATALOG_IDENTIFIER_RE)
  "partitionKeys": [],                   // OPTIONAL; user-declared, granularity order; [] = flat
  "requestId": "f3a1…"                   // dedup + correlation
}
```

A partition key is one of:
`{"name","type":"integer","range":[min,max],"digits"?}` ·
`{"name","type":"date","range":[start,end],"format","interval"?,"intervalUnit"?}` ·
`{"name","type":"string","values":[…]}` (→ projection `enum`).

### What `validate-authorize` does (SPEC-067)

Verifies the ID token **offline** (pool JWKS) → `actor`; authorizes the target space
(personal: `database == actor`, user-space bucket, `prefix` under `{actor}/`; shared:
`actor` is an **active member** per `<admin-bucket>/shared-spaces/{database}.json`,
shared bucket, `prefix` under `{database}/`); validates `tableName` + `partitionKeys`;
emits `{actor, space, tableName, partitionKeys, location, requestId}`. Any failure
raises a `TerminalError` (`unauthorized` / `forbidden` / `invalid_table_name` /
`invalid_partition_keys`) → Catch → Fail, no downstream verb runs.

### Checks

1. **Valid request passes through validate** — enqueue with a real ID token (personal
   space = your own username/prefix). The SFN execution reaches the (stub)
   `CheckTableAbsent` carrying the validated payload (visible in the execution's
   `ValidateAuthorize` output: `actor`, normalized `space`, `location`).
2. **Forged / cross-user request is recorded-failed at validate** — a body with a
   `database`/`prefix` that isn't the token's user fails `forbidden` at
   `ValidateAuthorize` (Catch → Fail); no downstream state runs.
3. **Unit tests** — `lambdas/table-builder-validate-authorize/test_validate_authorize.py`
   (20 cases): valid personal/shared/partitioned; the `forbidden` /
   `invalid_table_name` / `invalid_partition_keys` / `unauthorized` terminal reasons.
   Run: `python3 -m pytest lambdas/table-builder-validate-authorize/` or
   `python3 lambdas/table-builder-validate-authorize/test_validate_authorize.py`.

> The portal role's `sqs:SendMessage` grant is in place, but the **browser** can't send
> until SPEC-071 wires the send helper + `VITE_TABLE_BUILD_QUEUE_URL` into
> `deploy-app.yml` + the GH repo variable. For a live check now, enqueue with the CLI
> (as in the SPEC-066 smoke test) using a real ID token in the body.

---

## SPEC-068 — check-table-absent + inspect-source

The two gathering/validation verbs now do real work (the stubs are gone). They run after
`validate-authorize` and before the (still stub) `infer-schema`.

### What each verb does

- **`check-table-absent`** — Glue `GetTable(database, tableName)`. `EntityNotFoundException`
  ⇒ pass the request through; a table that exists ⇒ terminal `table_exists`. Transient
  Glue errors are **raised** (SFN `Retry`), never terminalized.
- **`inspect-source`** — lists `space.prefix` (paginated, via the shared
  `tbcommon.s3_listing` ignore-rules: marker `DO_NOT_DELETE.txt`, `athenaresults/`,
  zero-byte, `_`/`.`-prefixed files are skipped) and validates:
  - **Layout vs declared keys** — empty `partitionKeys` ⇒ flat (no `key=value/`);
    non-empty ⇒ each declared key as an ordered Hive `key=value/` segment. Mismatch ⇒
    terminal `unexpected_partitioning` / `partition_layout_mismatch`.
  - **Format** — a single supported format across the data objects (Parquet/CSV/JSON).
    Terminal `mixed_formats` / `no_data_files` / `unsupported_format` otherwise.
  - Emits `{…request, format, partitioned, sampleObjectKey, location, fileCount}`.

### Checks

1. **Valid flat-Parquet request** flows `validate → check → inspect` and reaches the stub
   `InferSchema` with `format=parquet`, `partitioned=false`, a `sampleObjectKey`, and
   `fileCount` in the `InspectSource` output.
2. **Existing-name request** is recorded-failed at `CheckTableAbsent` (`table_exists`) —
   enqueue a `tableName` that already exists in the target DB; no downstream state runs.
3. **Mixed-format / bad-layout request** is recorded-failed at `InspectSource` with the
   specific reason.
4. **Unit tests** — `python3 -m pytest lambdas/table-builder-check-table-absent/
   lambdas/table-builder-inspect-source/` (pass/`table_exists`/transient-raise;
   flat-Parquet, partitioned-CSV match, and the `mixed_formats` / `no_data_files` /
   `unsupported_format` / `unexpected_partitioning` / `partition_layout_mismatch` reasons;
   ignore-rules).

## SPEC-069 — infer-schema (polars) → CREATE TABLE DDL

`infer-schema` scans the `inspect-source` sample object with a polars LazyFrame read
**directly from S3** (`scan_*('s3://…')`, object_store — **no `/tmp`**, only the byte
ranges each reader needs), derives the data columns, folds in the user-declared partition
columns, and emits the `CREATE EXTERNAL TABLE IF NOT EXISTS` DDL (with partition-projection
`TBLPROPERTIES`). Runs on **both** the `table-builder-polars` and `table-builder-common`
layers.
`execute-ddl` (running it) is SPEC-070.

### Type rules

- **Parquet** — native types (incl. real `date`/`timestamp`).
- **JSON/NDJSON** — inferred; date/datetime-looking **strings** → `date`/`timestamp`.
- **CSV** — **not** type-inferred: names from the header, every column `string`, via
  **OpenCSVSerde** + `skip.header.line.count=1`.

### Checks

1. **Flat-Parquet request** flows `inspect → infer`; the `InferSchema` output carries
   `columns` (native types) + a `STORED AS PARQUET` DDL, before the stub `ExecuteDdl`.
2. **Partitioned-CSV request** yields all-`string` columns and a DDL with
   `PARTITIONED BY (…)`, OpenCSVSerde, and `projection.*` `TBLPROPERTIES` (capture and
   eyeball it — no `MSCK REPAIR`).
3. **Unit tests** — `python3 -m pytest lambdas/table-builder-infer-schema/` (needs
   `polars` installed): `map_dtype` for every supported + nested + `Date`/`Datetime`
   dtype and a representative unmappable one; golden `build_create_table_ddl` strings for
   flat-Parquet, partitioned-CSV (all-string + projection), JSON, and a string `enum`
   key; the handler on real CSV/JSON/Parquet fixtures (all-string / date-parse / native),
   plus scan-error → `schema_inference_failed` and transient-S3 → raised.

> **CI runs the polars tests.** The `lambdas` CI job installs polars (from
> `lambdas/table-builder-infer-schema/requirements.txt`) so the type-mapping + handler
> tests execute for real, not just the pure DDL golden strings.

## SPEC-070 — execute-ddl + terminal states (end-to-end create)

`execute-ddl` runs the `infer-schema` `CREATE EXTERNAL TABLE IF NOT EXISTS` DDL via
**Athena** (`StartQueryExecution`, context DB = `space.database`, the analytics workgroup,
results → `s3://{space.bucket}/{space.database}/athenaresults/{actor}/`), polls
`GetQueryExecution` to terminal, and returns `status:"created"`. Projection (SPEC-069) makes
a partitioned table queryable immediately — **no `MSCK REPAIR`**, one query for both flat and
partitioned sources.

**Terminal states.** The pipeline now ends
`… → ExecuteDdl → RecordSuccess → Succeeded`; every verb's `Catch` routes to a single
recorded-failure path (`RecordFailure → Failed`) that shapes the structured
outcome SPEC-072 will notify from:

```jsonc
// RecordSuccess output (execution result on SUCCEEDED):
{ "requestId": "…", "actor": "alice", "database": "alice", "tableName": "sales_2026", "status": "created" }
// RecordFailure output (recorded in history before the Fail state):
{ "requestId": "…", "actor": "alice", "database": "alice", "tableName": "sales_2026",
  "status": "failed",
  "error": { "Error": "TerminalError",
             "Cause": "{\"errorMessage\": \"ddl_execution_failed: SYNTAX_ERROR …\"}" } }
```

A validate-authorize failure runs before the request identity exists, so its `Catch` routes
via `ValidateFailureSeed` (null identity) into the same `RecordFailure` state.

### execute-ddl role — LF admin + IAM (FR-005)

`execute-ddl` is made a **Lake Formation admin** (via `analytics` `data_lake_settings.admins`,
root-wired constructed ARN) so it can `CREATE` tables in the dynamic per-user / per-shared-space
target databases (they can't be statically enumerated). Its IAM role policy
(`policies/execute-ddl.json.tftpl`) is scoped to: Athena on the workgroup; Glue
`CreateTable`/`GetTable`/`GetDatabase`/`BatchCreatePartition`/`GetPartitions` on the account
catalog; `lakeformation:GetDataAccess`; S3 read on both data buckets; `PutObject` to
`*/athenaresults/*`; an explicit **deny** on `s3:DeleteObject`. The deploy role already carries
`PutDataLakeSettings` + scoped `iam:PassRole` on `*-table-builder-*` roles, so no deploy-role IAM
change was needed.

> **First-apply ordering (LF admin).** On a **from-scratch** apply, `module.analytics` writes
> `data_lake_settings` before `module.table_builder` creates the execute-ddl role (table_builder
> depends_on analytics), so LF may reject the not-yet-existing admin principal — **re-run the
> apply** once the role exists. On the live env the role already exists (SPEC-066), so this apply
> is clean.

Capture `simulate-custom-policy` for the execute-ddl role and confirm it **can**
`StartQueryExecution` + `glue:CreateTable` on a target-DB ARN and `PutObject` to an
`athenaresults/` key, and **cannot** `s3:DeleteObject` on a data key or touch the admin registry:

```bash
ROLE=dat-prod-table-builder-execution-role
POLICY=$(aws iam get-role-policy --role-name "$ROLE" --policy-name permissions --query PolicyDocument --output json)
aws iam simulate-custom-policy --policy-input-list "$POLICY" \
  --action-names glue:CreateTable athena:StartQueryExecution s3:PutObject s3:DeleteObject \
  --resource-arns arn:aws:glue:us-east-1:ACCT:table/alice/sales_2026 \
                  arn:aws:s3:::dat-prod-user-space/alice/athenaresults/x.txt \
                  arn:aws:s3:::dat-prod-user-space/alice/sales/part-0.parquet
```

### Checks (live, post-deploy)

1. **Flat-Parquet, personal space** — enqueue a request over a folder of Parquet files with a
   real ID token; the execution reaches `Succeeded` with the `status:"created"` outcome. Confirm
   the table appears (`SHOW TABLES IN alice` / schema rail) and a `SELECT … LIMIT 1` returns rows.
2. **Partitioned-CSV via projection** — enqueue over a Hive `key=value/` folder with declared
   partition keys; the table is created by the **same single `CREATE`** (confirm the execution
   ran exactly one Athena query — no `MSCK REPAIR`), and a partition-filtered
   `SELECT … WHERE year=… LIMIT 1` returns rows **without** any load step.
3. **Bad DDL** — force a failure (e.g. a table over a bad location) and confirm the execution ends
   `Failed` with the `RecordFailure` output carrying `reason: "ddl_execution_failed: …"`.
4. **Replay** — re-enqueue an already-created request; the `IF NOT EXISTS` create is a no-op
   `created` (not `table_exists`).
5. **Unit tests** — `python3 lambdas/table-builder-execute-ddl/test_execute_ddl.py` (11 cases):
   flat + partitioned success (assert exactly one query, no MSCK), personal/shared results
   routing, `ddl_execution_failed` (FAILED/CANCELLED/bad-start, reason carried), transient
   start/poll → `TransientError` (SFN Retry), `ddl_timeout`, replay no-op.

## SPEC-072 — outcome notifications (producer)

Every verb Lambda is now a **trusted producer** of the SPEC-058 notifications inbox: at its
terminal-failure branch it emits ONE `create` notification to the **actor** (a reason-specific
message), and `execute-ddl` emits a **success** notification on `status:created`. Best-effort —
a missed notification never changes the pipeline outcome (still recorded in the SFN execution).
No fan-out: every event has a single recipient, the actor. Wiring: each verb role gains
`sqs:SendMessage` on the **notifications queue ARN only**; each verb's `NOTIFICATIONS_QUEUE_URL`
env is the SPEC-058 queue; the shared best-effort helper is `tbcommon.notify.emit_notification`
(+ `emit_failure`/`emit_created`); the message text lives in `tbcommon.messages`.

> Depends on SPEC-058 (queue + writer). If unset, emit is a logged no-op — the pipeline still
> records its SFN outcome. **execute-ddl now attaches the `table-builder-common` layer** (it
> imports `tbcommon.config` since SPEC-070 + `tbcommon.notify` here) — the CI matrix flag was
> flipped `tbcommon: true`.

### IAM check (FR-001)

```bash
ROLE=dat-prod-table-builder-execution-role
POLICY=$(aws iam get-role-policy --role-name "$ROLE" --policy-name permissions --query PolicyDocument --output json)
NOTIF_ARN=arn:aws:sqs:us-east-1:ACCT:dat-prod-notifications-requests.fifo
aws iam simulate-custom-policy --policy-input-list "$POLICY" \
  --action-names sqs:SendMessage \
  --resource-arns "$NOTIF_ARN" arn:aws:sqs:us-east-1:ACCT:some-other-queue
# Expect: allowed on the notifications queue, implicitDeny on the unrelated queue.
```

### Checks (live, post-deploy)

1. **Success notification** — run a create that **succeeds** (the flat-Parquet check above); the
   actor's `/notifications` page (SPEC-060) shows *"Table "…" is ready to query in "…"."*.
2. **Failure notification** — run a create that **fails** (e.g. a `tableName` that already exists,
   or a mixed-format folder); the actor sees the matching message (*"…: a table with that name
   already exists…"* / *"…: the folder mixes file formats…"*). The SFN execution still ends
   `Failed` with its `RecordFailure` outcome regardless of the notification.
3. **No premature notification** — a transient/retryable step (e.g. a throttled Athena poll) does
   **not** emit; only the terminal branch does.
4. **Unit tests** — each verb suite asserts the actor recipient + mapped message + FIFO dedup
   (`{requestId}:{step}`) and **silence** on transient/non-terminal paths and (validate-authorize)
   on `unauthorized` (no actor). Plus `python3 lambdas/table-builder-common/test_notify.py` +
   `test_messages.py` (helper + message-map).

> **Corrected 2026-07-21 (PR #252):** the `ParseError` state is GONE from every control
> plane. It decoded the error Cause with `States.StringToJson`, which raises an
> uncatchable `States.Runtime` on any Cause that is absent or not JSON — killing the
> execution before the recorded-failure state. The terminal states now carry the RAW
> `error` object (`{Error, Cause}`) instead of a decoded `reason`; decode it with
> `cpcommon.errors.failure_reason`.

---

## The refresh arc (SPEC-143 → 145, 149, 157) — the two procedures that were wrong

Corrected 2026-08-14 (SPEC-186 FR-006). Both of the checks below **described procedures that
cannot produce the outcome they claimed**, and a careful tester following them files a defect
against working code. One of us already did.

### Adding a column: the sample is ONE OBJECT, and it is the FIRST KEY IN LISTING ORDER

The old wording was *"add a file with a new column, refresh and confirm it appears."* Schema
inference probes **exactly one** sample object per format — `sample_by_format.setdefault(fmt, key)`
in `inspect-source`, and `setdefault` keeps the **first** key the listing yields, which S3 returns
in lexicographic order. **A column added in a file that sorts later is invisible by design**, and
the refresh correctly reports `already up to date - no schema changes were found`. That is not a
bug and it must not be filed as one.

**Fixture, and the name matters.** Build the table from a folder holding:

| File | Header | Why |
|---|---|---|
| `part1.csv` | `id,region,amount` | the original schema |
| `part2.csv` | `id,region,amount` | a sibling, so the table is genuinely multi-file |

Then to add a column, upload:

| File | Header | Why |
|---|---|---|
| `part0.csv` | `id,region,amount,channel` | **sorts before `part1.csv`**, so it becomes the sample |

`part0` is the load-bearing detail. `part3.csv` would sort **last**, be ignored, and the refresh
would honestly report no change.

**Steps:**

1. Upload `part0.csv`, then **Refresh table** from the Query rail.
2. Expect `1 column added`; the rail reads `id, region, amount, channel`.
3. Delete `part0.csv` and refresh **without** ticking the opt-in. Expect a refusal naming
   **`channel`** — nothing changed.
4. Follow the notification link. The dialog opens pre-armed with `channel` named, the opt-in
   **unchecked**, and submit carrying an `aria-disabled` reason (SPEC-186 FR-002) rather than
   being silently dead.
5. Tick the opt-in and submit. Expect `1 column removed`.

**The casing control, in the same fixture:** upload `part00.csv` with headers `ID,Region,Amount`
(it sorts first, so it becomes the sample) against a stored schema of `id,region,amount`. Expect
`already up to date` and the rail **unchanged** — `diff-schema` folds case rather than seeing 3
added and 3 removed, and nothing is silently re-cased.

### SPEC-157's lock: two UI submits CANNOT contend, and that is measured

The old wording was *"submit two refreshes in quick succession from the UI."* **This cannot pass or
fail.** Two submits **2 seconds apart** — the floor two pre-armed browser tabs allow, using the
`/query?refreshTable=` deep link — **both returned independently** with no `refresh_already_running`
(measured 2026-08-14; a pair 9 s apart behaved the same). A small table's refresh completes inside
that window, so the lock is never contended.

**Use one of these instead.**

**A. Send two messages to the queue directly** (the reliable one). The lock is claimed by the
*execution*, so two messages are two executions:

```bash
QUEUE=$(aws sqs get-queue-url --queue-name dat-prod-table-builder-requests.fifo --query QueueUrl --output text)
BODY='{"action":"refresh_table","idToken":"<see the token note below>","space":{...},"tableName":"sales_livecheck","requestId":"contend-a"}'
for id in contend-a contend-b; do
  aws sqs send-message --queue-url "$QUEUE" \
    --message-body "$(printf '%s' "$BODY" | sed "s/contend-a/$id/")" \
    --message-group-id "refresh-contention" \
    --message-deduplication-id "$id" &
done
wait
```

The FIFO group serializes *delivery*, so use **the same group** and rely on the Pipe starting the
second execution while the first still holds the lock — or use **different groups** to remove even
that serialization. Either way the second execution must end with `refresh_already_running` and its
actor must get the refusal notification.

**B. Make the first refresh slow enough to overlap.** Point the table at a folder with **several
hundred objects** so `inspect-source`'s listing takes tens of seconds, then the two-tab UI method
works after all. Slower to set up, but it needs no raw token.

> **The raw ID token.** Procedure A needs one in the request envelope. Read it from devtools
> (Application → Local Storage, `idToken`) and **do not paste it into a shell command** — it is a
> live credential and it lands in shell history. Write it to a `600` file (`umask 077 && cat >
> /tmp/idtoken`), interpolate from `$(cat /tmp/idtoken)`, and `rm -f /tmp/idtoken` afterwards.

**Pass:** one execution succeeds, the other ends `refresh_already_running`, the loser is
**notified** rather than queued, and `logs/service=table-builder/` shows one lock claim and one
refusal. **Nothing that runs today proves this** — the unit tests simulate contention with a pinned
read, so until this is run the serialization is asserted, not demonstrated.

### Still owed here beyond the two above

- ~~The **partitioned**-table variant of the add/remove sequence.~~ **DISCHARGED 2026-08-16.**
  `agriffith_three.partfix` over `partfix/year=2025/part1.csv` + `partfix/year=2026/part2.csv`,
  declared key `year` (string, `2025, 2026`): the create was queryable by partition filter with no
  load step; `year=2025/part0.csv` gave **1 column added**; deleting it and refreshing without the
  opt-in refused naming **`channel`**; the link opened the dialog pre-armed with the opt-in
  unchecked and submit `aria-disabled`; ticking it gave **1 column removed**. **`part0.csv` must go
  in the FIRST partition** — the sample is the first key of the whole listing, so a file that sorts
  first inside `year=2026/` is still invisible. The partition key survived both refreshes (the same
  filtered SELECT kept working, `year` still projected). Evidence:
  `2026-08-16-live-check-session.md`.
- **SPEC-149's preservation check** — refresh a table carrying a `Description` and a column comment,
  then `GetTable`: both survive, the columns changed, and `get-table-versions` shows a previous
  version. This needs the SPEC-186 FR-004 verification role (`dat-prod-verification`); from any
  other principal it returns `Insufficient Lake Formation permission(s): Required Describe`.

  > **The role is one config line away, not available today — and DO NOT APPLY IT LOCALLY.**
  > It is created only once `verification_principal_arns` names a principal, because delegating
  > to the account root instead was rejected by the plan scan (`CKV_AWS_61`) for the right
  > reason. An earlier version of this note said to put the ARN in `infra/terraform.tfvars` and
  > apply; **following that would have destroyed production.** No human identity here can apply
  > locally: the laptop IAM user is not on the data buckets' policy allowlists, so tofu reads
  > `dat-prod-user-space` and `dat-prod-archive` as ABSENT and plans to destroy and recreate
  > them (measured 2026-08-14: `25 to add, 3 to change, 13 to destroy`, both buckets in the
  > replace set). The value is a **repo variable** applied by CI:
  >
  > ```bash
  > gh variable set TF_VAR_verification_principal_arns \
  >   --body '["arn:aws:iam::<account>:user/<you>"]'
  > ```
  >
  > Then run **Deploy Infrastructure** and expect a red first apply (IAM is eventually
  > consistent). Once it is green:
  > `aws sts assume-role --role-arn arn:aws:iam::<account>:role/dat-prod-verification
  > --role-session-name livecheck`.

  While you have that response, **paste it verbatim** as SPEC-153's owed foreign projection
  fixture.
