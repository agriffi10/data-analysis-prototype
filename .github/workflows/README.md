# GitHub Actions Workflows

This directory contains five workflows:

| File | Trigger | Purpose |
|---|---|---|
| `ci.yml` | Push to any branch; PR → `main` | Web app: lint + unit/component tests + production build. Lambdas: `ruff` lint + `pytest` (separate `lambdas` job) |
| `deploy-app.yml` | Push to `main` | Build SPA with env vars, sync to S3, invalidate CloudFront |
| `deploy-infra.yml` | PR → `main` (paths: `infra/**`, own workflow file); push to `main` (same); manual dispatch (optional `skip_refresh` recovery input) | `tofu fmt -check` + `tofu plan` on PRs (posts plan as PR comment); `tofu plan` + `tofu apply` on merge |
| `security.yml` | PR → `main`; weekly (Mon 06:17 UTC); manual dispatch | Security scanning: Semgrep SAST, `npm audit` (runtime + full), `pip-audit`, gitleaks, Checkov, OWASP ZAP baseline. All **report-only** — see the `GATE_*` block in the workflow and `docs/security-baseline.md` (SPEC-138) |
| `deploy-lambdas.yml` | Push to `main` (paths: `lambdas/**`, the two `.github/lambda-*.json` tables, the two deploy scripts); manual dispatch | Build each Python Lambda package, upload to the artifacts bucket, `update-function-code` (SPEC-012) |
| `spa-image.yml` | PR → `main` (paths: `apps/portal/**`, the root manifests, `.dockerignore`, the matrix script, both image workflows) | Builds the SPA image and runs the behaviour matrix — every response header, status and cache class, against a container started the way ECS starts it. **Before merge**, because a gate that runs after cannot block anything |
| `deploy-spa-image.yml` | Push to `main` (**no path filter**, deliberately — the container tracks `main` exactly as the bundle does, or "which commit is in production" has no answer); manual dispatch (`image_tag` re-points at an existing image without rebuilding) | Build → matrix → push to ECR tagged by commit sha → register a task-definition revision → point the service → wait → **assert it settled on this run's revision and image**. `update-service` returns before anything runs, so waiting is what makes a bad image able to fail a deploy |

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

> **These variables no longer reach the deployed bundle.** `deploy-app.yml` renders them into
> `/config.json`, which the SPA fetches at startup — that is what lets one artifact be promoted
> between environments instead of rebuilt. A variable still feeds the build as well, but only as the
> **dev fallback**. The practical consequence is unchanged: an unset variable renders as an empty
> string, and a required one empty makes the deploy **refuse to publish** rather than ship a portal
> that shows every user a boot failure. Full list and classification:
> `apps/portal/.env.example`.

| Variable | Value source | Notes |
|---|---|---|
| `AWS_REGION` | e.g. `us-east-1` | Must match region of all provisioned resources |
| `VITE_APP_URL` | `tofu output cloudfront_domain` | Set after first deploy; use `https://` URL |
| `TF_VAR_github_repo` | `owner/repo-name` | Scopes OIDC trust; must match exactly |
| `VITE_COGNITO_USER_POOL_ID` | `tofu output cognito_user_pool_id` | Injected into the build by `deploy-app.yml` (SPEC-007) |
| `VITE_COGNITO_USER_POOL_CLIENT_ID` | `tofu output cognito_user_pool_client_id` | Injected into the build by `deploy-app.yml` (SPEC-007) |
| `VITE_COGNITO_DOMAIN` | `tofu output cognito_domain` | Injected into the build by `deploy-app.yml` (SPEC-007) |
| `VITE_COGNITO_IDENTITY_POOL_ID` | `tofu output cognito_identity_pool_id` | Injected into the build by `deploy-app.yml` (SPEC-011); without it the deployed app gets no AWS credentials |
| `VITE_S3_USER_SPACE_BUCKET` | `tofu output s3_user_space_bucket_name` | Bucket provisioned in SPEC-010; read by the file browser starting SPEC-013. Required — an unset one fails the deploy at the render step |
| `VITE_ATHENA_WORKGROUP` | `tofu output athena_workgroup_name` | Workgroup provisioned in SPEC-032; read by the query workspace starting SPEC-034. No separate results-bucket variable — the app derives `{username}/athenaresults/` from `VITE_S3_USER_SPACE_BUCKET` |
| `API_BASE_URL` | *(not yet provisioned)* | The one runtime-configuration key with **no** `VITE_` variable — nothing in the browser reads it until the API lands (SPEC-197), so it has no dev fallback. Leave it unset until then; it renders as an empty string, which reads as absent. |

The table above is the set an operator populates first. The queue URLs (`VITE_*_QUEUE_URL`) are
listed per control plane in `apps/portal/.env.example`, each with its `tofu output`; an unset one
disables that one feature rather than the app.

> **Chicken-and-egg note for `VITE_APP_URL`:** On the very first deploy, the CloudFront domain isn't known yet. Set `VITE_APP_URL` to a placeholder (or empty string), let the first deploy complete, then update the variable to the value from `tofu output cloudfront_domain` and redeploy.

### Step 4 — Trigger the first app deploy

Push a commit to `main` (or merge a PR). The `deploy-app.yml` workflow will:
1. Render `/config.json` and build the SPA
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
- `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_USER_POOL_CLIENT_ID` and `VITE_COGNITO_DOMAIN` are rendered into `/config.json` by `deploy-app.yml` from GitHub Actions **variables** (SPEC-007). Populate them from `tofu output` (see the variables table above) before the next app deploy: all three are required, so the deploy refuses to publish a document without them.
- `VITE_S3_USER_SPACE_BUCKET` is provisioned by SPEC-010 (`tofu output s3_user_space_bucket_name`) and scopes the file browser to the user-space bucket. It is required, so an unset one fails the deploy at the render step rather than reaching a user. `VITE_S3_SHARED_SPACE_BUCKET` remains a future spec.
- `VITE_IAM_ROLE_ARN` has been **removed** (SPEC-011): the Cognito Identity Pool issues scoped credentials and the app never handles a role ARN. `VITE_COGNITO_IDENTITY_POOL_ID` replaces it.
- `TF_VAR_state_bucket` and `TF_VAR_state_lock_table` are stored as **secrets** (not variables) because they are used both as OpenTofu input variables (scoping IAM permissions in `iam.tf`) and as backend configuration passed to `tofu init`.

### `deploy-lambdas.yml` (SPEC-012)

Terraform owns the Lambda *infrastructure* (function, execution role, log group, Cognito trigger) and bootstraps the function with a placeholder; this workflow owns the *code*. On a push to `main` touching `lambdas/**` (or manual dispatch) it builds each function's Python package, uploads it to the artifacts bucket, and runs `aws lambda update-function-code`. The function declares `ignore_changes` on its code, so a later `tofu apply` never reverts a CI deploy.

- **Prerequisite:** the IaC must be applied first — the function and the `*-lambda-artifacts-*` bucket must exist before this workflow can deploy to them. New lambdas land via `deploy-infra.yml`, then their code via this workflow.
- **Reuses** the existing `AWS_DEPLOY_ROLE_ARN` secret and `AWS_REGION` variable — no new required config.
- **Resource names are derived**, not stored: `{project}-{env}-{name}` for the function and `{project}-lambda-artifacts-{accountId}` for the bucket. `accountId` comes from `sts get-caller-identity`; `project`/`env` come from optional Variables `TF_VAR_project_name` / `TF_VAR_environment` (defaults `dat` / `prod`, matching `infra/variables.tf`). Set those Variables only if you overrode the Terraform defaults.
- **Adding a lambda:** create `lambdas/<name>/<module>.py`, add the function infra under the owning Terraform module, then add a `{"name": "<name>", "layers": [...]}` entry to **`.github/lambda-functions.json`**. `layers` names the layer flags the function attaches, in attach order — `lambdas/test_deploy_matrix.py` fails if it omits one the module imports, if the order disagrees with `.github/lambda-layers.json`, or if it is empty.
- **Adding a layer:** add an entry to **`.github/lambda-layers.json`** naming one of the three build shapes (`requirements`, `package`, or `sourceDir` + `modules`), then reference its `flag` from the functions that attach it. A layer nothing attaches, or a function attaching a layer that does not exist, both fail the suite.
- **Only what changed is deployed.** A `plan` job diffs the push and decides which functions and which layers the run needs (`.github/scripts/plan_deploy.py`, tested by `lambdas/test_plan_deploy.py`). A change to one function deploys one function; a change to a *layer* deploys every function attaching it, because a republished layer is a new ARN and functions pin layers by ARN. A change to `deploy-lambdas.yml`, either deploy script, the planner, or `lambdas/requirements.txt` deploys **everything** — as does any push whose diff cannot be computed. Editing the two tables is narrowed by diffing them, so adding a function deploys that function alone.
- **Unchanged layers are NOT republished.** `publish-layer-version` mints a new version on every call, so republishing everything each run is what used to force all 73 functions to be re-pointed. Unchanged layers now resolve to the version already published. They are still *built*, because the combined 250 MB per-function size guard needs their unzipped size.
- **Why JSON and not a matrix:** the deploy is sharded across six jobs because GitHub bills every job a rounded-up minute and 73 twenty-nine-second jobs were 46% of this repo's Actions spend. A `strategy.matrix` creates one job per entry and cannot express "these twelve in one job", so the table has to be data the shard reads.
