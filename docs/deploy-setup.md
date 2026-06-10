# SPEC-005 Setup Checklist

Everything that must be done before the SPEC-005 deploy workflows will function. Work through these sections in order — later steps depend on earlier ones.

---

## ~~1. Verify SPEC-003 infrastructure is applied~~ ✓ Done

- [x] S3 static assets bucket
- [x] CloudFront distribution (in `Deployed` state)
- [x] GitHub Actions OIDC Identity Provider (`token.actions.githubusercontent.com`) in IAM
- [x] GitHub Actions deployment IAM role

---

## ~~2. Capture IaC output values~~ ✓ Done

Run from the `infra/` directory:

```bash
cd infra
tofu output
```

Copy these values — you'll need them in Step 3:

| Output key | What to copy |
|---|---|
| `github_actions_role_arn` | full ARN, e.g. `arn:aws:iam::123456789012:role/s3-upload-portal-deploy-role` |
| `s3_static_assets_bucket_name` | bucket name string |
| `cloudfront_distribution_id` | distribution ID, e.g. `E1ABCDEFGHIJKL` |
| `cloudfront_domain` | domain, e.g. `https://d1234abcd.cloudfront.net` |
| `aws_region` | region string, e.g. `us-east-1` |

> Cognito and IAM outputs (`cognito_user_pool_id`, `iam_role_arn`, etc.) are not yet provisioned — those resources were deferred from SPEC-003. Leave the corresponding GitHub variables as empty strings for now; the app will build but auth won't function until they're populated.

---

## ~~3. Configure GitHub Actions variables~~ ✓ Done

No secrets are needed. AWS credentials are obtained at runtime via OIDC — there are no long-lived keys to store.

Navigate to: **GitHub repo → Settings → Secrets and variables → Actions → Variables tab**

### Secrets (Settings → Secrets and variables → Actions → Secrets tab)

| Secret | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | from `tofu output github_actions_role_arn` |
| `S3_STATIC_BUCKET` | from `tofu output s3_static_assets_bucket_name` |
| `CLOUDFRONT_DISTRIBUTION_ID` | from `tofu output cloudfront_distribution_id` |
| `TF_VAR_state_bucket` | state bucket name (from `infra/bootstrap/backend.conf`) |
| `TF_VAR_state_lock_table` | DynamoDB table name (from `infra/bootstrap/backend.conf`) |

### Variables (Settings → Secrets and variables → Actions → Variables tab)

| Variable | Value |
|---|---|
| `AWS_REGION` | from `tofu output aws_region` |
| `VITE_APP_URL` | from `tofu output cloudfront_domain` |
| `TF_VAR_github_repo` | your repo in `owner/repo-name` format |

> `VITE_AWS_REGION` and `TF_VAR_aws_region` are derived from `AWS_REGION` in the workflow YAML. `TF_VAR_app_url` is derived from `VITE_APP_URL`. No need to set these separately.

### Populate later (once Cognito and IAM are provisioned)

| Variable name | Future value source |
|---|---|
| `VITE_COGNITO_USER_POOL_ID` | future `tofu output cognito_user_pool_id` |
| `VITE_COGNITO_USER_POOL_CLIENT_ID` | future `tofu output cognito_user_pool_client_id` |
| `VITE_COGNITO_DOMAIN` | future `tofu output cognito_domain` |
| `VITE_IAM_ROLE_ARN` | future `tofu output iam_role_arn` |
| `VITE_S3_PERSONAL_BUCKET` | future `tofu output s3_personal_bucket_name` |
| `VITE_S3_SHARED_BUCKET` | future `tofu output s3_shared_bucket_name` |

Set these to empty strings for now so the build doesn't fail on a missing variable reference.

---

## ~~4. Apply the updated IaC (trust policy + state permissions)~~ ✓ Done

The `infra/iam.tf` was updated after the initial SPEC-003 apply with two changes:

1. **Trust policy widened** — the deployment role now allows both `main` branch pushes and `pull_request` events, so `tofu plan` can run on PRs.
2. **State backend permissions added** — the role now has S3 read/write on the state bucket and DynamoDB lock permissions, required for any `tofu init` / `plan` / `apply` operation.

Before running `tofu apply`, fill in the two new variables in `infra/terraform.tfvars`:

```
state_bucket     = "your-tofu-state-bucket-name"    # same value as in backend.conf
state_lock_table = "your-tofu-lock-table-name"      # same value as in backend.conf
```

Then apply:

```bash
cd infra
tofu plan    # should show: 1 change to aws_iam_role, 1 change to aws_iam_role_policy
tofu apply
```

---

## 5. Configure branch protection on `main`

This ensures CI must pass before any commit can merge, so the deploy workflows only run against code that has passed linting, tests, and build.

1. Go to **GitHub repo → Settings → Branches → Add branch protection rule**
2. Branch name pattern: `main`
3. Enable: **Require status checks to pass before merging**
4. Add the CI job name as a required check (it will appear in the dropdown after the first CI run — the job name from `ci.yml`, e.g. `ci`)
5. Enable: **Require branches to be up to date before merging** (optional but recommended)
6. Save

> Branch protection can only be configured after at least one CI run has completed, so the status check name appears in the dropdown. Implement SPEC-004 first, let it run once, then come back here.

---

## 6. Trigger first deploy

1. Merge any commit into `main`
2. Go to **GitHub repo → Actions** and watch the `deploy-app` workflow run
3. Verify:
   - OIDC credential exchange step succeeds
   - Build produces output
   - S3 sync completes (check the static assets bucket in AWS console)
   - CloudFront invalidation completes

The app should be live at the CloudFront domain after this run.

---

## Summary: what you need vs. what you don't

| Item | Needed? |
|---|---|
| AWS access keys stored in GitHub | No — OIDC handles this |
| GitHub Actions secrets | No — all values are non-sensitive variables |
| Manual approval gate | No — continuous deployment, auto-applies on merge to `main` |
| SPEC-003 IaC applied | Yes — OIDC role and hosting infra must exist |
| `tofu apply` for updated IAM role | Yes — widens trust to PRs and adds state backend permissions |
| Branch protection on `main` | Yes — enforces CI gate before deploy |
| Cognito/IAM resources | Not for initial deploy — needed before auth works |
