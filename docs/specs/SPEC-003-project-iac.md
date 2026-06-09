# Spec: Project IaC — OpenTofu AWS Infrastructure

**ID:** SPEC-003  
**Status:** Draft  
**Last Updated:** 2026-05-23  
**Depends On:** None (infrastructure is independent of application code)

---

## Overview

This spec establishes the OpenTofu project that provisions all AWS infrastructure required to run the S3 portal. It is a one-time setup concern: the resulting configuration is the canonical source of truth for every AWS resource the application depends on. Once applied, the IaC output values (bucket names, Cognito pool IDs, CloudFront domain, IAM role ARN) feed directly into the application's environment variables.

OpenTofu is the chosen IaC tool — it is the community-maintained open-source fork of Terraform, uses identical HCL syntax, and is compatible with all existing Terraform providers including the AWS provider.

---

## Scope

### In Scope

- OpenTofu project structure under `infra/`
- S3 + DynamoDB backend bootstrap for remote state (one-time manual step, documented)
- AWS provider configuration
- Cognito User Pool and User Pool Client (native users for MVP; AD federation is an infrastructure-only change later)
- Shared IAM Role with trust policy (Web Identity federation from the Cognito User Pool) and S3 permission policy using `${aws:PrincipalTag/username}` session tags
- S3 Personal Bucket (Bucket 1) with CORS and bucket policy
- S3 Shared Bucket (Bucket 2) with CORS and bucket policy (stub policy — Terraform-managed prefix grants are outside this spec)
- S3 Static Assets Bucket (hosts the built SPA) — private, no public access
- CloudFront Origin Access Control (OAC) and Distribution serving the static assets bucket
- ACM Certificate in `us-east-1` for the CloudFront distribution (if a custom domain is provided; optional)
- GitHub Actions OIDC Identity Provider and IAM role for use by the deployment pipeline (SPEC-004 depends on this)
- `outputs.tf` exporting all values needed as application env vars
- `.env.example` mapping from `tofu output` values to `VITE_*` variables

### Out of Scope

- Active Directory / SAML federation into Cognito (infrastructure concern, deferred)
- Terraform-managed per-user IAM prefix grants on Bucket 2 (owned by separate IaC pipeline)
- DNS / Route53 record creation (document the required CNAME manually if a custom domain is used)
- Staging environment (single prod environment only per this spec)
- Cognito user creation or group management
- Any application code changes

---

## Functional Requirements

### FR-001: OpenTofu Project Structure

#### Description:
A standalone `infra/` directory at the repo root contains all OpenTofu configuration. It must be runnable independently of the application build.

#### Acceptance Criteria:
- [ ] `infra/` directory exists at the repo root
- [ ] `infra/providers.tf` declares the `opentofu/aws` (hashicorp/aws) provider pinned to a specific version
- [ ] `infra/backend.tf` configures the S3 backend with the bootstrap bucket and DynamoDB lock table
- [ ] `infra/variables.tf` declares all input variables with descriptions and types
- [ ] `infra/terraform.tfvars.example` documents every required variable with placeholder values
- [ ] `infra/outputs.tf` exports all values needed to populate application env vars
- [ ] `infra/main.tf` (or logically separated `.tf` files) contains all resource definitions
- [ ] `infra/.terraform.lock.hcl` is committed to the repository (pins provider versions)
- [ ] `infra/.gitignore` excludes `.terraform/`, `*.tfstate`, `*.tfstate.backup`, and `*.tfvars` (to prevent accidental secret commit)

---

### FR-002: State Backend Bootstrap

#### Description:
Remote state requires an S3 bucket and DynamoDB table that must exist before `tofu init` can run. These are bootstrapped once and are not managed by the IaC itself.

#### Acceptance Criteria:
- [ ] `infra/bootstrap/README.md` documents the exact AWS CLI commands to create the state bucket and lock table
- [ ] The state bucket has versioning enabled and public access blocked
- [ ] The DynamoDB table uses `LockID` (string) as the partition key
- [ ] `infra/backend.tf` references the bootstrap bucket and table names via variables or hardcoded values with a comment explaining they must exist before `tofu init`
- [ ] The bootstrap README explains that the bootstrap resources are intentionally not in OpenTofu state

---

### FR-003: Cognito User Pool and Client

#### Description:
Provision a Cognito User Pool configured for native username/password auth (MVP) with the Hosted UI enabled for the OAuth flow used by the application.

#### Acceptance Criteria:
- [ ] A Cognito User Pool is created with password policy, email as a standard attribute, and username as the sign-in method
- [ ] A User Pool Client is created with no client secret (SPA), `code` response type, and allowed OAuth scopes: `openid`, `email`, `profile`
- [ ] A Cognito domain is created (prefixed subdomain under `amazoncognito.com`) for the Hosted UI
- [ ] Callback and sign-out URLs are set from a variable (e.g. `var.app_url`) to support both local and production values
- [ ] `outputs.tf` exports: `cognito_user_pool_id`, `cognito_user_pool_client_id`, `cognito_domain`

---

### FR-004: Shared IAM Role with Session Tag Trust

#### Description:
A single shared IAM role that all authenticated users assume. The trust policy grants `AssumeRoleWithWebIdentity` and `sts:TagSession` to tokens from the Cognito User Pool. The permission policy scopes S3 access using the `username` session tag.

#### Acceptance Criteria:
- [ ] An IAM role named `S3PortalRole` (or via variable) is created with the trust policy described in `docs/architecture.md`
- [ ] Trust policy grants `sts:AssumeRoleWithWebIdentity` AND `sts:TagSession` to the Cognito User Pool as federated principal — both actions are required; omitting `sts:TagSession` causes auth to fail silently
- [ ] Trust policy condition scopes to `authenticated` users and the specific User Pool Client ID
- [ ] Permission policy grants `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket` on the personal bucket scoped to `${aws:PrincipalTag/username}/*`
- [ ] `outputs.tf` exports `iam_role_arn`

---

### FR-005: S3 Personal Bucket

#### Description:
The personal bucket stores each user's files under their username prefix, plus their `connections.json` config. CORS is required for browser-based SDK access.

#### Acceptance Criteria:
- [ ] An S3 bucket is created with public access blocked and versioning disabled (optional at this stage)
- [ ] CORS configuration is applied matching the spec in `docs/architecture.md` (allowed methods: GET, PUT, POST, DELETE, HEAD; allowed origin from `var.app_url` and `var.cloudfront_domain` variable; exposed headers: ETag, x-amz-*)
- [ ] A bucket policy denies access to any principal except the shared IAM role and the AWS account root
- [ ] `outputs.tf` exports `s3_personal_bucket_name`

---

### FR-006: S3 Shared Bucket

#### Description:
The shared bucket hosts team/project prefixes whose access is managed by a separate IaC pipeline. This spec provisions the bucket itself with CORS; it does not manage prefix-level IAM grants.

#### Acceptance Criteria:
- [ ] An S3 bucket is created with public access blocked
- [ ] CORS configuration is applied (same settings as the personal bucket)
- [ ] A comment in the resource block notes that prefix-level IAM grants are managed by the separate Terraform IaC pipeline
- [ ] `outputs.tf` exports `s3_shared_bucket_name`

---

### FR-007: S3 Static Assets Bucket and CloudFront Distribution

#### Description:
The built SPA is served from a private S3 bucket via a CloudFront distribution. The distribution uses OAC to access the bucket. All routes return `index.html` to support SPA client-side routing.

#### Acceptance Criteria:
- [ ] An S3 bucket for static assets is created with all public access blocked
- [ ] A CloudFront Origin Access Control (OAC) is created for the static assets bucket
- [ ] A CloudFront distribution is created with: the static assets bucket as origin (via OAC), HTTPS only (redirect HTTP), `index.html` as default root object, and custom error responses mapping 403 and 404 to `/index.html` with HTTP 200 response code
- [ ] If `var.custom_domain` is provided, an ACM certificate (in `us-east-1`) and a CloudFront alias are configured; the certificate ARN is referenced but DNS validation record creation is documented as a manual step
- [ ] A bucket policy on the static assets bucket grants `s3:GetObject` to the CloudFront OAC principal only
- [ ] `outputs.tf` exports `cloudfront_domain`, `cloudfront_distribution_id`, `s3_static_assets_bucket_name`

---

### FR-008: GitHub Actions OIDC Role

#### Description:
Provision an IAM OIDC Identity Provider for GitHub Actions and a deployment role that the CI/CD pipeline can assume without storing long-lived AWS credentials. SPEC-004 depends on this role ARN.

#### Acceptance Criteria:
- [ ] An IAM OIDC provider is created for `token.actions.githubusercontent.com` with the correct thumbprint
- [ ] An IAM role (`S3PortalDeployRole` or via variable) is created with a trust policy allowing GitHub Actions to assume it, scoped to the specific repository (`var.github_repo`, e.g. `org/repo-name`) and the `main` branch only
- [ ] The role has permissions to: `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket` on the static assets bucket; `cloudfront:CreateInvalidation` on the distribution; and `tofu`/`terraform` state operations on the state bucket and DynamoDB table
- [ ] `outputs.tf` exports `github_actions_role_arn`

---

## Variables

All variables are declared in `infra/variables.tf` and documented in `infra/terraform.tfvars.example`.

| Variable | Type | Required | Description |
|---|---|---|---|
| `aws_region` | string | yes | AWS region for all resources (e.g. `us-east-1`) |
| `app_url` | string | yes | App URL for Cognito callback/sign-out and CORS origin (e.g. `https://portal.example.com`) |
| `cloudfront_domain` | string | no | CloudFront domain added to CORS allowed origins (known after first apply; leave blank on bootstrap) |
| `custom_domain` | string | no | Custom domain for CloudFront alias (optional; skip ACM/alias if not provided) |
| `iam_role_name` | string | no | Name of the shared portal IAM role. Defaults to `S3PortalRole` |
| `github_repo` | string | yes | GitHub repository in `owner/name` format for OIDC trust scope |
| `state_bucket` | string | yes | Name of the bootstrap S3 bucket for OpenTofu state |
| `state_lock_table` | string | yes | Name of the bootstrap DynamoDB table for state locking |

---

## Outputs

`infra/outputs.tf` exports the following. After `tofu apply`, these map directly to application `VITE_*` env vars:

| Output | Maps to env var |
|---|---|
| `cognito_user_pool_id` | `VITE_COGNITO_USER_POOL_ID` |
| `cognito_user_pool_client_id` | `VITE_COGNITO_USER_POOL_CLIENT_ID` |
| `cognito_domain` | `VITE_COGNITO_DOMAIN` |
| `iam_role_arn` | `VITE_IAM_ROLE_ARN` |
| `s3_personal_bucket_name` | `VITE_S3_PERSONAL_BUCKET` |
| `s3_shared_bucket_name` | `VITE_S3_SHARED_BUCKET` |
| `aws_region` | `VITE_AWS_REGION` |
| `cloudfront_domain` | `VITE_APP_URL` (after first deploy) |
| `cloudfront_distribution_id` | Used by SPEC-004 deployment workflow |
| `s3_static_assets_bucket_name` | Used by SPEC-004 deployment workflow |
| `github_actions_role_arn` | Used by SPEC-004 GitHub Actions workflow |

---

## File & Folder Structure

```
infra/
├── bootstrap/
│   └── README.md               ← manual AWS CLI commands for state bucket + DynamoDB table
├── main.tf                     ← Cognito, IAM, S3 buckets, CloudFront, OIDC provider
├── providers.tf                ← AWS provider version pin
├── backend.tf                  ← S3 remote state configuration
├── variables.tf                ← all input variable declarations
├── outputs.tf                  ← all outputs (maps to VITE_* env vars)
├── terraform.tfvars.example    ← placeholder values for all variables
└── .gitignore                  ← excludes .terraform/, *.tfvars, *.tfstate*
```

> Resources may be split into logical files (e.g. `cognito.tf`, `iam.tf`, `s3.tf`, `cloudfront.tf`) if `main.tf` grows unwieldy — this is a style preference, not a requirement.

---

## Implementation Phases

### Phase 1: Project scaffold and state backend

- Create `infra/` directory and all scaffold files (`providers.tf`, `backend.tf`, `variables.tf`, `outputs.tf`, `main.tf` stub, `.gitignore`, `terraform.tfvars.example`)
- Create `infra/bootstrap/README.md` with the exact AWS CLI commands
- Run `tofu init` locally against the bootstrap state bucket to verify the backend config is valid
- Commit `.terraform.lock.hcl`

#### Checkpoint
`tofu init` succeeds with remote state backend. `tofu validate` returns no errors. The lock file is present and committed.

---

### Phase 2: Cognito and IAM

- Add Cognito User Pool, User Pool Client, and Cognito domain resources
- Add the shared IAM role with trust policy and S3 permission policy
- Add outputs for all Cognito and IAM values
- Run `tofu plan` and review for correctness

#### Checkpoint
`tofu plan` shows Cognito and IAM resources to create with no errors. After `tofu apply` (against a dev AWS account or sandbox), the Cognito pool is visible in the AWS console and the IAM role trust policy matches the architecture doc exactly (verify `sts:TagSession` is present).

---

### Phase 3: S3 buckets

- Add personal bucket, shared bucket, and static assets bucket resources with CORS and bucket policies
- Add outputs for all bucket names

#### Checkpoint
`tofu apply` succeeds. All three buckets are visible in S3 console. CORS config is verified by fetching the bucket CORS in the console or via `aws s3api get-bucket-cors`. Public access is blocked on all three.

---

### Phase 4: CloudFront and GitHub Actions OIDC

- Add static assets bucket policy (OAC principal grant)
- Add CloudFront OAC and Distribution
- Add ACM certificate resource (conditional on `var.custom_domain`)
- Add GitHub OIDC provider and deployment role
- Add all remaining outputs

#### Checkpoint
`tofu apply` succeeds. CloudFront distribution is in `Deployed` state in the console. Fetching the CloudFront domain returns a 403 (no files deployed yet — correct). OIDC provider is visible in IAM console under Identity Providers. Running `tofu output` displays all expected values.

---

## Open Questions

- [ ] Should the Cognito Hosted UI be configured with a custom logo or CSS? Deferred — confirm plain Hosted UI is acceptable for MVP.
- [ ] Should versioning be enabled on the personal bucket? Useful for accidental-delete recovery but adds cost. Decision needed before Phase 3.
- [ ] What value should `app_url` be on the first apply (before CloudFront domain is known)? Recommend using `http://localhost:5173` for the bootstrap apply, then updating after CloudFront is deployed.
- [ ] Is a custom domain in scope for the initial deployment, or plain CloudFront domain only?
