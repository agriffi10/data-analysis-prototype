# ── data-quality module variables ─────────────────────────────────
# Bounded-context module for the "check data quality on a file or folder" control
# plane: a DEDICATED FIFO SQS → EventBridge Pipe → Standard Step Function pipeline
# orchestrating nine single-task verb Lambdas around ONE Athena profile query.
# Mirrors the table-builder/table-share control-plane PATTERN (not their resources).
#
# FOUNDATION ONLY — plumbing + Lambda stubs; no request contract, no
# authorization, no DDL/query logic. Cross-module ARNs are CONSTRUCTED
# STRINGS (passed from root locals), never another module's output, so they are known
# at plan time (architecture.md "unknown ARN in list" trap) and this module plans
# standalone.

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

# ── Buckets (env for every verb; grants land in SPEC-109/111) ─────────────────
# NOTE: these are wired into the COMMON Lambda env now, not because the SPEC-108 stubs
# use them, but because every verb attaches the cpcommon layer and cpcommon/config.py
# requires them. That requirement moved from import to
# FIRST READ, so a verb missing one no longer crashes at cold start (the table-builder
# production break, PR #196) — it fails on whichever branch reads it. The union is still
# what must be set; do not prune one as "unused". No bucket is created here.

variable "user_space_bucket_name" {
  description = "Name of the user-space bucket (Bucket 1). Personal-space sources + the report destination; env USER_SPACE_BUCKET (required by cpcommon.config). Grants land in SPEC-109."
  type        = string
}

variable "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). Shared-space sources + report destination; env SHARED_SPACE_BUCKET (required by cpcommon.config). Grants land in SPEC-109."
  type        = string
}

variable "admin_bucket_name" {
  description = "Name of the existing analytics admin bucket. Holds the shared-spaces registry (shared authorization) and this workgroup's FALLBACK Athena result location; env ADMIN_BUCKET (required by cpcommon.config). No bucket is created here."
  type        = string
}

# ── Cognito (env for every verb; used by cpcommon.auth from SPEC-109) ─────────

variable "user_pool_id" {
  description = "Cognito User Pool ID — env COGNITO_USER_POOL_ID (required by cpcommon.config). validate-authorize verifies caller ID tokens against the pool JWKS from SPEC-109."
  type        = string
  default     = ""
}

variable "app_client_id" {
  description = "Cognito SPA app client ID — env COGNITO_APP_CLIENT_ID (required by cpcommon.config); the ID-token audience validate-authorize checks."
  type        = string
  default     = ""
}

# ── Notifications (SPEC-114 producer; optional by design) ─────────────────────

variable "notifications_queue_arn" {
  description = "SPEC-114: ARN of the SPEC-058 notifications FIFO queue — scopes the execution role's sqs:SendMessage when the producer lands. Constructed-string local from root; default \"\" keeps the module standalone-plannable."
  type        = string
  default     = ""
}

variable "notifications_queue_url" {
  description = "SPEC-114: URL of the SPEC-058 notifications FIFO queue — every verb's NOTIFICATIONS_QUEUE_URL env. OPTIONAL in cpcommon.config by design (unset ⇒ every emit is a logged no-op), so it never fails a cold start."
  type        = string
  default     = ""
}

variable "dlq_max_receive_count" {
  description = "Redrive maxReceiveCount on the FIFO request queue → DLQ (a poison request lands in the DLQ after this many failed deliveries)."
  type        = number
  default     = 3
}

# ── SPEC-109: the browser's enqueue grant ────────────────────────────────────

variable "portal_role_name" {
  description = "SPEC-109 FR-003: name of the shared portal role this module attaches the browser's sqs:SendMessage (data-quality queue ONLY) inline policy to, by name — mirrors the notifications/shared-spaces/table-builder/table-share modules."
  type        = string
}

variable "athena_workgroup" {
  description = "SPEC-111-fix: the SHARED portal Athena workgroup every verb's queries run in — the SAME workgroup table-builder/table-share use. Athena's Lake Formation integration is tied to the workgroup: a dedicated workgroup (SPEC-108's original design) fails LF's Create/Describe checks even when the execution role is an LF admin, because everything LF-governed must run in the one workgroup. Constructed string from root (the portal workgroup name), mirroring table-builder's athena_workgroup input."
  type        = string
}

# ── SPEC-128: structured logging ─────────────────────────────────────────────

variable "logs_queue_arn" {
  description = "ARN of the SPEC-127 logs queue. The execution role gains sqs:SendMessage on this and nothing else."
  type        = string
}

variable "logs_queue_url" {
  description = "URL of the SPEC-127 logs queue, set as LOGS_QUEUE_URL on all nine verbs. Optional by construction (cpcommon.observability reads it with os.environ.get), so a function that somehow misses it logs to stdout rather than crashing at cold start."
  type        = string
}
