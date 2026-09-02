# GitHub Actions Workflows

Every workflow in this directory, and what it is for. A count would rot — the row is the
record, so a workflow without one is a workflow nobody has described:

| File | Trigger | Purpose |
|---|---|---|
| `ci.yml` | PR → `main` | Web app: lint + format + `tsc -b` build + unit/component tests. Those steps are **scoped**: a pull request touching none of `apps/portal/**`, the root manifests, `.nvmrc` or this workflow skips them and the job costs one billed minute instead of six. The scoping is per-STEP, not a workflow-level `paths:` filter, so the job always runs and always reports — a required check by that name can never sit pending. An unreachable base runs everything. Lambdas: `ruff` + `mypy` + `pytest` + the doc, contract and feature-flag validators (separate `lambdas` job, never scoped) |
| `deploy-config.yml` | Push to `main` (paths: `config/**`, its own file, the flag validator, the configuration map and the resolver); manual dispatch | Validate the feature-flag document, then publish it to the user-space bucket — whose name it resolves from Terraform state through the same map |
| `deploy-infra.yml` | PR → `main` (paths: `infra/**`, own workflow file); push to `main` (same); manual dispatch (optional `skip_refresh` recovery input) | `tofu fmt -check` + `tofu plan` on PRs (posts plan as PR comment); `tofu plan` + `tofu apply` on merge |
| `security.yml` | PR → `main`; weekly (Mon 06:17 UTC); manual dispatch | Security scanning: Semgrep SAST, `npm audit` (runtime + full), `pip-audit`, gitleaks, Checkov, OWASP ZAP baseline. All **report-only** — see the `GATE_*` block in the workflow and `docs/security-baseline.md` (SPEC-138) |
| `deploy-lambdas.yml` | Push to `main` (paths: `lambdas/**`, the function table, the probe table, `point-lambda.sh`, `probe-cold-start.sh`, the planner); manual dispatch (optional `image_tag` **rollback** input) | Point **every** function at the fleet's container image, reconcile what was pointed by name, then invoke a sample and prove the deployed artefact starts |
| `spa-image.yml` | PR → `main` (paths: `apps/portal/**`, the root manifests, `.dockerignore`, the matrix script, both image workflows) | Builds the SPA image and runs the behaviour matrix — every response header, status and cache class, against a container started the way ECS starts it. **Before merge**, because a gate that runs after cannot block anything |
| `lambda-image.yml` | PR → `main` (paths: `lambdas/**`, `infra/**`, the matrix script and its sweep, both image workflows) | Builds the Lambda fleet's container image and runs its behaviour matrix — every function's handler module imported inside the built image, through the real runtime bootstrap. **Before merge**, for the reason `spa-image.yml` gives |
| `deploy-lambda-image.yml` | Push to `main` (**no path filter**, deliberately — the image tracks `main` exactly, or "which commit is in the registry" has no answer); manual dispatch (`image_tag` reports an existing tag rather than rebuilding it) | Builds the Lambda fleet's image, proves it with the same matrix, and pushes it to ECR tagged by commit sha. **It points nothing**, and that is a split rather than an unfinished job: all 86 functions run this image, and `deploy-lambdas.yml` is what points them at it. The two fire on the same commit, so a deploy step here would race the pointing there |
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
*variable* straight from Terraform state: `deploy-config.yml` inits the backend and runs one
`tofu output -json`, mapping output names to configuration keys through
[`.github/config-outputs.json`](../config-outputs.json). Copying a derived value into a settings
page is no longer a setup step, and doing it anyway creates a second copy that nothing reconciles.

From `infra/` after a successful `tofu apply`:

```bash
tofu output github_actions_role_arn      # → AWS_DEPLOY_ROLE_ARN
tofu output spa_origin                   # → VITE_APP_URL (see the note below)
```

### Step 2 — Populate GitHub Actions Secrets

Go to **Settings → Secrets and variables → Actions → Secrets**.

| Secret | Value source |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `tofu output github_actions_role_arn` |
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
| `VITE_APP_URL` | **No longer a Terraform input.** `variable "app_url"` is deleted and the three module blocks that consumed it take `local.spa_origin`, which Terraform builds from the subdomain and the parent domain | Its one remaining consumer is `security.yml`'s ZAP target. A stale value there does **not** fail the job — it scans a dead host and reports a clean baseline, the worst shape a security check can take. Set it to `tofu output spa_origin` |
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
`Publish Config`**, because until then they are what a revert falls back to. `Deploy App` is gone,
so `Publish Config` is the only workflow still resolving configuration from Terraform state — which
is what makes re-pointing `.github/config-outputs.json` part of this retirement, not a follow-up. The
queue URLs are wired straight from each module's output onto the API function by Terraform, with no
repository variable and no build env in between.

### Step 4 — Trigger the first app deploy

Push a commit to `main` (or merge a PR). `deploy-spa-image.yml` builds the SPA image, proves it
against the container matrix, pushes it to ECR under the commit sha, and **points the service at
the new revision** — Terraform ignores `task_definition`, so a pipeline that only registers a
revision leaves the old task running.

The app loads at `spa_origin` once the rolling deployment finishes. There is no invalidation step
and no sync: the image IS the file set, so there is no reconciliation and no orphan class.

### Step 5 — Test the infra workflow

Open a PR that changes a file under `infra/`. The `deploy-infra.yml` `plan` job will run `tofu fmt -check -recursive` (fails the job if any `.tf` file is unformatted — run `tofu fmt -recursive` in `infra/` to fix), then `tofu plan`, posting the plan output as a comment on the PR. Merge the PR to trigger `plan` → `apply` automatically.

> To enforce this as a merge gate, mark the `deploy-infra.yml` `plan` job a **required status check** under **Settings → Branches → Branch protection rules** for `main`.

---

## Variable Derivation

Several workflow values are derived rather than stored as separate GitHub variables:

- `VITE_AWS_REGION` is set to `${{ vars.AWS_REGION }}` in the build step — no separate variable needed.
- `TF_VAR_aws_region` is set to `${{ vars.AWS_REGION }}` in the plan/apply steps — no separate variable needed.
- The three Cognito values and the two bucket names reach `/config.json` through the **container
  entrypoint**, from the ECS task definition that root's `local.spa_runtime_config` renders. There is
  nothing to populate. `.github/scripts/resolve-config.sh` still reads the same Terraform outputs for
  `Publish Config`, and still refuses an absent or empty one by name.
- `VITE_IAM_ROLE_ARN` and `VITE_COGNITO_IDENTITY_POOL_ID` have both been **removed**. The first went when the Identity Pool took over credential issuance; the second went with the pool itself, once the browser stopped making AWS calls. The app handles neither a role ARN nor a pool id.
- `TF_VAR_state_bucket` and `TF_VAR_state_lock_table` are stored as **secrets** (not variables) because they are used both as OpenTofu input variables (scoping IAM permissions in `iam.tf`) and as backend configuration passed to `tofu init`.

### `deploy-lambdas.yml` (SPEC-012)

Terraform owns the Lambda *infrastructure* (function, execution role, log group, Cognito trigger); this workflow owns **which image each function runs**. On a push to `main` touching `lambdas/**` — or a manual dispatch, which additionally takes an `image_tag` to roll back — it calls `aws lambda update-function-code --image-uri` on every function. The function declares `ignore_changes = [image_uri]`, so a later `tofu apply` never reverts a CI deploy, and equally never moves the fleet forward: this workflow is the only thing that does.

- **Prerequisite:** the IaC must be applied first, and this commit's image must be in the registry — `deploy-lambda-image.yml` builds it on the same push, and both this workflow and `deploy-infra.yml`'s apply wait for the tag.
- **Reuses** the existing `AWS_DEPLOY_ROLE_ARN` secret and `AWS_REGION` variable — no new required config.
- **Resource names are derived**, not stored: `{project}-{env}-{name}` for the function and `{project}-{env}-lambda` for the registry. `project`/`env` come from optional Variables `TF_VAR_project_name` / `TF_VAR_environment` (defaults `dat` / `prod`, matching `infra/variables.tf`). Set those Variables only if you overrode the Terraform defaults.
- **Adding a lambda:** create `lambdas/<name>/<module>.py`, add a `docker-lambda` module call under the owning Terraform module, and that is the whole registration — CI derives the fleet from those module calls, and no list under `.github/` names functions any more. A new **module** also needs a `function_names` output and a line in the root's `lambda_deployed_names`; a new **plane** additionally needs an invoke grant and a row in `.github/lambda-probes.json` — see [`lambdas/info/deployment.md`](../../lambdas/info/deployment.md).
- **The layer table is dead machinery awaiting its own PR.** `.github/lambda-layers.json` and `build-layer.sh` still exist and nothing deploys through them: a container function has no layers, and `point-lambda.sh` refuses a non-`Image` packaging by name. The table is still read by the image assembler, which is what its own retirement has to solve.
- **EVERY function is deployed, every run.** Narrowing to a diff was right while each function carried its own zip and its own layer ARNs; with one image for the whole fleet, "which functions changed" has no answer, and a function left un-pointed runs an older image and reports a stale build stamp while working perfectly. The `pointed` job reconciles by NAME rather than by count, because the names say which functions are running last week's image.
- **The deployed artefact is proved to start.** After pointing, a `probe` job invokes one function per plane and each standalone and fails on an `errorType` under `Runtime.`, on `Status: error` in the log, or on no anchored `^REPORT RequestId` line. That combination took three designs — the reasoning is in `lambdas/info/deployment.md`, and it matters because two simpler rules each passed a real init failure. Its population is derived from the deploy role's own invoke grants (`lambdas/test_cold_start_probe.py`), not hand-maintained.
- **Why shards and not a matrix:** the deploy is sharded across six jobs because GitHub bills every job a rounded-up minute and one job per function was 46% of this repo's Actions spend. A `strategy.matrix` creates one job per entry and cannot express "these fifteen in one job", so the fleet has to be data the shard reads — `lambdas/fleet.py --plan` emits it, and a test holds the union of the shards equal to the fleet.
