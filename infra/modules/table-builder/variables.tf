# ── table-builder module variables ────────────────────────────────
# Cross-module ARNs are CONSTRUCTED STRINGS from root locals, never another module's output,
# so they are known at plan time and this module plans standalone. README.md.

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
  description = "Name of the user-space bucket (Bucket 1). Source data for personal-space tables; the inspect-source / infer-schema / execute-ddl roles read it (env USER_SPACE_BUCKET). No bucket is created here."
  type        = string
}

variable "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). Source data for shared-space tables; the inspect-source / infer-schema / execute-ddl roles read it (env SHARED_SPACE_BUCKET). No bucket is created here."
  type        = string
}

variable "admin_bucket_name" {
  description = "Name of the existing analytics admin bucket. The shared-spaces registry (for shared authorization) and the Athena results prefix live here. No bucket is created here."
  type        = string
}

variable "athena_workgroup" {
  description = "Athena workgroup the execute-ddl verb runs the CREATE DDL in. Carried as a foundation variable so the module's interface is stable across the arc."
  type        = string
  default     = ""
}

variable "dlq_max_receive_count" {
  description = "Redrive maxReceiveCount on the FIFO request queue → DLQ (a poison request lands in the DLQ after this many failed deliveries)."
  type        = number
  default     = 3
}

# ── Request contract + validate-authorize ──────────────────────────

# ── Outcome notifications (trusted producer of the inbox) ─────────────

variable "logs_queue_arn" {
  description = "ARN of the structured-logging queue — scopes the execution role's sqs:SendMessage for log events."
  type        = string
  default     = ""
}

variable "logs_queue_url" {
  description = "URL of the structured-logging queue, set as LOGS_QUEUE_URL on every verb Lambda. Optional BY CONSTRUCTION on the Lambda side (cpcommon.observability uses os.environ.get, never config._require), so a verb missing it logs to stdout rather than crashing the plane at cold start."
  type        = string
  default     = ""
}

variable "notifications_queue_arn" {
  description = "ARN of the notifications FIFO queue. Scopes each verb role's sqs:SendMessage grant (the ONLY notifications-pipeline action they get). Constructed-string local from root; default \"\" keeps the module standalone-plannable."
  type        = string
  default     = ""
}

variable "notifications_queue_url" {
  description = "URL of the notifications FIFO queue — every verb Lambda's NOTIFICATIONS_QUEUE_URL env (best-effort emit target; unset ⇒ emit is a logged no-op)."
  type        = string
  default     = ""
}
