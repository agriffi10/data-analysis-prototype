variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment}."
  type        = string
}

variable "app_url" {
  description = "Public URL of the deployed app (e.g. the CloudFront domain). Added to the User Pool Client callback/logout URLs alongside localhost. When empty, only localhost is configured."
  type        = string
  default     = ""
}

variable "cognito_domain_prefix" {
  description = "Hosted UI domain prefix (must be globally unique). When empty, defaults to {project_name}-{environment}-portal."
  type        = string
  default     = ""
}

# ── SPEC-033 post-confirmation provisioning Lambda inputs ────────────────────

variable "aws_region" {
  description = "AWS region — used to scope the post-confirmation Lambda exec role's Glue ARNs (SPEC-033)."
  type        = string
}

variable "account_id" {
  description = "AWS account ID — used to build the Glue catalog/database ARNs in the post-confirmation Lambda exec role policy (SPEC-033)."
  type        = string
}

variable "portal_role_arn" {
  description = "ARN of the shared portal IAM role (SPEC-011). The post-confirmation Lambda receives this via env var and targets it in the per-database Lake Formation grant (SPEC-033 FR-002)."
  type        = string
}

# ── SPEC-056 shared-space membership slots ───────────────────────────────────

variable "max_shared_memberships" {
  description = "SPEC-056: number of shared-space membership slots — the user pool gains custom:shared_space_1..N (mutable string) and the Identity Pool maps each to principal tag shared_space_1..N. Single source is the root variable of the same name."
  type        = number
  default     = 10
}
