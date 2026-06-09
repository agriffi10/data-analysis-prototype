variable "aws_region" {
  description = "AWS region for all resources (e.g. us-east-1)"
  type        = string
}

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
  default     = "s3-upload-portal"
}

variable "github_repo" {
  description = "GitHub repository in owner/name format (e.g. acme/s3-upload-portal). Scopes the GitHub Actions OIDC trust policy to the main branch of this repo only."
  type        = string
}
