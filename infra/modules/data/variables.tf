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

variable "shared_space_orchestrator_role_arn" {
  description = "SPEC-051: ARN of the shared-space orchestrator role (SPEC-050), constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny so the privileged pipeline can write each member's per-user cache ({username}/user_settings/shared-connections.json); without the exclusion the resource-policy Deny would override the orchestrator's identity-policy Allow."
  type        = string
  default     = ""
}

variable "notifications_writer_role_arn" {
  description = "SPEC-058: ARN of the notifications-writer role (the single writer of every user's notifications.json), constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny so the privileged writer can read-modify-write {username}/user_settings/notifications.json; without the exclusion the resource-policy Deny would override the writer's identity-policy Allow (architecture.md: resource policies can lock out a role)."
  type        = string
  default     = ""
}

# The three control-plane execution roles below all read USER-SPACE data via their own
# execution role (table-builder/table-share inspect a source folder; data-quality lists +
# probes + profiles one). SPEC-070/092/109 granted each the identity-side s3:GetObject/
# ListBucket — but NONE was ever added to THIS bucket's resource-policy allowlist, so the
# Deny below overrode those Allows and every read 403'd. The gap was invisible until the
# SPEC-111 live smoke run became the first time any of the three actually read a real
# user's files (greenfield, no production users). Constructed cycle-free by the root module
# (a bucket-policy StringNotLike condition only needs the ARN string, so the role need not
# exist at apply time); default "" keeps this module planning standalone.

variable "table_builder_execution_role_arn" {
  description = "SPEC-070/111-fix: ARN of the table-builder shared execution role. Excluded from the user-space bucket policy's data-access Deny so inspect-source can read a personal-space source folder; the identity-side grant alone is overridden by the Deny without this exclusion."
  type        = string
  default     = ""
}

variable "table_share_execution_role_arn" {
  description = "SPEC-092/111-fix: ARN of the table-share shared execution role. Excluded from the user-space bucket policy's data-access Deny so inspect-source/copy-objects can read a personal-space source table's files."
  type        = string
  default     = ""
}

variable "data_quality_execution_role_arn" {
  description = "SPEC-109/111-fix: ARN of the data-quality shared execution role. Excluded from the user-space bucket policy's data-access Deny so inspect-source can list+probe and Athena can profile a personal-space folder; without it the whole pipeline 403s at the first read."
  type        = string
  default     = ""
}

variable "file_send_execution_role_arn" {
  description = "SPEC-164 FR-006: ARN of the file-send shared execution role, constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny so a send can read the sender's personal-space files and write a `user` recipient's shared_files/ inbox. AN EXPLICIT RESOURCE-POLICY DENY BEATS AN IDENTITY-POLICY ALLOW, so without this the plane half-works — every `space` recipient succeeds (the shared-space bucket has no bucket policy) and every `user` recipient fails AccessDenied, which reads like a code bug and is not."
  type        = string
  default     = ""
}

variable "archive_execution_role_arn" {
  description = "SPEC-168 FR-007: ARN of the archive shared execution role, constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny so an archive can read the actor's personal-space files and — from SPEC-169, once every object is confirmed copied — delete them. AN EXPLICIT RESOURCE-POLICY DENY BEATS AN IDENTITY-POLICY ALLOW, so without this the plane half-works: every SHARED-space archive succeeds (the shared-space bucket has no bucket policy) and every PERSONAL one fails AccessDenied, which reads like a code bug and is not."
  type        = string
  default     = ""
}

variable "user_directory_build_role_arn" {
  description = "SPEC-146: ARN of the daily username-directory builder, constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny so it can ListBucket the workspace prefixes and PutObject _directory/usernames.json; without the exclusion the Deny overrides its identity-policy Allow and the write fails with an opaque AccessDenied that looks like an IAM problem and is not (#241)."
  type        = string
  default     = ""
}
