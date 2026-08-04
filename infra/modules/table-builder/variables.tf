# ── table-builder module variables (SPEC-066) ────────────────────────────────
# Bounded-context module for the "create table from a folder" control plane: a
# DEDICATED FIFO SQS → EventBridge Pipe → Step Function pipeline that orchestrates
# single-task verb Lambdas (validate-authorize → {check-table-absent |
# load-table-definition} → inspect-source → infer-schema → execute-ddl, SPEC-143's two
# branches over one shared spine). Mirrors the shared-spaces control
# plane PATTERN (not its resources), but with PER-VERB least-privilege roles.
#
# SPEC-066 is FOUNDATION ONLY — plumbing + Lambda stubs, no request contract and no
# action semantics (those land in SPEC-067→070). Cross-module ARNs are CONSTRUCTED
# STRINGS (passed from root locals), never another module's output, so they are known
# at plan time (architecture.md "unknown ARN in list" trap) and this module plans
# standalone.

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (e.g. dat)."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-table-builder-infer-schema)."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to build the SQS / Pipes / Step Functions / Lambda / log-group ARNs in the per-verb and deploy-time policies."
  type        = string
}

variable "account_id" {
  description = "AWS account ID — used to build the per-verb roles' Glue / S3 / Lambda / log-group ARNs and the constructed function ARNs."
  type        = string
}

variable "user_space_bucket_name" {
  description = "Name of the user-space bucket (Bucket 1, SPEC-013). Source data for personal-space tables; the inspect-source / infer-schema / execute-ddl roles read it (env USER_SPACE_BUCKET). No bucket is created here."
  type        = string
}

variable "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2, SPEC-050). Source data for shared-space tables; the inspect-source / infer-schema / execute-ddl roles read it (env SHARED_SPACE_BUCKET). No bucket is created here."
  type        = string
}

variable "admin_bucket_name" {
  description = "Name of the existing analytics admin bucket (SPEC-032). The shared-spaces registry (for shared authorization, SPEC-067) and the Athena results prefix (SPEC-070) live here. No bucket is created here."
  type        = string
}

variable "athena_workgroup" {
  description = "SPEC-032 Athena workgroup the execute-ddl verb runs the CREATE DDL in (wired to execute-ddl's env in SPEC-070). Carried as a foundation variable so the module's interface is stable across the arc."
  type        = string
  default     = ""
}

variable "dlq_max_receive_count" {
  description = "Redrive maxReceiveCount on the FIFO request queue → DLQ (a poison request lands in the DLQ after this many failed deliveries)."
  type        = number
  default     = 3
}

# ── SPEC-067: request contract + validate-authorize ──────────────────────────

variable "portal_role_name" {
  description = "SPEC-067: name of the shared portal role (SPEC-011) this module attaches the browser's sqs:SendMessage (table-build queue only) inline policy to, by name — mirrors the notifications/shared-spaces modules."
  type        = string
}

variable "user_pool_id" {
  description = "SPEC-067: Cognito User Pool ID — passed to validate-authorize (env COGNITO_USER_POOL_ID) so it can verify caller ID tokens against the pool JWKS (offline trusted-actor binding)."
  type        = string
  default     = ""
}

variable "app_client_id" {
  description = "SPEC-067: Cognito SPA app client ID — the ID-token audience validate-authorize checks (env COGNITO_APP_CLIENT_ID)."
  type        = string
  default     = ""
}

# ── SPEC-072: outcome notifications (trusted producer of the SPEC-058 inbox) ──

variable "logs_queue_arn" {
  description = "SPEC-135: ARN of the structured-logging queue — scopes the execution role's sqs:SendMessage for log events."
  type        = string
  default     = ""
}

variable "logs_queue_url" {
  description = "SPEC-135: URL of the structured-logging queue, set as LOGS_QUEUE_URL on every verb Lambda. Optional BY CONSTRUCTION on the Lambda side (cpcommon.observability uses os.environ.get, never config._require), so a verb missing it logs to stdout rather than crashing the plane at cold start (PR #196)."
  type        = string
  default     = ""
}

variable "notifications_queue_arn" {
  description = "SPEC-072: ARN of the SPEC-058 notifications FIFO queue. Scopes each verb role's sqs:SendMessage grant (the ONLY notifications-pipeline action they get). Constructed-string local from root; default \"\" keeps the module standalone-plannable."
  type        = string
  default     = ""
}

variable "notifications_queue_url" {
  description = "SPEC-072: URL of the SPEC-058 notifications FIFO queue — every verb Lambda's NOTIFICATIONS_QUEUE_URL env (best-effort emit target; unset ⇒ emit is a logged no-op)."
  type        = string
  default     = ""
}
