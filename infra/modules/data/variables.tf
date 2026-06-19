variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
}

variable "app_url" {
  description = "Public URL of the deployed app (CloudFront domain). Added as a CORS origin when non-empty."
  type        = string
  default     = ""
}

variable "user_space_bucket_name" {
  description = "Name of the user-space S3 bucket (Bucket 1). Computed by the root module (default {project_name}-prod-user-space, overridable via the root user_space_bucket_name variable if the global name is taken)."
  type        = string
}

variable "identity_pool_id" {
  description = "Cognito Identity Pool ID (from the auth module). Used as the portal role's trust audience and bound as the pool's authenticated role. Keeps the dependency one-directional: data -> auth."
  type        = string
}

variable "portal_role_name" {
  description = "Name of the shared portal IAM role (SPEC-011). Computed by the root module (default {project_name}-portal-user-role)."
  type        = string
}

variable "deploy_role_arn" {
  description = "ARN of the GitHub Actions deploy role (modules/base). Excluded from the user-space bucket policy's data-access Deny so the IaC principal can HeadBucket/manage the bucket; without it tofu refresh reports false 'deleted' drift and plans a destructive recreate (SPEC-013 FR-002 fix)."
  type        = string
}

variable "lf_registration_role_arn" {
  description = "ARN of the analytics Lake Formation registration role (modules/analytics, SPEC-032), constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny: LF assumes this role to read the registered location when serving Athena queries, so the explicit Deny would otherwise block its s3:ListBucket/GetObject and queries fail with PERMISSION_DENIED."
  type        = string
}
