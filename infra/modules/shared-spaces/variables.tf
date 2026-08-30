# ── shared-spaces module variables ────────────────────────────────
# Resource names are computed in the ROOT module and passed in, so naming lives in one place
# and base's deploy policy can scope to the same ARNs without a cycle. Cross-module ARNs are
# CONSTRUCTED STRINGS, so they are known at plan time. README.md.

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (e.g. dat)."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-shared-space-create)."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to build the SQS / Pipes / Step Functions / Lambda / Glue / log-group ARNs in the orchestrator and deploy-time policies."
  type        = string
}

variable "account_id" {
  description = "AWS account ID — used to build the orchestrator role's Glue catalog/database/table, Cognito User Pool, Lambda, and log-group ARNs."
  type        = string
}

variable "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). Computed by the root module (default {project_name}-prod-shared-space). Globally unique."
  type        = string
}

variable "athena_admin_bucket_name" {
  description = "Name of the existing analytics admin bucket. The registry lives under its shared-spaces/ prefix; the orchestrator role is scoped to that prefix only. No new bucket is created here."
  type        = string
}

variable "athena_workgroup" {
  description = "The shared portal Athena workgroup name. The shared-space verbs never call Athena — this is here because the cpcommon layer they attach requires ATHENA_WORKGROUP. That read happens on FIRST ACCESS rather than at import, so a verb missing it no longer crashes at COLD START but fails on whichever branch reads it. \"No verb calls Athena\" is not a reason to remove it — the union is what any code path in the layer may demand."
  type        = string
}

variable "app_url" {
  description = "Public URL of the deployed app. Added to the shared-space bucket CORS allowed-origins alongside local dev; empty = localhost only."
  type        = string
  default     = ""
}

variable "user_space_bucket_name" {
  description = "Name of the user-space bucket (Bucket 1). The orchestrator writes each member's per-user cache to {username}/user_settings/shared-connections.json here (env USER_SPACE_BUCKET + scoped in the orchestrator policy)."
  type        = string
}

# ── Access model ────────────────────────────────────────────────────

variable "max_shared_memberships" {
  description = "Number of membership slots — drives the portal-role policy's ten templated S3/Glue statements scoped to the shared_space_k principal tag. Single source is the root variable of the same name."
  type        = number
  default     = 10
}

variable "portal_role_name" {
  description = "Name of the shared portal role this module attaches the membership inline policy (slots + sqs:SendMessage + shared delete-denies) to, by name — mirrors how the analytics module attaches its portal policy."
  type        = string
}

variable "user_pool_id" {
  description = "Cognito User Pool ID — carried as env COGNITO_USER_POOL_ID because the orchestrator looks members up (AdminGetUser). It is NOT a cpcommon required variable: the planes stopped verifying tokens, so only the three that resolve a user still set it, and cpcommon reads it lazily through config.require."
  type        = string
  default     = ""
}

# ── Notifications producer (the first trusted producer) ─────────────

variable "logs_queue_arn" {
  description = "ARN of the structured-logging queue — scopes the orchestrator role's sqs:SendMessage for log events. Empty = the grant resolves to nothing and events fall back to stdout."
  type        = string
  default     = ""
}

variable "logs_queue_url" {
  description = <<-EOT
    URL of the structured-logging queue, set as LOGS_QUEUE_URL on every verb Lambda.

    Optional BY CONSTRUCTION on the Lambda side: cpcommon.observability reads it with
    os.environ.get and never config._require, so a verb deployed without it logs to stdout
    rather than crashing a whole control plane at cold start (the exact break this
    plane suffered when a shared layer's import-time _require went unmet).
  EOT
  type        = string
  default     = ""
}

variable "notifications_queue_arn" {
  description = "ARN of the notifications FIFO queue. Constructed string from root (not module.notifications' output) so this module plans standalone — scopes the orchestrator role's sqs:SendMessage (trusted producer, the notifications queue ARN only). Empty = notifications not wired."
  type        = string
  default     = ""
}

variable "notifications_queue_url" {
  description = "URL of the notifications FIFO queue. Passed to every verb Lambda as NOTIFICATIONS_QUEUE_URL; the shared emit helper SendMessages a `create` notification here at each lifecycle terminal outcome. Empty = emit is a logged no-op (module stays independently deployable)."
  type        = string
  default     = ""
}

# ── TBAC fix: control-plane data-location on the shared bucket ──

variable "control_plane_execution_role_arns" {
  description = "ARNs of the shared control-plane execution roles (table-builder / table-share / data-quality) granted DATA_LOCATION_ACCESS on the shared bucket so they can CREATE tables over shared-space prefixes. LF-Tags cover DB/table resources but not S3 locations, so the location grant is here while the `portal-managed` tag + tag-policy grants live in the analytics module. Constructed strings from root; empty keeps the module standalone-plannable."
  type        = list(string)
  default     = []
}

variable "spa_origin" {
  description = "Origin serving the container SPA (https://host), allowlisted for CORS so a presigned URL minted by the API can be redeemed from it. Empty contributes no entry, matching app_url's idiom."
  type        = string
  default     = ""
}
