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

- The verb roles are **per-verb least-privilege** (SPEC-066 FR-002). At this foundation
  stage validate-authorize and execute-ddl carry **logs only**; check-table-absent has
  Glue read; inspect-source / infer-schema have S3 read on both data buckets. Each owning
  spec (067→070) adds that verb's real grants.
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

`infer-schema` opens the `inspect-source` sample object with a polars LazyFrame, derives
the data columns, folds in the user-declared partition columns, and emits the
`CREATE EXTERNAL TABLE IF NOT EXISTS` DDL (with partition-projection `TBLPROPERTIES`).
Runs on **both** the `table-builder-polars` and `table-builder-common` layers.
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
