# Completed Spec — SPEC-058: Notifications Foundation Infrastructure (Write Pipeline + IAM)

## What was completed?

The **write side** of the per-user notifications inbox — no UI (read service/hook = SPEC-059, header bell + page = SPEC-060, first `create` producer = SPEC-061). All infra + one Lambda; no app code.

- **New bounded-context module `infra/modules/notifications/`** (standalone-deployable, constructed-string cross-module ARNs):
  - **FIFO** request queue (`.fifo`, content-based dedup) + **FIFO DLQ** (redrive `maxReceiveCount`) — `sqs.tf`. Per-user serialization via `MessageGroupId = username`.
  - **notifications-writer Lambda** (placeholder + `ignore_changes`, py3.12) + 14-day log group + an **SQS event-source mapping (batch size 1)** that triggers the Lambda directly — `lambda.tf`. **No EventBridge Pipe, no Step Function** (one-task write).
  - **Single privileged writer role** — `iam.tf` + `policies/writer-permissions.json.tftpl`: `s3:GetObject`/`PutObject` on `…/*/user_settings/notifications.json` only (**no DeleteObject anywhere**), prefix-conditioned `s3:ListBucket` (for the new-user 404 disambiguation), SQS receive on the queue, logs. Plus a **portal-role `sqs:SendMessage`** fragment (`policies/portal-role-notifications.json.tftpl`) — the browser's only notifications privilege.
  - `variables.tf` / `locals.tf` / `outputs.tf` (queue url/arn + writer role arn).
- **Writer Lambda** `lambdas/notifications-writer/notifications_writer.py` — thin handler → `action`-switch read-modify-write (`create` | `markRead` | `markAllRead`; **no delete**), server-assigned `id`/`timestamp`, cap to `NOTIFICATIONS_MAX` (200) by timestamp, missing/corrupt doc → `[]`. Offline-JWKS ID-token verification for user actions (username derived from `cognito:username`; `create` uses body username). 14 unit tests (`test_notifications_writer.py`). `deploy-lambdas.yml` matrix row added.
- **Deploy-role IAM** — shipped **first, in its own PR** ([#124](https://github.com/agriffi10/data-analysis-prototype/pull/124)) as a customer-managed policy `dat-deploy-notifications` (off the inline aggregate, like `dat-deploy-shared-spaces`): SQS/Lambda/writer-role+`PassRole`/logs scoped to `*-notifications-*`, with the non-scopable **event-source-mapping** actions (incl. `lambda:ListTags`) isolated to a `"*"` statement.

> **Corrected 2026-09-07.** Three of those four actions — `Get`, `Update` and `DeleteEventSourceMapping` — DO accept an `event-source-mapping` ARN; only `Create` and `List` take none. The wildcard is still right, because the mapping's UUID does not exist when the policy is written and `lambda:FunctionArn` pins what an ARN pattern would. Method and evidence: `docs/decisions/infrastructure/`.

- Root `main.tf` wiring + `outputs.tf`; message contract + smoke test in `docs/testing/e2e.md`.

## What changed from earlier specs?

- **SPEC-011 base** (`iam.tf`, `policies/`): deploy role gained the `dat-deploy-notifications` managed policy (+attachment).
- **SPEC-013/051 data** (`s3.tf`, `variables.tf`, `policies/user-space-bucket-policy.json.tftpl`): the notifications-writer role ARN was added to the user-space bucket policy's data-access-Deny exclusion list (same shape as the shared-space orchestrator), so the writer can read-modify-write `notifications.json`. Personal-space model otherwise untouched.

## Verification

`tofu fmt`/`validate` clean; all `.tftpl` render to valid JSON; writer policy `simulate-custom-policy` (PutObject `notifications.json` allowed; adjacent key + DeleteObject `implicitDeny`; ReceiveMessage allowed); 14/14 Python unit tests pass. **Deployed to AWS** and the write path ran **end-to-end green**: two `create`s for one user processed in arrival order (inbox `1`→`2`, proving FIFO per-user serialization + RMW with no lost update); a token-less user action was rejected (`AuthorizationError` → retry → DLQ). Live `markRead`/`markAllRead` deferred (need a real Cognito ID token) — covered by unit tests + documented in the e2e doc. **Lessons (recurred from SPEC-050):** the AWS provider reads an event-source-mapping's tags via `lambda:ListTags` on the mapping ARN (add it to the ESM `"*"` grant); a new privileged role that writes the user-space bucket must be **excluded from the bucket-policy Deny**; and a backend doing RMW needs prefix-conditioned `s3:ListBucket` or `GetObject` on a missing key 403s instead of 404s. The ESM-tag fix hit the documented refresh-before-policy-update deadlock → resolved with a temporary break-glass `lambda:ListTags` on `*`, then removed.
