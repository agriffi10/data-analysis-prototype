variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository in owner/name format. Scopes the GitHub Actions OIDC trust policy to this repo's main branch and pull requests."
  type        = string
}

variable "state_bucket" {
  description = "Name of the S3 bucket used for OpenTofu remote state."
  type        = string
}

variable "state_lock_table" {
  description = "Name of the DynamoDB table used for OpenTofu state locking."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to scope the state lock table ARN in the deploy policy."
  type        = string
}

variable "static_bucket_arn" {
  description = "ARN of the static assets bucket the deploy role manages (from the app module)."
  type        = string
}

variable "user_space_bucket_arn" {
  description = "ARN of the user-space (Bucket 1) S3 bucket the deploy role manages. Passed as a constructed string from the root module to avoid a dependency cycle with the data module."
  type        = string
}

variable "portal_role_arn" {
  description = "ARN of the shared portal IAM role the deploy role manages. Passed as a constructed string from the root module to avoid a dependency cycle with the data module."
  type        = string
}

variable "lambda_artifacts_bucket_arn" {
  description = "ARN of the Lambda deployment artifacts bucket the deploy role manages and uploads packages to. Passed as a constructed string from the root module to avoid a dependency cycle with the lambda-artifacts module."
  type        = string
}

variable "athena_admin_bucket_arn" {
  description = "ARN of the admin-only Athena results bucket the deploy role manages. Passed as a constructed string from the root module to avoid a dependency cycle with the analytics module."
  type        = string
}

variable "shared_space_bucket_arn" {
  description = "ARN of the shared-space (Bucket 2) S3 bucket the deploy role manages. Passed as a constructed string from the root module to avoid a dependency cycle with the shared-spaces module. The rest of the shared-space deploy grants (SQS/Pipes/Step Functions/Lambda/roles/logs) are scoped by {project_name}-*-shared-space-* name patterns in the policy template."
  type        = string
}

variable "archive_bucket_name" {
  description = "NAME (not ARN) of the archive bucket the deploy role manages (Bucket 5). Passed as a constructed string from the root module to avoid a dependency cycle with the archive module. A NAME because the policy template builds both the bucket and the object ARN from it, and because this bucket is the one resource in that plane its {project_name}-*-archive-* name patterns cannot cover: the bucket has no trailing segment, so it needs an exact-name statement of its own."
  type        = string
  default     = ""
}

variable "verification_trail_bucket_name" {
  description = "NAME (not ARN) of the archive-audit trail bucket the deploy role manages. A constructed string from the root module, for the same reason archive_bucket_name is one: it avoids a dependency cycle with the module that creates the bucket, and the bucket's own name has no trailing segment a pattern could match."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Hosted zone ID for the front door's parent domain. Scopes the deploy role's Route 53 record-writing grant to the one zone this platform owns."
  type        = string
}
