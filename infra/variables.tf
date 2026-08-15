variable "aws_region" {
  description = "AWS region for all resources (e.g. us-east-1)"
  type        = string
}

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
  default     = "dat"
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-user-pool)."
  type        = string
  default     = "prod"
}

variable "github_repo" {
  description = "GitHub repository in owner/name format (e.g. acme/s3-upload-portal). Scopes the GitHub Actions OIDC trust policy to this repo's main branch and pull requests."
  type        = string
}

variable "state_bucket" {
  description = "Name of the S3 bucket used for OpenTofu remote state (created by the bootstrap process, not managed by this IaC)."
  type        = string
}

variable "state_lock_table" {
  description = "Name of the DynamoDB table used for OpenTofu state locking (created by the bootstrap process, not managed by this IaC)."
  type        = string
}

variable "app_url" {
  description = "Public URL of the deployed app (e.g. the CloudFront domain). Used for Cognito OAuth callback URLs when auth IaC is added."
  type        = string
  default     = ""
}

variable "cognito_domain_prefix" {
  description = "Hosted UI domain prefix (must be globally unique across all AWS accounts). When empty, defaults to {project_name}-{environment}-portal."
  type        = string
  default     = ""
}

variable "user_space_bucket_name" {
  description = "Override for the user-space (Bucket 1) S3 name. When empty, defaults to {project_name}-prod-user-space. Override only if that global name is already taken (S3 names are globally unique)."
  type        = string
  default     = ""
}

variable "portal_role_name" {
  description = "Override for the shared portal IAM role name (SPEC-011). When empty, defaults to {project_name}-portal-user-role."
  type        = string
  default     = ""
}

variable "workgroup_name" {
  description = "Override for the shared Athena workgroup name (SPEC-032). When empty, defaults to {project_name}-prod-portal-wg."
  type        = string
  default     = ""
}

variable "athena_admin_bucket_name" {
  description = "Override for the admin-only Athena results bucket name (SPEC-032). When empty, defaults to {project_name}-prod-athena-admin. Override only if that global name is already taken (S3 names are globally unique)."
  type        = string
  default     = ""
}

variable "shared_space_bucket_name" {
  description = "Override for the shared-space (Bucket 2) S3 name (SPEC-050). When empty, defaults to {project_name}-prod-shared-space. Override only if that global name is already taken (S3 names are globally unique)."
  type        = string
  default     = ""
}

variable "archive_bucket_name" {
  description = "Override for the archive (Bucket 5) S3 name (SPEC-168). When empty, defaults to {project_name}-prod-archive. Override only if that global name is already taken (S3 names are globally unique)."
  type        = string
  default     = ""
}

variable "max_shared_memberships" {
  description = "SPEC-056: number of shared-space membership slots per user (Cognito custom attributes custom:shared_space_1..N + Identity-Pool principal tags shared_space_1..N + portal-role policy slots). Single source for the slot count across auth/data/shared-spaces. Bounded because a Cognito Identity Pool maps each claim to exactly one single-valued principal tag; raising it enlarges the portal-role policy (see docs/architecture.md, Bucket 2 membership slots)."
  type        = number
  default     = 10
}

variable "principal_tag_key" {
  description = "IAM principal-tag key carrying the username (SPEC-011). Scopes the portal role's analytics Glue/results ARNs (SPEC-032 FR-006). Default 'username' — matches the Identity Pool attribute mapping."
  type        = string
  default     = "username"
}

# NOTE (SPEC-033): the post-confirmation Lambda exec role ARN that module.analytics
# adds as a Lake Formation admin is now sourced directly from module.auth's output
# (see main.tf), so the former root `lambda_provisioner_role_arn` variable was
# removed. The analytics module keeps its own optional variable (default "") so it
# still plans standalone before auth exists.

variable "verification_principal_arns" {
  description = "SPEC-186 FR-004: IAM principals allowed to assume the read-only verification role (catalog read-backs + the archive audit record). Set as the TF_VAR_verification_principal_arns repo variable and applied by deploy-infra.yml — NOT in a local terraform.tfvars, which would require a local apply, and no human identity here can apply locally without tofu proposing to destroy the data buckets it cannot read. Empty (the default) means the role is not created at all; the CloudTrail trail ships either way, since it needs no principal."
  type        = list(string)
  default     = []
}
