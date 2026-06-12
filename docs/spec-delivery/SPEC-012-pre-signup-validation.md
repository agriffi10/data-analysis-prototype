# Completed Spec - Pre-Signup Username Validation (Cognito Trigger Lambda)

## What was completed from this spec?

Usernames are now enforced server-side at signup. A Cognito **pre-signup** trigger
Lambda rejects any registration whose username falls outside the authoritative
rule, before the user (and therefore their S3 prefix / `username` principal tag)
is ever created. Valid usernames pass through untouched — the normal email
verification flow (SPEC-009) proceeds unchanged.

This delivers the single-phase spec end to end as IaC; live verification runs on
the next `deploy-infra.yml` apply (see Checkpoint below).

**FR-001 — Validation rule:**
- One authoritative pattern, `^[a-zA-Z0-9._@-]{3,64}$`, defined once in the Lambda
  and quoted verbatim in a code comment + the spec. S3-prefix-safe and IAM-tag-safe
  (no `/`, spaces, `=`, or `,`).
- The SPEC-009 landing-page guidance text already matched this rule exactly
  ([`LandingPage.tsx`](../../apps/portal/src/routes/LandingPage.tsx) — "3–64
  characters, letters and numbers plus `. _ @ -` only"), so no app change was
  needed; verified during this work.
- Rejection throws the user-readable message
  `Username must be 3-64 characters using only letters, numbers, . _ @ -`, which
  the Hosted UI surfaces on the signup page.

**FR-002 — Pre-signup Lambda:**
- **`infra/modules/auth/lambda/pre-signup/index.mjs`** — pure ESM handler, no
  dependencies, no AWS API calls. Throws on mismatch; returns `event` unchanged
  on success (does not auto-confirm/auto-verify).
- **`infra/modules/auth/lambda.tf`** (new) — `archive_file` packaging (no build
  step), `aws_lambda_function` `dat-prod-pre-signup` (nodejs20.x, handler
  `index.handler`), a logs-only execution role, an explicit
  `aws_cloudwatch_log_group` with 14-day retention, and an `aws_lambda_permission`
  granting the User Pool `lambda:InvokeFunction` (scoped to the pool ARN). A fresh
  `time_sleep` IAM-propagation guard mirrors the auth/data pattern.
- **`infra/modules/auth/cognito.tf`** — `lambda_config.pre_sign_up` on the User
  Pool wired to the function ARN.
- **`infra/providers.tf`** — added `hashicorp/archive ~> 2.0` (lockfile updated
  with multi-platform hashes for CI).

**FR-003 — Deploy role permissions:**
- **`infra/modules/base/policies/github-actions-deploy.json.tftpl`** extended with
  three statements scoped to the function name pattern: `PreSignupLambdaManage`
  (lambda create/update/delete/tag/permission + read actions), `PreSignupLambdaExecRole`
  (IAM self-manage of the exec role incl. `iam:PassRole`), and `PreSignupLambdaLogs`
  (log group create/retention/tag). `cognito-idp:UpdateUserPool` (used to attach
  the trigger) was already granted. `project_name` is now passed into the
  `templatefile()` render.

## What has changed?

- **New infra**: `infra/modules/auth/lambda.tf` + `lambda/pre-signup/index.mjs`;
  `lambda_config` block added to the User Pool in `cognito.tf`.
- **Provider**: `hashicorp/archive` added to `providers.tf` + `.terraform.lock.hcl`.
- **Deploy role**: three new scoped statements in the base deploy policy; template
  now receives `project_name`.
- **`.gitignore`**: ignores `modules/auth/lambda/*.zip` (the `archive_file` artifact
  generated at plan/apply time — never committed).
- **Docs**: spec Status → Completed; CLAUDE.md + architecture.md spec tables
  updated; pre-signup Lambda added to the architecture AWS Resource Inventory.
- No previously delivered code behavior changed — the SPEC-009 guidance text was
  already aligned and required no edit.

## Verification

- `tofu fmt` clean; `tofu validate` → **Success** (graph builds with no dependency
  cycle: function → pool → invoke-permission); rendered deploy policy parses as
  valid JSON (15 statements).
- **Checkpoint (runs on live apply, not yet executed):** `deploy-infra.yml` PR plan
  shows the Lambda, exec role, log group, and the pool trigger update. After apply:
  Hosted UI signup with `bad/name!` is rejected with the readable message; a valid
  username proceeds to email verification (SPEC-009 E2E signup section). CloudWatch
  shows the invocation with no errors.

### Follow-ups / notes

- The function name pattern in the deploy policy uses a wildcard environment
  segment (`{project}-*-pre-signup`) so the single template var `project_name`
  suffices without threading `environment` into the base module.
- Lambda read actions (`GetFunctionConcurrency`, `GetRuntimeManagementConfig`,
  etc.) are granted so post-apply plan refreshes don't fail; harmless when scoped
  to the function ARN.
