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

---

## SPEC-089 — request contract + validate-authorize

### Request envelope (the contract)

The browser enqueues this JSON body (FIFO: `MessageGroupId = "{source.database}.{source.table}"`,
`MessageDeduplicationId` = SHA-256 of token + content + a 1-minute bucket — content
dedup is OFF, this id is the only double-submit guard). The portal role gains
`sqs:SendMessage` here; the UI that sends lands in SPEC-093.

```jsonc
{
  "actor": "<cognito ID token>",           // REQUIRED; actor derived from the verified claim
  "source": { "database": "alice", "table": "orders" },
  "tableName": "orders_copy",              // catalog-safe (CATALOG_IDENTIFIER_RE); one name, all recipients
  "recipients": [
    { "kind": "user",  "name": "bob" },    // must exist in the User Pool
    { "kind": "space", "name": "salesteam" } // must be an ACTIVE registry space (membership NOT required)
  ]
}
```

### What `validate-authorize` does (SPEC-089)

Verifies the ID token **offline** (pool JWKS) → `actor`; authorizes the **source**
(personal: `source.database == actor`; otherwise the actor must be an **active
member** of that space per `<admin-bucket>/shared-spaces/{database}.json`); validates
`tableName`; normalizes recipients (dedupe on kind+name) and **annotates** each with
`valid` / `reason` (`unknown_user` / `unknown_space`) — an invalid recipient is NOT
fatal (it fails per-recipient in the Map; siblings proceed). Whole-request terminals
(`unauthorized` / `forbidden` / `invalid_table_name` / `invalid_recipients` /
`no_recipients`) route Catch → `ValidateFailureSeed → ParseError → RecordFailure →
Failed` with the structured `{actor, source, tableName, status:'failed', reason}`.

### Checks

1. **Forged / stub token is recorded-failed at validate** (live, CLI):

   ```bash
   QURL=$(aws sqs get-queue-url --queue-name dat-prod-table-share-requests.fifo --query QueueUrl --output text)
   aws sqs send-message --queue-url "$QURL" \
     --message-group-id alice.orders --message-deduplication-id smoke-089-bad-token \
     --message-body '{"actor":"forged","source":{"database":"alice","table":"orders"},"tableName":"orders_copy","recipients":[{"kind":"user","name":"bob"}]}'
   ```

   Expect the newest execution **FAILED**, with the `RecordFailure` state output
   carrying `status:"failed"`, null identity fields, and
   `reason: "unauthorized: token verification failed: …"`; no downstream state ran.
2. **Valid request** — not CLI-testable (the SPA app client is SRP/refresh-only, no
   CLI-mintable ID token — same as SPEC-051/067); exercised end to end by SPEC-093's
   UI. The recipient-annotation and authorization matrix is covered by the 15 unit
   tests.
3. **Unit tests** — `python3 lambdas/table-share-validate-authorize/test_table_share_validate_authorize.py`
   (or pytest): personal/shared source authz, inactive-space source, malformed
   source/recipients, name rule, dedupe, unknown-user/space annotation,
   any-active-space-is-a-valid-target.

---

## SPEC-090 — source resolution & copy plan (inspect-source)

`inspect-source` is real: Glue `GetTable` on the source → shape validation → clone
the definition verbatim (LOCATION stripped) → list the source objects (relative
keys + sizes, shared ignore rules incl. `_`/`.`-prefixed path segments) → enforce
`SHARE_MAX_OBJECTS` (1000) / `SHARE_MAX_TOTAL_BYTES` (20 GiB) → emit the copy plan
`{tableDefinition, location, objects[], partitioned}` merged over the request.

**Supported source shapes (v1):** base `EXTERNAL_TABLE`, flat or
partition-projection. Terminal reasons: `source_is_view` / `source_not_external` /
`source_catalog_partitioned` / `source_location_unsupported` (LOCATION must be
`s3://{user-space|shared-space}/prefix`) / `source_not_found` /
`source_not_readable` / `source_empty` / `source_too_large`.

### Checks

1. **Unit tests** — `python3 lambdas/table-share-inspect-source/test_table_share_inspect_source.py`
   (16 cases): the shape matrix, clone fidelity (+ projection props carried,
   bookkeeping params stripped), LOCATION rules, ignore rules/relative keys, both
   caps, transient-vs-terminal Glue error mapping.
2. **Live happy path is BLOCKED until SPEC-092** — the execution role isn't a Lake
   Formation admin yet, so `GetTable` on a real (LF-gated) personal/shared DB
   returns `AccessDenied` → terminal `source_not_readable`. This is expected; the
   end-to-end live share is SPEC-092's check. (The same LF foot-gun the
   table-builder hit — see its #174 bugfix.)

---

## SPEC-091 — recipient Map + copy (check-target-absent + copy-objects)

The recipient fan-out is real: the Map (MaxConcurrency 5) runs
`check-target-absent → copy-objects → create-table(stub)` per recipient with a
per-item `Catch → RecipientParseError → RecipientFailed` shaping
`{recipient, status:'failed', reason}` — one recipient's failure never aborts
siblings; the success path ends in `RecipientSucceeded` (`{recipient, status:'ok'}`).

- **check-target-absent**: invalid recipients (SPEC-089 annotation) short-circuit to
  their `unknown_user`/`unknown_space` terminal; destination =
  `{name}/shared_tables/{tableName}/` in the kind's bucket; `conflict` when the
  table exists in the recipient DB or the destination prefix is non-empty.
- **copy-objects**: `tscommon.copy.copy_prefix` — bounded-parallel (8) server-side
  `CopyObject`, layout preserved; > 5 GiB via multipart `UploadPartCopy` (1 GiB
  ranges, abort on failure); throttles → `TransientError` (SFN retries the
  idempotent verb), deterministic errors → `copy_failed`.

### Checks

1. **Unit tests** — `python3 lambdas/table-share-check-target-absent/test_table_share_check_target_absent.py`
   (8) + `python3 lambdas/table-share-copy-objects/test_table_share_copy_objects.py` (6):
   destination resolution, both conflict guards, invalid short-circuit,
   `target_not_readable`, layout-preserving keys, multipart range math + abort,
   transient/terminal mapping, concurrency bound.
2. **Live per-recipient path** — still gated on the SPEC-092 LF-admin wiring
   (recipient-DB `GetTable` → `target_not_readable` until then). The full live
   share (copy + create + per-recipient outcomes) is SPEC-092's check.
