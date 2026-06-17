# GitHub Actions Workflows

This directory contains four workflows:

| File | Trigger | Purpose |
|---|---|---|
| `ci.yml` | Push to any branch; PR → `main` | Web app: lint + unit/component tests + production build. Lambdas: `ruff` lint + `pytest` (separate `lambdas` job) |
| `deploy-app.yml` | Push to `main` | Build SPA with env vars, sync to S3, invalidate CloudFront |
| `deploy-infra.yml` | PR → `main` (paths: `infra/**`); push to `main` (paths: `infra/**`) | `tofu fmt -check` + `tofu plan` on PRs (posts plan as PR comment); `tofu plan` + `tofu apply` on merge |
| `deploy-lambdas.yml` | Push to `main` (paths: `lambdas/**`); manual dispatch | Build each Python Lambda package, upload to the artifacts bucket, `update-function-code` (SPEC-012) |

All deploy workflows authenticate to AWS via GitHub OIDC — no long-lived credentials are stored.

---

## First-Time Setup

### Prerequisites

1. SPEC-003 IaC has been applied (`tofu apply` completed successfully against a real AWS account).
2. The bootstrap state bucket and DynamoDB lock table exist (see `infra/bootstrap/README.md`).

### Step 1 — Capture IaC outputs

From `infra/` after a successful `tofu apply`:

```bash
tofu output github_actions_role_arn      # → AWS_DEPLOY_ROLE_ARN
tofu output s3_static_assets_bucket_name # → S3_STATIC_BUCKET
tofu output cloudfront_distribution_id   # → CLOUDFRONT_DISTRIBUTION_ID
tofu output cloudfront_domain            # → VITE_APP_URL
tofu output aws_region                   # → AWS_REGION
```

### Step 2 — Populate GitHub Actions Secrets

Go to **Settings → Secrets and variables → Actions → Secrets**.

| Secret | Value source |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `tofu output github_actions_role_arn` |
| `S3_STATIC_BUCKET` | `tofu output s3_static_assets_bucket_name` |
| `CLOUDFRONT_DISTRIBUTION_ID` | `tofu output cloudfront_distribution_id` |
| `TF_VAR_state_bucket` | Name of your bootstrap S3 state bucket |
| `TF_VAR_state_lock_table` | Name of your bootstrap DynamoDB lock table |

### Step 3 — Populate GitHub Actions Variables

Go to **Settings → Secrets and variables → Actions → Variables**.

| Variable | Value source | Notes |
|---|---|---|
| `AWS_REGION` | e.g. `us-east-1` | Must match region of all provisioned resources |
| `VITE_APP_URL` | `tofu output cloudfront_domain` | Set after first deploy; use `https://` URL |
| `TF_VAR_github_repo` | `owner/repo-name` | Scopes OIDC trust; must match exactly |
| `VITE_COGNITO_USER_POOL_ID` | `tofu output cognito_user_pool_id` | Injected into the build by `deploy-app.yml` (SPEC-007) |
| `VITE_COGNITO_USER_POOL_CLIENT_ID` | `tofu output cognito_user_pool_client_id` | Injected into the build by `deploy-app.yml` (SPEC-007) |
| `VITE_COGNITO_DOMAIN` | `tofu output cognito_domain` | Injected into the build by `deploy-app.yml` (SPEC-007) |
| `VITE_COGNITO_IDENTITY_POOL_ID` | `tofu output cognito_identity_pool_id` | Injected into the build by `deploy-app.yml` (SPEC-011); without it the deployed app gets no AWS credentials |
| `VITE_S3_USER_SPACE_BUCKET` | `tofu output s3_user_space_bucket_name` | Bucket provisioned in SPEC-010; injected into the build starting SPEC-013 (file browser switchover) |
| `VITE_ATHENA_WORKGROUP` | `tofu output athena_workgroup_name` | Workgroup provisioned in SPEC-032; injected into the build starting SPEC-034 (query workspace). No separate results-bucket variable — the app derives `{username}/athenaresults/` from `VITE_S3_USER_SPACE_BUCKET` |

> **Chicken-and-egg note for `VITE_APP_URL`:** On the very first deploy, the CloudFront domain isn't known yet. Set `VITE_APP_URL` to a placeholder (or empty string), let the first deploy complete, then update the variable to the value from `tofu output cloudfront_domain` and redeploy.

### Step 4 — Trigger the first app deploy

Push a commit to `main` (or merge a PR). The `deploy-app.yml` workflow will:
1. Build the SPA with the injected env vars
2. Sync `apps/portal/dist/` to the static assets S3 bucket
3. Invalidate the CloudFront distribution

The app should load at the CloudFront domain once the invalidation completes (typically under 60 seconds).

### Step 5 — Test the infra workflow

Open a PR that changes a file under `infra/`. The `deploy-infra.yml` `plan` job will run `tofu fmt -check -recursive` (fails the job if any `.tf` file is unformatted — run `tofu fmt -recursive` in `infra/` to fix), then `tofu plan`, posting the plan output as a comment on the PR. Merge the PR to trigger `plan` → `apply` automatically.

> To enforce this as a merge gate, mark the `deploy-infra.yml` `plan` job a **required status check** under **Settings → Branches → Branch protection rules** for `main`.

---

## Variable Derivation

Several workflow values are derived rather than stored as separate GitHub variables:

- `VITE_AWS_REGION` is set to `${{ vars.AWS_REGION }}` in the build step — no separate variable needed.
- `TF_VAR_aws_region` is set to `${{ vars.AWS_REGION }}` in the plan/apply steps — no separate variable needed.
- `TF_VAR_app_url` is set to `${{ vars.VITE_APP_URL }}` — declared in `infra/variables.tf` for Cognito OAuth callback URLs when auth IaC is added.
- `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_USER_POOL_CLIENT_ID`, and `VITE_COGNITO_DOMAIN` are injected into the build by `deploy-app.yml` from GitHub Actions **variables** (SPEC-007). Populate them from `tofu output` (see the variables table above) before the next app deploy, or the deployed bundle ships without auth config.
- `VITE_S3_USER_SPACE_BUCKET` is provisioned by SPEC-010 (`tofu output s3_user_space_bucket_name`) and is injected into the `deploy-app.yml` build as of SPEC-013 (the file browser switchover) — the deployed `/files` page reads it to scope the browser to the user-space bucket, so it must be set as a GitHub Actions **variable** or the deployed app shows a configuration error. `VITE_S3_SHARED_SPACE_BUCKET` remains a future spec.
- `VITE_IAM_ROLE_ARN` has been **removed** (SPEC-011): the Cognito Identity Pool issues scoped credentials and the app never handles a role ARN. `VITE_COGNITO_IDENTITY_POOL_ID` replaces it and is injected into the `deploy-app.yml` build from a GitHub Actions **variable**.
- `TF_VAR_state_bucket` and `TF_VAR_state_lock_table` are stored as **secrets** (not variables) because they are used both as OpenTofu input variables (scoping IAM permissions in `iam.tf`) and as backend configuration passed to `tofu init`.

### `deploy-lambdas.yml` (SPEC-012)

Terraform owns the Lambda *infrastructure* (function, execution role, log group, Cognito trigger) and bootstraps the function with a placeholder; this workflow owns the *code*. On a push to `main` touching `lambdas/**` (or manual dispatch) it builds each function's Python package, uploads it to the artifacts bucket, and runs `aws lambda update-function-code`. The function declares `ignore_changes` on its code, so a later `tofu apply` never reverts a CI deploy.

- **Prerequisite:** the IaC must be applied first — the function and the `*-lambda-artifacts-*` bucket must exist before this workflow can deploy to them. New lambdas land via `deploy-infra.yml`, then their code via this workflow.
- **Reuses** the existing `AWS_DEPLOY_ROLE_ARN` secret and `AWS_REGION` variable — no new required config.
- **Resource names are derived**, not stored: `{project}-{env}-{name}` for the function and `{project}-lambda-artifacts-{accountId}` for the bucket. `accountId` comes from `sts get-caller-identity`; `project`/`env` come from optional Variables `TF_VAR_project_name` / `TF_VAR_environment` (defaults `dat` / `prod`, matching `infra/variables.tf`). Set those Variables only if you overrode the Terraform defaults.
- **Adding a lambda:** create `lambdas/<name>/<module>.py`, add the function infra under the owning Terraform module, then add a `{ name: <name> }` entry to the `matrix.lambda` list in this workflow.
