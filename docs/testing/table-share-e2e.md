# Table Share — control-plane e2e / smoke test

Manual verification for the table-share control plane (`infra/modules/table-share/`).
Grows with the arc; **SPEC-088** covers the foundation smoke test (a message flows
through the Pipe → Step Function → the placeholder Lambdas, incl. one recipient-Map
iteration; nothing is copied or created). Later specs (SPEC-089→094) add the
request-contract, per-verb, and notification checks.

The pipeline:

```
Browser → SQS (FIFO requests.fifo) → EventBridge Pipe (batch 1) → Step Function (Standard)
   validate-authorize → inspect-source → Map(recipients):
        check-target-absent → copy-objects → create-table   (per-item Catch → RecipientFailed)
   → Succeed   (whole-request failure → Catch → Fail)
```

Resource names (defaults; `dat`/`prod`):

| Resource | Name |
|---|---|
| Request queue | `dat-prod-table-share-requests.fifo` |
| DLQ | `dat-prod-table-share-requests-dlq.fifo` |
| Pipe | `dat-prod-table-share-pipe` |
| State machine | `dat-prod-table-share-orchestrator` |
| Verb Lambdas | `dat-prod-table-share-{validate-authorize,inspect-source,check-target-absent,copy-objects,create-table}` |
| tscommon layer | `dat-prod-table-share-common` (attached to all five) |
| Execution role | `dat-prod-table-share-execution-role` (ONE shared role, logs-only at SPEC-088) |

---

## SPEC-088 — foundation control-plane smoke test

**Goal:** a message placed on the FIFO request queue drives the Pipe → Step Function,
runs `validate-authorize → inspect-source`, iterates the recipient `Map` once
(`check-target-absent → copy-objects → create-table` placeholders), and reaches
`Succeeded`. Nothing is validated, copied, or created.

### Request envelope (SPEC-089 contract, representative)

The full envelope is defined in SPEC-089; for this smoke test any JSON body with a
`recipients` array works (the placeholders pass through). A representative body:

```json
{
  "idToken": "<not verified yet — placeholder>",
  "source": { "database": "alice", "table": "orders" },
  "tableName": "orders_copy",
  "recipients": [{ "kind": "user", "name": "bob" }],
  "requestId": "smoke-ts-0001"
}
```

### Steps

1. **Enqueue** a message on the FIFO request queue (`MessageGroupId` = the source
   `database.table`; `MessageDeduplicationId` = the `requestId` — content dedup is
   OFF on this queue, the explicit id is the only dedup). The browser can't yet send
   (the portal-role grant is SPEC-089); enqueue with the deploy/admin identity:

   ```bash
   QURL=$(aws sqs get-queue-url --queue-name dat-prod-table-share-requests.fifo --query QueueUrl --output text)
   aws sqs send-message \
     --queue-url "$QURL" \
     --message-group-id alice.orders \
     --message-deduplication-id smoke-ts-0001 \
     --message-body '{"idToken":"stub","source":{"database":"alice","table":"orders"},"tableName":"orders_copy","recipients":[{"kind":"user","name":"bob"}],"requestId":"smoke-ts-0001"}'
   ```

2. **Confirm an execution started** on the state machine and **SUCCEEDED**:

   ```bash
   SM_ARN=$(aws stepfunctions list-state-machines \
     --query "stateMachines[?name=='dat-prod-table-share-orchestrator'].stateMachineArn" --output text)
   aws stepfunctions list-executions --state-machine-arn "$SM_ARN" --max-results 1
   ```

   Expect status `SUCCEEDED`. Open the execution (console or `get-execution-history`)
   and confirm the states ran in order: `ValidateAuthorize → InspectSource →
   ShareToRecipients` (one Map iteration: `CheckTargetAbsent → CopyObjects →
   CreateTable`) `→ Succeeded`.

3. **Confirm the placeholders logged** in CloudWatch (`/aws/lambda/dat-prod-table-share-*`):
   validate-authorize logs the pass-through request id; each other verb logs
   `placeholder <verb> invoked`.

4. **Confirm nothing changed** — no Glue table, no S3 writes (the placeholders touch
   nothing and the execution role can only write logs).

### Expected result

- One state-machine execution per message, `SUCCEEDED`, all five states visited
  (the three recipient verbs inside one Map iteration).
- Five CloudWatch log streams, one per verb.
- No Glue/S3 side effects.

### Notes

- The five verbs share **one execution role** (`dat-prod-table-share-execution-role`)
  from day one (user decision, `docs/table-share-architecture.md` §7). At SPEC-088 its
  policy is **logs-only**; the LF-admin / Glue / Athena / S3 / Cognito / registry /
  notifications grants land with the spec that first needs each (SPEC-089/090/092/094).
- The `Failed` state is a plain `Fail`; SPEC-089→092 add the structured
  recorded-failure outcomes (whole-request + per-recipient) that SPEC-094's
  notifications read.
- An **empty `recipients` array** is valid at this stage: the Map runs zero
  iterations and the execution still `Succeeded`s (per-recipient validation is
  SPEC-089's).
