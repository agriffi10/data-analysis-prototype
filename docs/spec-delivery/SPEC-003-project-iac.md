# Completed Spec - Project IaC (SPEC-003)

## What was completed from this spec?

OpenTofu project scaffold provisioning the AWS infrastructure needed to host and deploy the SPA:
a private S3 static assets bucket, a CloudFront distribution (OAC, HTTPS, SPA error routing),
and a GitHub Actions OIDC identity provider + deployment role.

**Scope narrowed from draft:** Cognito, the shared IAM portal role, and the S3 personal/shared
data buckets are provisioned separately and are not managed by this IaC project.

**New files created:**

| File | Purpose |
|---|---|
| `infra/.gitignore` | Excludes `.terraform/`, `*.tfstate*`, `*.tfvars`, `backend.conf` |
| `infra/providers.tf` | `hashicorp/aws ~> 5.0` and `hashicorp/tls ~> 4.0` providers; OpenTofu >= 1.8 |
| `infra/backend.tf` | Partial S3 backend config (bucket/region/table supplied via `backend.conf`); hardcodes the state key |
| `infra/variables.tf` | `aws_region`, `project_name` (default `s3-upload-portal`), `github_repo` |
| `infra/s3.tf` | Static assets S3 bucket (private, all public access blocked) + bucket policy granting CloudFront OAC read |
| `infra/cloudfront.tf` | CloudFront OAC + distribution (`Managed-CachingOptimized` cache policy; 403/404 → `index.html` custom error responses; HTTPS redirect; `index.html` default root) |
| `infra/iam.tf` | GitHub Actions OIDC provider (thumbprint fetched dynamically via `tls` provider) + deployment role (scoped to `main` branch of `var.github_repo`; S3 deploy + CloudFront invalidation permissions) |
| `infra/outputs.tf` | `s3_static_assets_bucket_name`, `cloudfront_distribution_id`, `cloudfront_domain`, `github_actions_role_arn`, `aws_region` |
| `infra/terraform.tfvars.example` | Placeholder values for all variables |
| `infra/bootstrap/README.md` | Step-by-step AWS CLI commands to create the state S3 bucket (versioning, encryption, public access block) and DynamoDB lock table; instructions for `backend.conf` and `tofu init` |
| `infra/bootstrap/backend.conf.example` | Template for the gitignored `backend.conf` file |

## What has changed?

### `.env.example`

Expanded from SPEC-001/002 dev variables into a full production variable map. Each variable
is annotated with its source (IaC output, separately provisioned, or local dev only).
New variables documented: `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_USER_POOL_CLIENT_ID`,
`VITE_COGNITO_DOMAIN`, `VITE_IAM_ROLE_ARN`, `VITE_S3_PERSONAL_BUCKET`, `VITE_S3_SHARED_BUCKET`,
`VITE_APP_URL`.

## First-apply checklist

Run these steps in order when applying against a real AWS account:

1. Bootstrap: follow `infra/bootstrap/README.md` to create the state bucket and lock table
2. `cp infra/bootstrap/backend.conf.example infra/backend.conf` and fill in values
3. `cp infra/terraform.tfvars.example infra/terraform.tfvars` and fill in values
4. `cd infra && tofu init -backend-config=backend.conf`
5. Commit the generated `infra/.terraform.lock.hcl`
6. `tofu plan` — review resources; expect static assets bucket + CloudFront + OIDC provider + deploy role
7. `tofu apply`
8. `tofu output` — copy values into the SPEC-004 GitHub Actions workflow secrets
9. Set `VITE_APP_URL` to `tofu output cloudfront_domain` value
