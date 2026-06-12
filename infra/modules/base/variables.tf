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
  description = "ARN of the user-space (Bucket 1) S3 bucket the deploy role manages (SPEC-010). Passed as a constructed string from the root module to avoid a dependency cycle with the data module."
  type        = string
}

variable "portal_role_arn" {
  description = "ARN of the shared portal IAM role the deploy role manages (SPEC-011). Passed as a constructed string from the root module to avoid a dependency cycle with the data module."
  type        = string
}

variable "lambda_artifacts_bucket_arn" {
  description = "ARN of the Lambda deployment artifacts bucket the deploy role manages and uploads packages to (SPEC-012). Passed as a constructed string from the root module to avoid a dependency cycle with the lambda-artifacts module."
  type        = string
}
