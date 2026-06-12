# Completed Spec - Pre-Signup Username Validation (Cognito Trigger Lambda)

## What was completed from this spec?

Usernames are now enforced server-side at signup. A Cognito **pre-signup** trigger
Lambda rejects any registration whose username falls outside the authoritative
rule, before the user (and therefore their S3 prefix / `username` principal tag)
is ever created. Valid usernames pass through untouched — the normal email
verification flow (SPEC-009) proceeds unchanged.

Code ownership is split: **Terraform owns the Lambda infrastructure** (function,
execution role, log group, Cognito trigger) and bootstraps the function with a
placeholder; **GitHub Actions owns the code** — `deploy-lambdas.yml` builds the
Python package, uploads it to a shared artifacts bucket, and runs
`update-function-code`. Live verification runs on the next `deploy-infra.yml`
apply followed by a `deploy-lambdas.yml` run (see Checkpoint).

**FR-001 — Validation rule:**
- One authoritative pattern, `^[a-zA-Z0-9._@-]{3,64}$`, defined once in the Lambda
  and quoted verbatim in a code comment + the spec. S3-prefix-safe and IAM-tag-safe.
- The SPEC-009 landing-page guidance text already matched this rule exactly
  ([`LandingPage.tsx`](../../apps/portal/src/routes/LandingPage.tsx)), so no app
  change was needed; verified during this work.
- Rejection raises the user-readable message
  `Username must be 3-64 characters using only letters, numbers, . _ @ -`.

**FR-002 — Pre-signup Lambda (Python, CI-deployed):**
- **`lambdas/pre-signup/pre_signup.py`** — pure-stdlib Python handler
  (`pre_signup.handler`); raises on mismatch, returns `event` unchanged on success.
- **`lambdas/requirements.txt`** — shared deps for all lambdas (empty for pre-signup).
- **`infra/modules/auth/lambda.tf`** — `python3.12` function bootstrapped from an
  inline `archive_file` placeholder with `lifecycle.ignore_changes = [filename,
  source_code_hash]` (CI owns the code), logs-only execution role, explicit
  `aws_cloudwatch_log_group` (14-day retention), `aws_lambda_permission` for the
  pool, and a `time_sleep` IAM-propagation guard.
- **`infra/modules/auth/policies/`** — exec-role **trust** and **permissions** as
  `.tftpl` templates (rendered with `templatefile()`), replacing the earlier inline
  `jsonencode` blocks (per the request that all IAM trust/permission policies be
  template files, matching the `base`/`data` convention).
- **`infra/modules/auth/cognito.tf`** — `lambda_config.pre_sign_up` wired to the
  function ARN.

**Lambda artifacts bucket + deploy workflow:**
- **`infra/modules/lambda-artifacts/`** — new module: a private S3 bucket
  `{project}-lambda-artifacts-{accountId}` (public access blocked, SSE-S3,
  BucketOwnerEnforced, 30-day expiry lifecycle, `time_sleep` guard, `depends_on =
  [module.base]`). Wired in root `main.tf`; name/ARN computed in root locals and
  passed both to this module (creation) and `base` (policy scoping) — the same
  cycle-free string-ARN pattern used for the user-space bucket.
- **`.github/workflows/deploy-lambdas.yml`** — on push to `main` touching
  `lambdas/**` (or manual dispatch): a matrix over functions installs
  `requirements.txt`, zips the package, uploads to `s3://<bucket>/<name>/<sha>.zip`,
  and runs `update-function-code --publish` + `wait function-updated`. Reuses the
  existing `AWS_DEPLOY_ROLE_ARN` secret / `AWS_REGION` var; resource names derived
  deterministically (no new required config). Documented in
  `.github/workflows/README.md`.

**FR-003 — Deploy role permissions:**
- **`infra/modules/base/policies/github-actions-deploy.json.tftpl`** extended with
  scoped statements: `PreSignupLambdaManage` (lambda CRUD/tag/permission +
  `UpdateFunctionCode`/`PublishVersion` + read actions), `PreSignupLambdaExecRole`
  (IAM self-manage of the exec role incl. `iam:PassRole`), `PreSignupLambdaLogs`
  (log group create/retention/tag), and `S3LambdaArtifactsBucketManage` (`s3:*` on
  the artifacts bucket). `cognito-idp:UpdateUserPool` (used to attach the trigger)
  was already granted. `project_name` + `lambda_artifacts_bucket_arn` are now passed
  into the `templatefile()` render.

## What has changed?

This spec was first implemented in Node.js with Terraform packaging the code via
`archive_file` (committed in `99d5c44`), then **reworked** per follow-up requests:

- **Language**: Node.js `index.mjs` → **Python** `pre_signup.py`. Runtime
  `nodejs20.x` → `python3.12`.
- **Code location**: `infra/modules/auth/lambda/` → repo-root **`lambdas/<name>/`**
  with a shared `lambdas/requirements.txt`.
- **Deploy model**: Terraform `archive_file` packaging → **CI builds + deploys**
  (`deploy-lambdas.yml`) via an S3 **artifacts bucket** (`modules/lambda-artifacts/`);
  Terraform bootstraps a placeholder and ignores code changes.
- **IAM policies**: inline `jsonencode` exec-role trust/permissions → **`.tftpl`
  template files** under `modules/auth/policies/`.
- **Deploy role**: added artifacts-bucket `s3:*`, `lambda:UpdateFunctionCode`/
  `PublishVersion`.
- **Outputs**: added `lambda_artifacts_bucket_name` and `pre_signup_function_name`.
- **`.gitignore`**: ignores `infra/modules/*/build/` (placeholder zip output).
- **Docs**: spec body updated to the Python/CI design; CLAUDE.md + architecture.md
  tables; architecture Resource Inventory gained the Python Lambda + artifacts
  bucket rows; workflows README documents `deploy-lambdas.yml`.
- No previously delivered code behavior changed — the SPEC-009 guidance text was
  already aligned and required no edit.

## Verification

- `tofu fmt` clean; `tofu validate` → **Success** (graph builds with no dependency
  cycle); rendered deploy policy parses as valid JSON (16 statements); both auth
  `.tftpl` policies parse as valid JSON; `deploy-lambdas.yml` is valid YAML.
- Python handler unit-checked locally: valid usernames (`alice`, `a.b_c@d-e`,
  64-char) pass through unchanged; invalid (`ab`, `bad/name!`, 65-char, spaces,
  `=`/`,`, empty) all raise the readable message.
- **Checkpoint (runs on live deploy, not yet executed):** `deploy-infra.yml` PR plan
  shows the placeholder Lambda, exec role, log group, artifacts bucket, and pool
  trigger update. After infra apply + a `deploy-lambdas.yml` run: Hosted UI signup
  with `bad/name!` is rejected with the readable message; a valid username proceeds
  to email verification (SPEC-009 E2E signup section); CloudWatch shows the
  invocation with no errors.

### Follow-ups / notes

- **Ordering on first deploy:** the function and artifacts bucket must exist
  (`deploy-infra.yml`) before `deploy-lambdas.yml` can deploy code. The placeholder
  ensures the function is valid in the interim and surfaces a clear error if invoked
  before its first code deploy.
- **Lambda architecture:** the function uses the default `x86_64`, matching the
  `ubuntu-latest` build runner — relevant only once a future lambda needs native
  wheels.
- Lambda read actions (`GetFunctionConcurrency`, `GetRuntimeManagementConfig`, etc.)
  are granted so post-apply plan refreshes don't fail; harmless when scoped to the
  function ARN.
