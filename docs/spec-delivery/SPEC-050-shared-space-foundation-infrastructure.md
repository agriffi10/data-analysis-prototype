# Completed Spec — SPEC-050: Shared-Space Foundation Infrastructure

## What was completed?

Plumbing for the shared-connections arc — **no access model, no action semantics** (SPEC-056 / SPEC-051→055). All infra; no app code.

- **New bounded-context module `infra/modules/shared-spaces/`** (standalone-deployable, constructed-string cross-module ARNs):
  - `dat-prod-shared-space` bucket (`s3.tf`) — user-space hygiene: public-access blocked, SSE-S3, `BucketOwnerEnforced`, versioning off, 7-day abort-incomplete-multipart, CORS (localhost + `app_url`). No bucket policy / access grants yet.
  - Control plane: **FIFO** request queue + FIFO DLQ (redrive, `sqs.tf`); **EventBridge Pipe** (`pipe.tf`, batch 1, `FIRE_AND_FORGET`) → **Standard** Step Function skeleton (`stepfunction.tf` + `state-machine.asl.json.tftpl`: Dispatch→Lambda, Retry/Catch→Fail, Succeed) → **provisioner Lambda** (`lambda.tf`, placeholder + `ignore_changes`). 14-day CW log groups.
  - **One privileged orchestrator role** for both SFN + Lambda (`iam.tf`, trust = states + lambda) with Glue/LF/S3(shared+admin-registry)/Cognito-admin/states/logs perms (`policies/orchestrator-permissions.json.tftpl`); separate **pipe role**.
- **Registry storage (FR-002)** — reuses the analytics admin bucket under `shared-spaces/`; `expire-admin-results` rescoped to `filter { prefix = "fallback-results/" }` and the workgroup fallback `OutputLocation` moved to `fallback-results/` so registry objects never expire.
- **Provisioner skeleton** `lambdas/shared-space-provisioner/shared_space_provisioner.py` (dispatch/echo, never raises) + tests; `deploy-lambdas.yml` matrix row.
- **Deploy-role IAM** — shared-space grants (SQS/Pipes/Step Functions/Lambda/roles+`PassRole`/logs, scoped to `{project}-*-shared-space-*`) shipped as a **customer-managed policy** `dat-deploy-shared-spaces` (not inline), plus deploy-role self-management of its own managed policies.
- Root wiring + outputs; smoke test `docs/testing/shared-spaces-e2e.md` (**executed green**).

Deviations (all in the spec's "Implementation Decisions" section): FIFO+single-MessageGroupId for serial intake (user requirement; dup-name correctness is SPEC-051's conditional `PutObject`); one orchestrator role (per FR-003); FR-002 via prefix-scoped expiry (S3 can't exclude a prefix); deploy grants as a **managed** policy (the 10,240-char inline limit is a per-role *aggregate*).

## What changed from earlier specs?

- **SPEC-032 analytics** (`athena.tf`, `s3.tf`): workgroup fallback output moved to `fallback-results/` and `expire-admin-results` scoped to that prefix (was whole-bucket) so the new registry prefix is retained.
- **SPEC-011 base** (`iam.tf`, deploy policy): deploy role gained `iam:CreatePolicy/AttachRolePolicy` (+versions) on its own `*-deploy-*` managed policies; new managed policy attached. Personal-space model untouched.

## Verification

`tofu fmt`/`validate` clean; all `.tftpl` render to valid JSON; both deploy policies under their IAM size limits; provisioner unit tests pass. **Deployed to AWS** and the control-plane smoke test ran **end-to-end green** (SQS→Pipe→SFN `SUCCEEDED`→Lambda echo); FR-001 hygiene + FR-002 lifecycle-prefix confirmed live. Bring-up surfaced the architecture.md **plan-time validation deadlock** (`states:ValidateStateMachineDefinition`/`ListStateMachineVersions` are called at plan/refresh) — resolved with a temporary break-glass grant while the permanent managed-policy grants were PR'd in; a final break-glass-free apply confirmed self-sufficiency. **Lesson recorded:** PR deploy-role IAM *before* the resources that use it.
