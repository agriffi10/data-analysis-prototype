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
