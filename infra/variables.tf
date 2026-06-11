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
