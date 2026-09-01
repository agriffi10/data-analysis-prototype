# GitHub Actions Workflows

Every workflow in this directory, and what it is for. A count would rot — the row is the
record, so a workflow without one is a workflow nobody has described:

| File | Trigger | Purpose |
|---|---|---|
| `ci.yml` | PR → `main` | Web app: lint + format + `tsc -b` build + unit/component tests. Those steps are **scoped**: a pull request touching none of `apps/portal/**`, the root manifests, `.nvmrc` or this workflow skips them and the job costs one billed minute instead of six. The scoping is per-STEP, not a workflow-level `paths:` filter, so the job always runs and always reports — a required check by that name can never sit pending. An unreachable base runs everything. Lambdas: `ruff` + `mypy` + `pytest` + the doc, contract and feature-flag validators (separate `lambdas` job, never scoped) |
| `deploy-app.yml` | Push to `main` | Resolve the configuration from Terraform state, build the SPA, render `/config.json`, sync to S3, invalidate CloudFront. The derived values are read by `tofu output -json` through [`config-outputs.json`](../config-outputs.json); only the genuine inputs are still repository variables |
| `deploy-config.yml` | Push to `main` (paths: `config/**`, its own file, the flag validator, the configuration map and the resolver) | Validate the feature-flag document, then publish it to the user-space bucket — whose name it resolves from Terraform state through the same map |
| `deploy-infra.yml` | PR → `main` (paths: `infra/**`, own workflow file); push to `main` (same); manual dispatch (optional `skip_refresh` recovery input) | `tofu fmt -check` + `tofu plan` on PRs (posts plan as PR comment); `tofu plan` + `tofu apply` on merge |
| `security.yml` | PR → `main`; weekly (Mon 06:17 UTC); manual dispatch | Security scanning: Semgrep SAST, `npm audit` (runtime + full), `pip-audit`, gitleaks, Checkov, OWASP ZAP baseline. All **report-only** — see the `GATE_*` block in the workflow and `docs/security-baseline.md` (SPEC-138) |
| `deploy-lambdas.yml` | Push to `main` (paths: `lambdas/**`, the two `.github/lambda-*.json` tables, the two deploy scripts); manual dispatch | Build each Python Lambda package, upload to the artifacts bucket, `update-function-code` (SPEC-012) |
| `spa-image.yml` | PR → `main` (paths: `apps/portal/**`, the root manifests, `.dockerignore`, the matrix script, both image workflows) | Builds the SPA image and runs the behaviour matrix — every response header, status and cache class, against a container started the way ECS starts it. **Before merge**, because a gate that runs after cannot block anything |
| `lambda-image.yml` | PR → `main` | Builds the Lambda fleet's container image and proves it before merge (SPEC-212) |
| `deploy-lambda-image.yml` | Push to `main` | Builds the Lambda image and pushes it to ECR by commit sha (SPEC-212) |
| `backfill-ever-active.yml` | Manual dispatch only | One-shot backfill of the durable `everActive` field (SPEC-205) |
| `deploy-spa-image.yml` | Push to `main` (**no path filter**, deliberately — the container tracks `main` exactly as the bundle does, or "which commit is in production" has no answer); manual dispatch (`image_tag` re-points at an existing image without rebuilding) | Build → matrix → push to ECR tagged by commit sha → register a task-definition revision → point the service → wait → **assert it settled on this run's revision and image**. `update-service` returns before anything runs, so waiting is what makes a bad image able to fail a deploy |

All deploy workflows authenticate to AWS via GitHub OIDC — no long-lived credentials are stored.

---

## First-Time Setup

### Prerequisites

1. SPEC-003 IaC has been applied (`tofu apply` completed successfully against a real AWS account).
2. The bootstrap state bucket and DynamoDB lock table exist (see `infra/bootstrap/README.md`).

### Step 1 — Capture IaC outputs

**Only the secrets below are captured by hand now.** The deploy workflows read every derived
*variable* straight from Terraform state: `deploy-app.yml` and `deploy-config.yml` init the same
backend and run one `tofu output -json`, mapping output names to configuration keys through
[`.github/config-outputs.json`](../config-outputs.json). Copying a derived value into a settings
page is no longer a setup step, and doing it anyway creates a second copy that nothing reconciles.

From `infra/` after a successful `tofu apply`:

```bash
tofu output github_actions_role_arn      # → AWS_DEPLOY_ROLE_ARN
tofu output s3_static_assets_bucket_name # → S3_STATIC_BUCKET
tofu output cloudfront_distribution_id   # → CLOUDFRONT_DISTRIBUTION_ID
tofu output cloudfront_domain            # → VITE_APP_URL (see the note below — it is an INPUT)
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

> **Every variable here is an INPUT — something Terraform is *given*, not something it computes.**
> That is the whole test for whether a value belongs on this page. A derived value (a bucket name,
> a queue URL, the API's origin, the Cognito identifiers) is read from state by the deploy, so a
> variable holding one is a second copy that goes stale silently. An input cannot be read that way,
> because it cannot be read from the thing it configures.
>
> An unset variable interpolates to the **empty string**, which satisfies a required Terraform
> variable *and* overrides its default — so the guard is a `validation` block or an explicit
> `|| 'default'` in the workflow, never the absence of a default.

| Variable | Why it is an input | Notes |
|---|---|---|
| `AWS_REGION` | Names where the state lives, so it is needed to assume the role and read state **before** any output can be resolved | Must match the region of all provisioned resources |
| `VITE_APP_URL` | Feeds `TF_VAR_app_url`, from which Cognito's callback and logout lists are built — Terraform consumes it | Use the `https://` origin. `deploy-app.yml` refuses to deploy if it disagrees with the resolved `appUrl`, because that divergence is a broken sign-in with nothing else red |
| `VITE_ENVIRONMENT` | Which feature-flag block this deployment resolves; no resource can tell you which environment it is | Unset ships a bundle that ignores every per-environment override while looking healthy |
| `VITE_MAX_UPLOAD_BYTES` | A policy number, not a resource attribute | Also feeds `TF_VAR_max_upload_bytes`, so the container and the bundle agree |
| `TF_VAR_github_repo` | Scopes the OIDC trust policy | `owner/repo-name`; must match exactly |
| `TF_VAR_parent_domain`, `TF_VAR_spa_subdomain`, `TF_VAR_api_subdomain`, `TF_VAR_route53_zone_id` | The names and the zone you chose | Terraform builds the origins from them |
| `TF_VAR_spa_desired_count`, `TF_VAR_spa_image_tag` | Deployment knobs | Both carry `validation` blocks and a `|| 'default'` in the workflow |
| `TF_VAR_verification_principal_arns` | Principals you nominate | **Unset by design.** Empty (the default) means the verification role is not created; every reference supplies `|| '[]'` |
| `TF_VAR_project_name`, `TF_VAR_environment` | The resource-name prefix and the environment segment | **Unset by design.** Every reference supplies `|| 'dat'` / `|| 'prod'`; set them only if this deployment does not use the defaults |

That table is the whole set of `vars.*` any workflow reads — **fourteen names, of which eleven are
actually set**; the last three rows are deliberately absent, each with an explicit `||` fallback at
every reference. **A variable with no reason in the middle column should not exist.**

**Sixteen retired names are still set and are waiting to be deleted. This is an outstanding action,
not a completed one.** Six were retired by the move to Terraform state: `API_BASE_URL`, the three
`VITE_COGNITO_*` values, and the two `VITE_S3_*` bucket names. Ten more had already stopped being
read when the browser's control-plane enqueues moved behind the API: the eight queue URLs,
`VITE_ATHENA_WORKGROUP` and `VITE_COGNITO_IDENTITY_POOL_ID`. The list and the ordering are in
[`docs/testing/owed.md`](../../docs/testing/owed.md) — **delete them only after a green post-merge
`Deploy App` and `Publish Config`**, because until then they are what a revert falls back to. The
queue URLs are wired straight from each module's output onto the API function by Terraform, with no
repository variable and no build env in between.

> **Chicken-and-egg note for `VITE_APP_URL`:** on the very first deploy the CloudFront domain is not
> known yet. Set it to a placeholder (or empty), let the first deploy complete, then set it to
> `tofu output cloudfront_domain` and redeploy. The agreement check in `deploy-app.yml` skips an
> empty value for exactly this reason, and enforces it once you set one.

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
- The three Cognito values and the two bucket names are rendered into `/config.json` by
  `deploy-app.yml` from **Terraform outputs**, resolved by `.github/scripts/resolve-config.sh`.
  There is nothing to populate: an absent or empty output fails the deploy, naming both the
  configuration key and the output it came from.
- `VITE_IAM_ROLE_ARN` and `VITE_COGNITO_IDENTITY_POOL_ID` have both been **removed**. The first went when the Identity Pool took over credential issuance; the second went with the pool itself, once the browser stopped making AWS calls. The app handles neither a role ARN nor a pool id.
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
