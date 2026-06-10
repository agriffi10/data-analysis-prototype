# Spec: Deploy App to AWS — GitHub Actions Pipeline

**ID:** SPEC-005  
**Status:** Draft  
**Last Updated:** 2026-06-09  
**Depends On:** SPEC-003 (OIDC provider, deployment role, static assets S3 bucket, and CloudFront distribution must exist), SPEC-004 (CI must be passing before deploy runs)

---

## Overview

This spec adds two GitHub Actions workflows that deploy the application to AWS: one that builds and syncs the React SPA to S3 + invalidates CloudFront on every merge to `main`, and one that plans and applies OpenTofu infrastructure changes when files under `infra/` change. Both workflows authenticate to AWS via GitHub OIDC federation — no long-lived credentials are stored anywhere.

**Pipeline split:**
- **Pull requests** → CI only (SPEC-004). The infra workflow runs `tofu plan` on PRs targeting infra changes, but this is read-only and makes no AWS changes.
- **Push to `main`** → CI (SPEC-004) runs first; if it passes, both deploy workflows fire automatically. The app is built and synced to S3; infrastructure changes are planned then applied without a manual gate (continuous deployment).

Deploy workflows never fire on PRs. Branch protection rules requiring SPEC-004 CI to pass enforce this ordering.

---

## Scope

### In Scope

- GitHub Actions workflow: build and deploy the React SPA (`main` branch → S3 sync → CloudFront invalidation)
- GitHub Actions workflow: OpenTofu plan on pull requests; OpenTofu plan + auto-apply on merge to `main` for changes under `infra/`
- AWS credential exchange via GitHub OIDC (no stored access keys)
- `VITE_*` environment variable injection into the Vite build from GitHub Actions variables
- Workflow documentation (comments within the YAML files and a setup README)

### Out of Scope

- Stored AWS access keys (OIDC is used instead)
- Staging or preview environments
- Per-PR preview deployments
- Rollback automation (revert the commit and re-deploy)
- Slack / email deployment notifications
- Automated end-to-end tests as a deployment gate

---

## Functional Requirements

### FR-001: GitHub OIDC Credential Exchange

#### Description:
Both workflows must obtain temporary AWS credentials via the GitHub OIDC provider rather than using stored access keys. The OIDC provider and deployment role were provisioned by SPEC-003. Each workflow job requests a short-lived token from GitHub, which is exchanged for temporary AWS credentials scoped to the deployment role.

#### Acceptance Criteria:
- [ ] Neither workflow references `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY`
- [ ] Both workflows declare `permissions: id-token: write` and `contents: read` on the job
- [ ] Both workflows use `aws-actions/configure-aws-credentials` with `role-to-assume` set to `${{ secrets.AWS_DEPLOY_ROLE_ARN }}`
- [ ] `AWS_DEPLOY_ROLE_ARN` is stored as a GitHub Actions secret (value from `tofu output github_actions_role_arn`)
- [ ] `AWS_REGION` is stored as a GitHub Actions variable
- [ ] If credential exchange fails, the job fails immediately with an informative error (default behavior of the action)

---

### FR-002: App Build and Deploy Workflow

#### Description:
On every merge to `main`, the SPA is built with production environment variables injected from GitHub Actions variables, the compiled output is synced to the static assets S3 bucket, and a CloudFront cache invalidation is triggered.

#### Acceptance Criteria:
- [ ] Workflow file is at `.github/workflows/deploy-app.yml`
- [ ] Workflow triggers on `push` to the `main` branch only
- [ ] `npm ci` is run from the **repo root**
- [ ] `npm run build` is run with `working-directory: apps/portal`
- [ ] All `VITE_*` environment variables are injected into the build step from GitHub Actions variables
- [ ] The S3 sync step runs: `aws s3 sync apps/portal/dist/ s3://$S3_STATIC_BUCKET --delete`
- [ ] The CloudFront invalidation step runs: `aws cloudfront create-invalidation --distribution-id $CLOUDFRONT_DISTRIBUTION_ID --paths "/*"`
- [ ] `S3_STATIC_BUCKET` and `CLOUDFRONT_DISTRIBUTION_ID` are stored as GitHub Actions variables
- [ ] A failure at any step (build, sync, or invalidation) fails the workflow and leaves it in a failed state visible in the Actions UI

---

### FR-003: OpenTofu Plan and Apply Workflow

#### Description:
Infrastructure changes under `infra/` are planned automatically on pull requests (output posted as a PR comment). When a PR merges to `main`, the workflow pauses at a manual approval gate before running `tofu apply`.

#### Acceptance Criteria:
- [ ] Workflow file is at `.github/workflows/deploy-infra.yml`
- [ ] Workflow triggers on `pull_request` (paths: `infra/**`) and `push` to `main` (paths: `infra/**`)
- [ ] On `pull_request`: runs `tofu init` → `tofu validate` → `tofu plan`; plan output is posted as a comment on the PR
- [ ] On `push` to `main`: workflow has two jobs — `plan` and `apply`; the `apply` job declares `needs: plan` and runs automatically without a manual gate
- [ ] `tofu apply -auto-approve` runs automatically after `plan` succeeds on `main`
- [ ] The `opentofu/setup-opentofu` action is used at a pinned version in both jobs
- [ ] OpenTofu variables (`TF_VAR_*`) are injected from GitHub Actions variables
- [ ] `tofu validate` failure on a PR fails the workflow job (non-zero exit)
- [ ] Apply failures leave the workflow in a failed state — no silent swallowing

---

### FR-004: Workflow Documentation

#### Description:
Every GitHub Actions variable required by both workflows is documented so the repository can be configured from scratch.

#### Acceptance Criteria:
- [ ] `.github/workflows/README.md` lists every required variable, its purpose, and where its value comes from (e.g. "from `tofu output cloudfront_distribution_id`")
- [ ] README includes a first-time setup checklist: verify SPEC-003 IaC is applied → capture outputs → populate GitHub variables → create `production` environment → trigger first deploy

---

## Required GitHub Actions Secrets and Variables

AWS credentials are obtained via OIDC at runtime — no AWS keys are stored.

`VITE_AWS_REGION` and `TF_VAR_aws_region` are derived from `AWS_REGION` in the workflow YAML. `TF_VAR_app_url` is derived from `VITE_APP_URL`. These do not need to be set as separate GitHub variables.

### Secrets (repo Settings → Secrets → Actions)

| Secret | Value source |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `tofu output github_actions_role_arn` |
| `S3_STATIC_BUCKET` | `tofu output s3_static_assets_bucket_name` |
| `CLOUDFRONT_DISTRIBUTION_ID` | `tofu output cloudfront_distribution_id` |
| `TF_VAR_state_bucket` | bootstrap state bucket name |
| `TF_VAR_state_lock_table` | bootstrap DynamoDB table name |

### Variables (repo Settings → Variables → Actions)

| Variable | Value source |
|---|---|
| `AWS_REGION` | e.g. `us-east-1` |
| `VITE_APP_URL` | `tofu output cloudfront_domain` |
| `TF_VAR_github_repo` | `owner/repo-name` |
| `VITE_COGNITO_USER_POOL_ID` | future IaC output |
| `VITE_COGNITO_USER_POOL_CLIENT_ID` | future IaC output |
| `VITE_COGNITO_DOMAIN` | future IaC output |
| `VITE_IAM_ROLE_ARN` | future IaC output |
| `VITE_S3_PERSONAL_BUCKET` | future IaC output |
| `VITE_S3_SHARED_BUCKET` | future IaC output |

> **Note:** Cognito and IAM variables are placeholders until those resources are provisioned (deferred from SPEC-003 scope). Set them to empty strings for now; the app will build but auth won't function until they're populated.

---

## File & Folder Structure

```
.github/
└── workflows/
    ├── deploy-app.yml      ← SPA build + S3 sync + CloudFront invalidation
    ├── deploy-infra.yml    ← OpenTofu plan (PRs) + apply (main, gated)
    └── README.md           ← setup guide and variable inventory
```

---

## Workflow Sketches

Structural outlines for the implementer — not final YAML.

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
      - setup Node (pin version)
      - npm ci                                       # repo root — installs all workspaces
      - npm run build                                # working-directory: apps/portal
                                                     # env vars injected into build step:
                                                     #   VITE_AWS_REGION: ${{ vars.AWS_REGION }}
                                                     #   VITE_APP_URL: ${{ vars.VITE_APP_URL }}
                                                     #   VITE_COGNITO_*: from vars
                                                     #   (etc. for all VITE_* vars)
      - configure-aws-credentials
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
      - aws s3 sync apps/portal/dist/ s3://$S3_STATIC_BUCKET --delete
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
      - configure-aws-credentials
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
      - tofu init
      - tofu validate
      - tofu plan → capture output               # env vars injected:
                                                 #   TF_VAR_aws_region: ${{ vars.AWS_REGION }}
                                                 #   TF_VAR_app_url: ${{ vars.VITE_APP_URL }}
                                                 #   TF_VAR_github_repo: ${{ vars.TF_VAR_github_repo }}
                                                 #   TF_VAR_state_bucket: ${{ secrets.TF_VAR_state_bucket }}
                                                 #   TF_VAR_state_lock_table: ${{ secrets.TF_VAR_state_lock_table }}
      - if pull_request: post plan output as PR comment

  apply:
    if: github.event_name == 'push'     # only on merge to main
    needs: plan
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - checkout
      - setup-opentofu (pinned version)
      - configure-aws-credentials
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
      - tofu init
      - tofu apply -auto-approve
```

---

## Implementation Phases

### Phase 1: App deploy workflow

- Create `.github/workflows/deploy-app.yml`
- Create `.github/workflows/README.md` with variable inventory and first-time setup checklist
- Populate all required GitHub Actions variables in repository settings

#### Checkpoint
Merge a trivial change to `main`. The workflow triggers, OIDC credential exchange succeeds, build produces `apps/portal/dist/`, files appear in the S3 static assets bucket, and the CloudFront invalidation completes. The app loads at the CloudFront domain.

---

### Phase 2: OpenTofu deploy workflow

- Create `.github/workflows/deploy-infra.yml`
- Add `TF_VAR_*` variables to repository settings
- Test plan: open a PR with a trivial IaC change; verify `tofu plan` output appears as a PR comment
- Test apply: merge the PR; verify `plan` then `apply` both complete automatically

#### Checkpoint
PR with an IaC change shows a plan comment. Merging triggers the workflow and `tofu apply` runs automatically after plan succeeds. The AWS console reflects the change.

---

## Open Questions

- [x] ~~Should the deploy workflow re-run unit tests before deploying?~~ **Resolved:** No. SPEC-004 CI runs on every push to `main` and branch protection rules require it to pass.
- [x] ~~**OIDC trust policy scope for PR plan step**~~ **Resolved:** Trust policy updated in `infra/iam.tf` to allow both `ref:refs/heads/main` and `pull_request` events. State backend (S3 + DynamoDB) permissions also added to the role policy.
- [ ] Node.js version: `.nvmrc`, `package.json engines`, or hardcoded in the workflow YAML?
