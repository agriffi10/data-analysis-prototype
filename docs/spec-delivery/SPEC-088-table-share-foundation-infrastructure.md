# Completed Spec — SPEC-088: Table Share Foundation Infrastructure + Common Layer

## What was completed?

The **dedicated, asynchronous control plane** for "share a table across databases" —
plumbing + Lambda stubs only, no request contract or action logic (those are
SPEC-089→092). Mirrors the table-builder control-plane pattern with **one shared
execution role** from day one. New `infra/modules/table-share/`:

- **FIFO** request queue (`.fifo`) + **FIFO DLQ** (redrive `maxReceiveCount=3`);
  `MessageGroupId` = source `database.table` (set by the producer, SPEC-089).
  **Content-based dedup OFF** (FR-001) — the explicit `MessageDeduplicationId` =
  `requestId` is the only dedup, so a genuinely repeated share isn't absorbed.
- **EventBridge Pipe** (SQS → Step Function, batch 1, `FIRE_AND_FORGET`) + pipe role.
- **Standard Step Function** — `ValidateAuthorize → InspectSource →
  Map($.recipients): CheckTargetAbsent → CopyObjects → CreateTable → Succeed`;
  transient-Lambda `Retry` on every Task, **per-item Catch → RecipientFailed** (a
  recipient's failure never aborts siblings), whole-request Catch → `Fail`. The Map's
  `ItemSelector` hands each iteration `{recipient, request}`; results collect under
  `$.recipientResults`. 14-day vended-logs group + SFN role.
- **Five verb Lambdas** (placeholder zip + `ignore_changes=[…,layers]`, py3.12) on
  **one shared execution role** (`dat-prod-table-share-execution-role`) with a
  **logs-only** policy at this stage; per-task timeout/memory (validator 15s/256MB …
  copy-objects 900s/1024MB); 14-day log groups.
- **`table-share-common` (`tscommon`) layer** — CI-built/published
  (`deploy-lambdas.yml` `table_share_layer` job, PyJWT deps + the `tscommon` package
  with stubbed config/clients/auth/registry/copy/notify namespaces), attached to all
  five verbs (`tscommon: true` matrix flag).
- Wired into root `main.tf` as `module.table_share` (depends_on base only; the
  LF-admin + analytics wiring is SPEC-092's).

Shipped per the deploy-perms-before-resources rule as **two PRs**: **PR1 (#192)** the
deploy-role IAM (managed policy `dat-deploy-table-share`, scoped `*-table-share-*`;
no S3-bucket statement) → applied → **PR2 (#193)** the module + stubs + CI + smoke doc.

No component-inventory rows (infra + Lambda stubs only — the inventory tracks app
code) and no Help-content change (nothing user-facing shipped).

## What changed from earlier specs?

- **`deploy-lambdas.yml`** gained the `table_share_layer` job + 5 matrix rows, and the
  deploy step now runs `aws lambda wait function-active-v2` before
  `update-function-code` — the SPEC-088 first deploy raced Deploy Infrastructure's
  function creation (state `Pending` → `ResourceConflictException`); the wait closes
  that race for every function.

## Verification

`tofu fmt`/`validate` clean; ASL/policy templates render to valid JSON; stubs compile;
PR `plan` green against live AWS (proving PR1's grants, incl. plan-time
`states:ValidateStateMachineDefinition`). **Live smoke test (post-merge):** a message
on the FIFO queue drove Pipe → SFN → all five placeholders in order (one recipient-Map
iteration) → execution **SUCCEEDED**, `recipientResults` collected, CloudWatch lines
present, no Glue/S3 side effects. Documented in `docs/testing/e2e.md`.
