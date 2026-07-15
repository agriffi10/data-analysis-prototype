# Data Quality — control-plane e2e / smoke test

Manual verification for the data-quality control plane (`infra/modules/data-quality/`).
Grows with the arc; **SPEC-108** covers the foundation smoke test (a message flows
through the Pipe → Step Function → the placeholder Lambdas, **including at least one
iteration of the Athena polling loop**; nothing is read, queried, or written). Later
specs (SPEC-109→114) add the request-contract, per-verb, and notification checks.

The pipeline:

```
Browser → SQS (FIFO requests.fifo) → EventBridge Pipe (batch 1) → Step Function (Standard)
   validate-authorize → inspect-source → create-temp-tables → start-profile-query
     → WaitForQuery(30s) → check-query → Choice(QUEUED/RUNNING? → WaitForQuery)   ◀── THE POLL
     → byte-scan → assemble-report → drop-temp-tables → RecordSuccess → Succeed
   (any failure → Catch → ParseError → DropTempTablesOnFailure → RecordFailure
                        → NotifyFailure → Fail)
```

Resource names (defaults; `dat`/`prod`):

| Resource | Name |
|---|---|
| Request queue | `dat-prod-data-quality-requests.fifo` |
| DLQ | `dat-prod-data-quality-requests-dlq.fifo` |
| Pipe | `dat-prod-data-quality-pipe` |
| State machine | `dat-prod-data-quality-orchestrator` |
| Verb Lambdas | `dat-prod-data-quality-{validate-authorize,inspect-source,create-temp-tables,start-profile-query,check-query,byte-scan,assemble-report,drop-temp-tables,notify-failure}` |
| dqcommon layer | `dat-prod-data-quality-common` (attached to all nine, with `cpcommon`) |
| polars layer | `dat-prod-data-quality-polars` (attached to **inspect-source only**) |
| Athena workgroup | `dat-prod-data-quality-wg` (**no** `bytes_scanned_cutoff_per_query`) |
| Execution role | `dat-prod-data-quality-execution-role` (ONE shared role, logs-only at SPEC-108) |

---

## SPEC-108 — foundation control-plane smoke test

**Goal:** a message placed on the FIFO request queue drives the Pipe → Step Function,
runs every placeholder verb in order, **iterates `WaitForQuery → CheckQuery → Choice` at
least once**, and reaches `Succeeded`. Nothing is authorized, listed, queried, scanned,
or written.

The polling-loop iteration is the point of this test. The poll living in the STATE
MACHINE (not inside a Lambda) is the structural decision the whole arc rests on — a
Lambda-internal poll cannot survive a query longer than its 900 s ceiling, and a
profiling query over 250 GB runs for minutes to tens of minutes. If this loop doesn't
cycle here, it never will.

### How the loop iterates without an Athena query

The `check-query` placeholder returns a deterministic status sequence driven by a
`pollCount` it carries in the threaded request: `RUNNING` on the first call, `SUCCEEDED`
after. So the Choice loops back to `WaitForQuery` exactly once (≈30 s), then proceeds —
provably exercising the loop, and terminating. (SPEC-111 replaces this with a real
`GetQueryExecution`.)

### Request envelope (SPEC-109 contract, representative)

The full envelope is defined in SPEC-109; for this smoke test any JSON body works (the
placeholders pass it through). A representative body:

```json
{
  "requestId": "smoke-dq-0001",
  "idToken": "<not verified yet — placeholder>",
  "space": { "kind": "personal", "bucket": "dat-prod-user-space", "prefix": "alice/" },
  "location": "alice/sales/"
}
```

### Steps

1. **Enqueue** a message on the FIFO request queue. `MessageGroupId` = the **SHA-256 hex
   digest of the canonical target location** (SPEC-109) — never the raw location: SQS
   caps `MessageGroupId` at 128 chars and S3 keys reach 1024. `MessageDeduplicationId` =
   the `requestId` (content dedup is **OFF** on this queue; the explicit id is the only
   dedup). The browser can't yet send (the portal-role grant is SPEC-109's), so enqueue
   with the deploy/admin identity:

   ```bash
   QURL=$(aws sqs get-queue-url --queue-name dat-prod-data-quality-requests.fifo --query QueueUrl --output text)
   GROUP=$(printf 'dat-prod-user-space/alice/sales/' | shasum -a 256 | cut -d' ' -f1)
   aws sqs send-message \
     --queue-url "$QURL" \
     --message-group-id "$GROUP" \
     --message-deduplication-id smoke-dq-0001 \
     --message-body '{"requestId":"smoke-dq-0001","idToken":"stub","space":{"kind":"personal","bucket":"dat-prod-user-space","prefix":"alice/"},"location":"alice/sales/"}'
   ```

2. **Confirm exactly one execution started** and **SUCCEEDED** (allow ~1 min — the loop
   costs one 30 s `Wait`):

   ```bash
   SM_ARN=$(aws stepfunctions list-state-machines \
     --query "stateMachines[?name=='dat-prod-data-quality-orchestrator'].stateMachineArn" --output text)
   aws stepfunctions list-executions --state-machine-arn "$SM_ARN" --max-results 1
   ```

3. **Confirm the polling loop iterated** — the point of the test. In the execution
   history, `WaitForQuery` and `CheckQuery` must each appear **twice** (poll 1 →
   `RUNNING` → loop; poll 2 → `SUCCEEDED` → proceed):

   ```bash
   EXEC_ARN=$(aws stepfunctions list-executions --state-machine-arn "$SM_ARN" --max-results 1 \
     --query 'executions[0].executionArn' --output text)
   aws stepfunctions get-execution-history --execution-arn "$EXEC_ARN" \
     --query "events[?type=='TaskStateEntered' || type=='WaitStateEntered'].stateEnteredEventDetails.name" --output text
   ```

   Expect the order: `ValidateAuthorize InspectSource CreateTempTables StartProfileQuery
   WaitForQuery CheckQuery WaitForQuery CheckQuery ByteScan AssembleReport DropTempTables`.

4. **Confirm the placeholders logged** in CloudWatch (`/aws/lambda/dat-prod-data-quality-*`);
   `check-query` logs `poll=1 status=RUNNING` then `poll=2 status=SUCCEEDED`.

5. **Confirm nothing changed** — no Glue table, no Athena query, no S3 writes (the
   placeholders touch nothing and the execution role can only write logs).

### Failure-path check (the leak this prevents)

Force a failure (e.g. temporarily send a body the validator stub can't parse, or invoke
with a broken payload) and confirm the Catch path reaches **`DropTempTablesOnFailure`
before `RecordFailure → NotifyFailure → Failed`**. Cleanup running on the failure path is
not cosmetic: every failed request would otherwise **leak a temp Glue table into the
user's own database**, visible in the Query workspace's schema rail and eventually
colliding with their real table names.

### Expected result

- One state-machine execution per message, `SUCCEEDED`.
- `WaitForQuery`/`CheckQuery` entered **twice** (the loop cycled once).
- Nine CloudWatch log streams, one per verb (`notify-failure` only on a failure run).
- No Glue/Athena/S3 side effects.

### Notes

- The nine verbs share **one execution role** (`dat-prod-data-quality-execution-role`).
  At SPEC-108 its policy is **logs-only**; the S3 grants + the protected-object `Deny`
  land in SPEC-109, and the Glue/Athena/Lake-Formation-admin grants in SPEC-111.
- **`s3:DeleteObject` is granted nowhere in this arc, ever.** `drop-temp-tables` touches
  **Glue only**, which is what makes it safe to reach from every failure path — including
  a validator failure, where the body-supplied location is still untrusted.
- The workgroup deliberately has **no** `bytes_scanned_cutoff_per_query`: the shared
  portal workgroup's 10 GiB cutoff is 25× under a 250 GB check and would fail every real
  one. There is **no workgroup query-timeout field** — that is an account Service Quota
  (30 min default, 240 max, raised only by a support ticket). Not raised yet, by decision
  (2026-07-14): the 30-minute default is sufficient while the arc is in testing/concept.
- `RecordSuccess`/`RecordFailure` are `Pass` states; **nothing durable is written by a
  terminal state** — the report object (SPEC-112) is the artefact.
