# ── shared-spaces module variables (SPEC-050) ────────────────────────────────
# Bounded-context module for Bucket 2 (the shared-space bucket) and the async
# provisioning control plane (SQS → EventBridge Pipe → Step Function → Lambda).
# Resource names are computed in the root module (like the user-space / admin
# buckets) and passed in, so naming lives in one place and base's deploy policy
# can be scoped to the same ARNs without a dependency cycle.
#
# SPEC-050 is FOUNDATION ONLY — the plumbing, no access model and no action
# semantics. Cross-module ARNs are CONSTRUCTED STRINGS (passed from root locals),
# never another module's output, so they are known at plan time (architecture.md
# "unknown ARN in list" trap) and this module plans standalone.

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
  description = "Name of the existing analytics admin bucket (SPEC-032). The registry lives under its shared-spaces/ prefix; the orchestrator role is scoped to that prefix only. No new bucket is created here."
  type        = string
}

variable "athena_workgroup" {
  description = "SPEC-125: the shared portal Athena workgroup name. The shared-space verbs never call Athena — this is here because the cpcommon layer they attach requires ATHENA_WORKGROUP. SPEC-156 FR-004 moved that from import to FIRST READ, so a verb missing it no longer crashes at COLD START (the table-builder break, PR #196) but fails on whichever branch reads it. \"No verb calls Athena\" is not a reason to remove it — the union is what any code path in the layer may demand."
  type        = string
}

variable "app_url" {
  description = "Public URL of the deployed app. Added to the shared-space bucket CORS allowed-origins alongside local dev; empty = localhost only."
  type        = string
  default     = ""
}

variable "user_space_bucket_name" {
  description = "SPEC-051: name of the user-space bucket (Bucket 1). The orchestrator writes each member's per-user cache to {username}/user_settings/shared-connections.json here (env USER_SPACE_BUCKET + scoped in the orchestrator policy)."
  type        = string
}

# ── SPEC-056 access model ────────────────────────────────────────────────────

variable "max_shared_memberships" {
  description = "SPEC-056: number of membership slots — drives the portal-role policy's ten templated S3/Glue statements scoped to the shared_space_k principal tag. Single source is the root variable of the same name."
  type        = number
  default     = 10
}

variable "portal_role_name" {
  description = "SPEC-056: name of the shared portal role (SPEC-011) this module attaches the membership inline policy (slots + sqs:SendMessage + shared delete-denies) to, by name — mirrors how the analytics module attaches its portal policy."
  type        = string
}

variable "user_pool_id" {
  description = "SPEC-056: Cognito User Pool ID — passed to the control-plane Lambdas (env COGNITO_USER_POOL_ID) so the validate-authorize Lambda can verify caller ID tokens against the pool JWKS (trusted-actor binding, SPEC-062)."
  type        = string
  default     = ""
}

variable "app_client_id" {
  description = "SPEC-056: Cognito SPA app client ID — the ID token audience the validate-authorize Lambda checks when verifying the caller's token (env COGNITO_APP_CLIENT_ID)."
  type        = string
  default     = ""
}

# ── SPEC-061: notifications producer (the first trusted producer) ─────────────

variable "logs_queue_arn" {
  description = "SPEC-134: ARN of the structured-logging queue — scopes the orchestrator role's sqs:SendMessage for log events. Empty = the grant resolves to nothing and events fall back to stdout."
  type        = string
  default     = ""
}

variable "logs_queue_url" {
  description = <<-EOT
    SPEC-134: URL of the structured-logging queue, set as LOGS_QUEUE_URL on every verb Lambda.

    Optional BY CONSTRUCTION on the Lambda side: cpcommon.observability reads it with
    os.environ.get and never config._require, so a verb deployed without it logs to stdout
    rather than crashing a whole control plane at cold start (PR #196 — the exact break this
    plane suffered when a shared layer's import-time _require went unmet).
  EOT
  type        = string
  default     = ""
}

variable "notifications_queue_arn" {
  description = "SPEC-061: ARN of the SPEC-058 notifications FIFO queue. Constructed string from root (not module.notifications' output) so this module plans standalone — scopes the orchestrator role's sqs:SendMessage (trusted producer, the notifications queue ARN only). Empty = notifications not wired."
  type        = string
  default     = ""
}

variable "notifications_queue_url" {
  description = "SPEC-061: URL of the SPEC-058 notifications FIFO queue. Passed to every verb Lambda as NOTIFICATIONS_QUEUE_URL; the shared emit helper SendMessages a `create` notification here at each lifecycle terminal outcome. Empty = emit is a logged no-op (module stays independently deployable)."
  type        = string
  default     = ""
}

# ── TBAC fix (SPEC-070/111): control-plane data-location on the shared bucket ──

variable "control_plane_execution_role_arns" {
  description = "ARNs of the shared control-plane execution roles (table-builder / table-share / data-quality) granted DATA_LOCATION_ACCESS on the shared bucket so they can CREATE tables over shared-space prefixes. LF-Tags cover DB/table resources but not S3 locations, so the location grant is here while the `portal-managed` tag + tag-policy grants live in the analytics module. Constructed strings from root; empty keeps the module standalone-plannable."
  type        = list(string)
  default     = []
}
