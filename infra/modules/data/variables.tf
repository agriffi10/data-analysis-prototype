variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
}

variable "account_id" {
  description = "AWS account ID, for the user-space bucket policy. Passed from the root rather than read by a data source here: the root calls this module with depends_on, which would defer that read to apply whenever module.base has a change pending, and the whole bucket policy with it."
  type        = string
}

variable "user_space_bucket_name" {
  description = "Name of the user-space S3 bucket (Bucket 1). Computed by the root module (default {project_name}-prod-user-space, overridable via the root user_space_bucket_name variable if the global name is taken)."
  type        = string
}

variable "portal_role_name" {
  description = "Name of the shared portal IAM role. Computed by the root module (default {project_name}-portal-user-role)."
  type        = string
}

variable "deploy_role_arn" {
  description = "ARN of the GitHub Actions deploy role (modules/base). Excluded from the user-space bucket policy's data-access Deny so the IaC principal can HeadBucket/manage the bucket; without it tofu refresh reports false 'deleted' drift and plans a destructive recreate."
  type        = string
}

variable "lf_registration_role_arn" {
  description = "ARN of the analytics Lake Formation registration role (modules/analytics), constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny: LF assumes this role to read the registered location when serving Athena queries, so the explicit Deny would otherwise block its s3:ListBucket/GetObject and queries fail with PERMISSION_DENIED."
  type        = string
}

variable "shared_space_orchestrator_role_arn" {
  description = "ARN of the shared-space orchestrator role, constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny so the privileged pipeline can write each member's per-user cache ({username}/user_settings/shared-connections.json); without the exclusion the resource-policy Deny would override the orchestrator's identity-policy Allow."
  type        = string
  default     = ""
}

variable "notifications_writer_role_arn" {
  description = "ARN of the notifications-writer role (the single writer of every user's notifications.json), constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny so the privileged writer can read-modify-write {username}/user_settings/notifications.json; without the exclusion the resource-policy Deny would override the writer's identity-policy Allow (infra/info/deploy-role-iam.md: resource policies can lock out a role)."
  type        = string
  default     = ""
}

# Every ARN below is a bucket-policy allowlist entry. Root-constructed strings, so the role
# need not exist at apply time; default "" keeps this module planning standalone.
# OMITTING ONE IS A RUNTIME 403 THAT READS AS A CODE BUG — README.md.

variable "table_builder_execution_role_arn" {
  description = "ARN of the table-builder shared execution role. Excluded from the user-space bucket policy's data-access Deny so inspect-source can read a personal-space source folder; the identity-side grant alone is overridden by the Deny without this exclusion."
  type        = string
  default     = ""
}

variable "table_share_execution_role_arn" {
  description = "ARN of the table-share shared execution role. Excluded from the user-space bucket policy's data-access Deny so inspect-source/copy-objects can read a personal-space source table's files."
  type        = string
  default     = ""
}

variable "data_quality_execution_role_arn" {
  description = "ARN of the data-quality shared execution role. Excluded from the user-space bucket policy's data-access Deny so inspect-source can list+probe and Athena can profile a personal-space folder; without it the whole pipeline 403s at the first read."
  type        = string
  default     = ""
}

variable "file_send_execution_role_arn" {
  description = "ARN of the file-send shared execution role, constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny so a send can read the sender's personal-space files and write a `user` recipient's shared_files/ inbox. AN EXPLICIT RESOURCE-POLICY DENY BEATS AN IDENTITY-POLICY ALLOW, so without this the plane half-works — every `space` recipient succeeds (the shared-space bucket has no bucket policy) and every `user` recipient fails AccessDenied, which reads like a code bug and is not."
  type        = string
  default     = ""
}

variable "archive_execution_role_arn" {
  description = "ARN of the archive shared execution role, constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny so an archive can read the actor's personal-space files and — once every object is confirmed copied — delete them. AN EXPLICIT RESOURCE-POLICY DENY BEATS AN IDENTITY-POLICY ALLOW, so without this the plane half-works: every SHARED-space archive succeeds (the shared-space bucket has no bucket policy) and every PERSONAL one fails AccessDenied, which reads like a code bug and is not."
  type        = string
  default     = ""
}

variable "file_ops_execution_role_arn" {
  description = "ARN of the file-operations shared execution role, constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny so the plane can eventually read, copy and delete a personal space's files. IT IS ADDED BEFORE THE PLANE HAS ANY S3 GRANT AT ALL, deliberately: the allowlist is hand-maintained and a plane that skips it is denied at runtime with nothing in the plan to warn it, so the exclusion lands with the role rather than with the first verb that needs it. AN EXPLICIT RESOURCE-POLICY DENY BEATS AN IDENTITY-POLICY ALLOW, which is what makes the omission read like a code bug: every SHARED-space operation would succeed (the shared-space bucket has no bucket policy) and every PERSONAL one fail."
  type        = string
  default     = ""
}

variable "results_conversion_execution_role_arn" {
  description = "ARN of the results-conversion shared execution role, constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny so the plane can read a user's own Athena result object out of the bucket. AN EXPLICIT RESOURCE-POLICY DENY BEATS AN IDENTITY-POLICY ALLOW, so without this every request would fail AccessDenied at the size read however correct the role's own grant is."
  type        = string
  default     = ""
}

variable "user_directory_build_role_arn" {
  description = "ARN of the daily username-directory builder, constructed cycle-free by the root module. Excluded from the user-space bucket policy's data-access Deny so it can ListBucket the workspace prefixes and PutObject _directory/usernames.json; without the exclusion the Deny overrides its identity-policy Allow and the write fails with an opaque AccessDenied that looks like an IAM problem and is not."
  type        = string
  default     = ""
}

variable "api_execution_role_arn" {
  description = "ARN of the API Lambda's execution role, admitted by the portal role's second trust statement so the API can act as its caller. A root-constructed string like every other cross-module role ARN here: a module output would be (known after apply) on any plan where the API role changes, and would order this role's creation behind the API on a fresh account."
  type        = string
}

variable "principal_tag_key" {
  description = "The session-tag key carrying the username. Bounds the trust statement's sts:TagKeys list. NOT threaded into the permission template, which hard-codes the literal, so the agreement is asserted by test instead of made structural."
  type        = string
  default     = "username"
}

variable "max_shared_memberships" {
  description = "Number of shared-space membership slots. Sizes the trust statement's sts:TagKeys list, and is the same variable that sizes the Cognito attributes, the session tags the API stamps and the portal role's shared-space policy."
  type        = number
  default     = 10
}

variable "spa_origin" {
  description = "Origin serving the container SPA (https://host), allowlisted for CORS so a presigned URL minted by the API can be redeemed from it. Empty contributes no entry — compact() drops it rather than sending S3 an empty origin."
  type        = string
  default     = ""
}
