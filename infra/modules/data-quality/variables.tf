# ── data-quality module variables ─────────────────────────────────
# Cross-module ARNs are CONSTRUCTED STRINGS from root locals, so they are known at plan time
# and this module plans standalone. README.md.

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (e.g. dat)."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-data-quality-inspect-source)."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to build the SQS / Pipes / Step Functions / Lambda / log-group / Athena ARNs in this module's policies."
  type        = string
}

variable "account_id" {
  description = "AWS account ID — used to build the execution role's log-group ARNs, the constructed function ARNs, and the Athena workgroup ARN."
  type        = string
}

# ── Buckets (env for every verb) ─────────────────────────────────────────────
# Wired into the COMMON Lambda env because every verb attaches cpcommon, whose config requires
# them. THE UNION IS WHAT MUST BE SET — do not prune one as "unused". No bucket is created
# here.

variable "user_space_bucket_name" {
  description = "Name of the user-space bucket (Bucket 1). Personal-space sources + the report destination; env USER_SPACE_BUCKET (required by cpcommon.config). "
  type        = string
}

variable "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). Shared-space sources + report destination; env SHARED_SPACE_BUCKET (required by cpcommon.config). "
  type        = string
}

variable "admin_bucket_name" {
  description = "Name of the existing analytics admin bucket. Holds the shared-spaces registry (shared authorization) and this workgroup's FALLBACK Athena result location; env ADMIN_BUCKET (required by cpcommon.config). No bucket is created here."
  type        = string
}

# ── Cognito (env for every verb; used by cpcommon.auth) ─────────────────────

variable "user_pool_id" {
  description = "Cognito User Pool ID — env COGNITO_USER_POOL_ID (required by cpcommon.config). validate-authorize verifies caller ID tokens against the pool JWKS."
  type        = string
  default     = ""
}

variable "app_client_id" {
  description = "Cognito SPA app client ID — env COGNITO_APP_CLIENT_ID (required by cpcommon.config); the ID-token audience validate-authorize checks."
  type        = string
  default     = ""
}

# ── Notifications ─────────────────────

variable "notifications_queue_arn" {
  description = "ARN of the notifications FIFO queue — scopes the execution role's sqs:SendMessage when the producer lands. Constructed-string local from root; default \"\" keeps the module standalone-plannable."
  type        = string
  default     = ""
}

variable "notifications_queue_url" {
  description = "URL of the notifications FIFO queue — every verb's NOTIFICATIONS_QUEUE_URL env. OPTIONAL in cpcommon.config by design (unset ⇒ every emit is a logged no-op), so it never fails a cold start."
  type        = string
  default     = ""
}

variable "dlq_max_receive_count" {
  description = "Redrive maxReceiveCount on the FIFO request queue → DLQ (a poison request lands in the DLQ after this many failed deliveries)."
  type        = number
  default     = 3
}

# ── The browser's enqueue grant ────────────────────────────────────

variable "athena_workgroup" {
  description = "the SHARED portal Athena workgroup every verb's queries run in — the SAME workgroup table-builder/table-share use. Athena's Lake Formation integration is tied to the workgroup: a dedicated workgroup (the original design) fails LF's Create/Describe checks even when the execution role is an LF admin, because everything LF-governed must run in the one workgroup. Constructed string from root (the portal workgroup name), mirroring table-builder's athena_workgroup input."
  type        = string
}

# ── Structured logging ─────────────────────────────────────────────

variable "logs_queue_arn" {
  description = "ARN of the logs queue. The execution role gains sqs:SendMessage on this and nothing else."
  type        = string
}

variable "logs_queue_url" {
  description = "URL of the logs queue, set as LOGS_QUEUE_URL on all nine verbs. Optional by construction (cpcommon.observability reads it with os.environ.get), so a function that somehow misses it logs to stdout rather than crashing at cold start."
  type        = string
}
