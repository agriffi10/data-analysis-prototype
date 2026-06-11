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
