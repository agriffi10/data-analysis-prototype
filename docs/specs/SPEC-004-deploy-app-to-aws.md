# Spec: Deploy App to AWS — GitHub Actions Pipeline

**ID:** SPEC-004  
**Status:** Draft  
**Last Updated:** 2026-05-23 (added manual approval gate for tofu apply)  
**Depends On:** SPEC-003 (GitHub Actions OIDC role and static assets bucket must exist before the workflow can run)

---

## Overview

This spec adds two GitHub Actions workflows to the repository: one that builds and deploys the React SPA to S3 + CloudFront on every push to `main`, and one that plans and applies OpenTofu infrastructure changes when files under `infra/` change. Together, they form the complete CI/CD pipeline for a single production environment.

Neither workflow stores long-lived AWS credentials. Both use the GitHub OIDC identity provider and the deployment IAM role provisioned in SPEC-003, exchanging a short-lived GitHub-issued token for temporary AWS credentials at runtime.

---

## Scope

### In Scope

- GitHub Actions workflow: build and deploy the React SPA (`main` branch → S3 → CloudFront invalidation)
- GitHub Actions workflow: OpenTofu plan on pull requests; OpenTofu apply on merge to `main` for changes under `infra/` — gated behind a manual approval step
- GitHub OIDC credential exchange (no stored AWS access keys in GitHub secrets)
- Environment variable injection into the Vite build from GitHub Actions secrets / variables
- Workflow documentation (comments within the YAML files explaining each step)

### Out of Scope

- Staging or preview environments
- Per-PR preview deployments
- Rollback automation (manual re-deploy by reverting the commit is sufficient)
- Slack / email deployment notifications
- Automated end-to-end tests as part of the deployment gate
- Any changes to application code or IaC resources (this spec is workflow files only)

---

## Functional Requirements

### FR-001: GitHub OIDC Credential Exchange

#### Description:
Both workflows must obtain temporary AWS credentials via the GitHub OIDC provider rather than using stored access keys. This requires the `id-token: write` permission on the workflow job.

#### Acceptance Criteria:
- [ ] Neither workflow references `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` secrets
- [ ] Both workflows use the `aws-actions/configure-aws-credentials` action with `role-to-assume` set to the deployment role ARN from SPEC-003
- [ ] The role ARN is stored as a GitHub Actions variable (`AWS_DEPLOY_ROLE_ARN`) — not hardcoded in the YAML
- [ ] Both workflow jobs declare `permissions: id-token: write` and `contents: read`
- [ ] If credential exchange fails, the job fails immediately with an informative error (default behavior of the action)

---

### FR-002: App Build and Deploy Workflow

#### Description:
On every push to `main`, the SPA is built with production environment variables and the compiled output is synced to the static assets S3 bucket, followed by a CloudFront cache invalidation.

#### Acceptance Criteria:
- [ ] Workflow file is at `.github/workflows/deploy-app.yml`
- [ ] Workflow triggers on `push` to the `main` branch only
- [ ] Job steps in order: checkout → Node.js setup (version pinned to match project) → `npm ci` → `npm run build` → AWS credentials via OIDC → `aws s3 sync dist/ s3://$BUCKET --delete` → `aws cloudfront create-invalidation --distribution-id $DIST_ID --paths "/*"`
- [ ] All `VITE_*` environment variables are injected into the build step from GitHub Actions variables (not secrets, as they are not sensitive)
- [ ] `VITE_APP_URL` is set to the production CloudFront domain (or custom domain if configured)
- [ ] The bucket name and CloudFront distribution ID are stored as GitHub Actions variables (`S3_STATIC_BUCKET`, `CLOUDFRONT_DISTRIBUTION_ID`)
- [ ] The workflow runs `npm run lint` before the build step; a lint failure blocks the deploy
- [ ] The workflow runs `npm run test` before the build step; a test failure blocks the deploy

---

### FR-003: OpenTofu Plan and Apply Workflow

#### Description:
Infrastructure changes under `infra/` are planned automatically on pull requests (output posted as a PR comment). When a PR is merged to `main`, the workflow pauses at an approval gate before applying. A designated reviewer must approve before `tofu apply` runs.

#### Acceptance Criteria:
- [ ] Workflow file is at `.github/workflows/deploy-infra.yml`
- [ ] Workflow triggers on: `pull_request` (paths: `infra/**`) and `push` to `main` (paths: `infra/**`)
- [ ] On `pull_request`: runs `tofu init` → `tofu validate` → `tofu plan`; plan output is posted as a comment on the PR using the `actions/github-script` action or equivalent
- [ ] On `push` to `main`: the workflow is split into two jobs — `plan` and `apply`. The `apply` job declares `environment: production` and `needs: plan`, which triggers the GitHub environment protection rules before the job starts
- [ ] A GitHub environment named `production` is created in the repository with at least one required reviewer configured — this is the manual gate; `tofu apply` does not run until a reviewer approves in the GitHub Actions UI
- [ ] The `apply` job runs `tofu init` → `tofu apply -auto-approve` only after approval is granted
- [ ] The `opentofu/setup-opentofu` action is used to install OpenTofu at a pinned version in both jobs
- [ ] OpenTofu variables (`TF_VAR_*`) are injected from GitHub Actions variables
- [ ] State bucket name and DynamoDB lock table name are available to the backend config as environment variables or via a `backend.hcl` partial config
- [ ] `tofu validate` failure on a PR blocks the PR (job exits non-zero)
- [ ] Apply failures leave the workflow in a failed state (no silent swallowing); the failed run is visible in the GitHub Actions UI
- [ ] `.github/workflows/README.md` documents how to create the `production` environment and add required reviewers (Settings → Environments → New environment)

---

### FR-004: Workflow Secrets and Variables Documentation

#### Description:
Every GitHub Actions secret and variable required by both workflows must be documented so the repo can be set up from scratch.

#### Acceptance Criteria:
- [ ] `.github/workflows/README.md` lists every required GitHub Actions variable and secret, its purpose, and where the value comes from (e.g. "from `tofu output cloudfront_distribution_id`")
- [ ] The README distinguishes between variables (non-sensitive, visible in logs) and secrets (masked)
- [ ] The README includes a "First-time setup" checklist: bootstrap state backend → `tofu apply` → capture outputs → populate GitHub variables → trigger first deploy

---

## Required GitHub Actions Variables and Secrets

### Variables (non-sensitive — set under repo Settings → Variables → Actions)

| Variable | Value source | Used by |
|---|---|---|
| `AWS_REGION` | `us-east-1` (or your region) | Both workflows |
| `AWS_DEPLOY_ROLE_ARN` | `tofu output github_actions_role_arn` | Both workflows |
| `S3_STATIC_BUCKET` | `tofu output s3_static_assets_bucket_name` | deploy-app |
| `CLOUDFRONT_DISTRIBUTION_ID` | `tofu output cloudfront_distribution_id` | deploy-app |
| `VITE_AWS_REGION` | same as `AWS_REGION` | deploy-app build |
| `VITE_COGNITO_USER_POOL_ID` | `tofu output cognito_user_pool_id` | deploy-app build |
| `VITE_COGNITO_USER_POOL_CLIENT_ID` | `tofu output cognito_user_pool_client_id` | deploy-app build |
| `VITE_COGNITO_DOMAIN` | `tofu output cognito_domain` | deploy-app build |
| `VITE_APP_URL` | CloudFront domain or custom domain | deploy-app build |
| `VITE_IAM_ROLE_ARN` | `tofu output iam_role_arn` | deploy-app build |
| `VITE_S3_PERSONAL_BUCKET` | `tofu output s3_personal_bucket_name` | deploy-app build |
| `VITE_S3_SHARED_BUCKET` | `tofu output s3_shared_bucket_name` | deploy-app build |
| `TF_VAR_aws_region` | same as `AWS_REGION` | deploy-infra |
| `TF_VAR_app_url` | same as `VITE_APP_URL` | deploy-infra |
| `TF_VAR_github_repo` | `owner/repo-name` | deploy-infra |
| `TF_VAR_state_bucket` | bootstrap bucket name | deploy-infra |
| `TF_VAR_state_lock_table` | bootstrap DynamoDB table name | deploy-infra |

### Secrets (sensitive — set under repo Settings → Secrets → Actions)

None required. All values are non-sensitive configuration. AWS credentials are obtained via OIDC at runtime.

> **Note:** If a `TF_VAR_custom_domain` is ever needed (custom domain for CloudFront), it would be a variable, not a secret.

---

## File & Folder Structure

```
.github/
└── workflows/
    ├── deploy-app.yml          ← SPA build + S3 sync + CloudFront invalidation
    ├── deploy-infra.yml        ← OpenTofu plan (PRs) + apply (main)
    └── README.md               ← setup guide and variable/secret inventory
```

---

## Workflow Sketches

These are structural outlines for the implementer — not final YAML. Variable names are as defined in FR-004.

### deploy-app.yml

```
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - checkout
      - setup Node (pin version from .nvmrc or package.json engines)
      - npm ci
      - npm run lint          # blocks on failure
      - npm run test          # blocks on failure
      - npm run build         # VITE_* vars injected from GitHub variables
      - configure-aws-credentials (OIDC, role: AWS_DEPLOY_ROLE_ARN)
      - aws s3 sync dist/ s3://$S3_STATIC_BUCKET --delete
      - aws cloudfront create-invalidation --distribution-id $CLOUDFRONT_DISTRIBUTION_ID --paths "/*"
```

### deploy-infra.yml

```
on:
  pull_request:
    paths: [infra/**]
  push:
    branches: [main]
    paths: [infra/**]

jobs:
  plan:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
      pull-requests: write     # needed to post plan comment on PRs
    steps:
      - checkout
      - setup-opentofu (pinned version)
      - configure-aws-credentials (OIDC)
      - tofu init
      - tofu validate
      - tofu plan → capture output
      - if pull_request: post plan output as PR comment

  apply:
    if: github.event_name == 'push'   # only runs on merge to main
    needs: plan
    environment: production           # ← triggers manual approval gate
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - checkout
      - setup-opentofu (pinned version)
      - configure-aws-credentials (OIDC)
      - tofu init
      - tofu apply -auto-approve
```

> **How the approval gate works:** The `apply` job references `environment: production`. GitHub pauses the job and notifies the required reviewers configured on that environment. A reviewer approves (or rejects) in the GitHub Actions UI. Only on approval does the job proceed. If rejected or timed out, the workflow fails without applying any changes.

---

## Implementation Phases

### Phase 1: deploy-app workflow

- Create `.github/workflows/deploy-app.yml` following the sketch above
- Create `.github/workflows/README.md` with the variable/secret table and first-time setup checklist
- Populate all required GitHub Actions variables in the repository settings
- Verify the workflow runs successfully on a push to `main` (requires SPEC-003 infrastructure to exist)

#### Checkpoint
Push a trivial change to `main`. The Actions run completes: lint passes, tests pass, build succeeds, files appear in the static assets S3 bucket, CloudFront invalidation shows as `Completed` in the AWS console. The app loads at the CloudFront domain.

---

### Phase 2: deploy-infra workflow

- Create `.github/workflows/deploy-infra.yml` following the sketch above
- Add the `TF_VAR_*` variables to repository settings
- Create the `production` environment in GitHub repo Settings → Environments; add at least one required reviewer
- Test plan: open a PR that makes a trivial IaC change (e.g. adds a tag to one resource); verify the plan is posted as a PR comment
- Test apply: merge the PR; verify the Actions run pauses at the approval gate; approve it; verify `tofu apply` runs and succeeds

#### Checkpoint
PR with an IaC change shows a `tofu plan` comment. Merging the PR triggers the workflow but the `apply` job pauses waiting for approval. After a reviewer approves in the GitHub Actions UI, `tofu apply` completes and the AWS console reflects the change. No AWS credentials are stored as GitHub secrets (verify under repo Settings → Secrets).

---

## Open Questions

- [ ] Should `npm run test` failures block the deploy, or only block merges to `main` via branch protection rules? Blocking the deploy is assumed here — confirm.
- [x] ~~Should the OpenTofu apply job have a manual approval gate?~~ **Resolved:** Yes — `apply` job uses `environment: production` with required reviewers.
- [ ] Node.js version: should it be pinned via `.nvmrc`, `package.json engines`, or hardcoded in the workflow?
