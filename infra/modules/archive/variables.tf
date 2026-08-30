# ── archive module variables ──────────────────────────────────────
# Bounded-context module for the "put it away" control plane: a DEDICATED FIFO SQS →
# EventBridge Pipe → Step Function pipeline running single-task verb Lambdas on ONE
# shared execution role, plus the archive bucket itself. Mirrors the file-send
# control-plane PATTERN (not its resources); decision record: lambdas/info/planes/archive.md
# (Control Planes -> Archive).
#
# ONE PLANE SERVES BOTH ARCHIVE AND RESTORE, branching on `mode` in the request. That
# mirrors the create/refresh branch on the table-builder machine rather than
# standing up a sixth module: the two verbs share the bucket, the execution role, the
# key layout and the receipt, and a restore is meaningless without the archive that
# produced it.
#
# FOUNDATION, THE VAULT AND THE FRONT DOOR: the bucket, the plumbing, the
# request contract and validate-authorize. Nothing is listed, copied or deleted
# Cross-module ARNs
# are CONSTRUCTED STRINGS (passed from root locals), never another module's output, so
# they are known at plan time (infra/info/deploy-role-iam.md) and this
# module plans standalone.

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (e.g. dat)."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-archive-validate-authorize)."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to build the SQS / Pipes / Step Functions / Lambda / log-group ARNs in the module's policies."
  type        = string
}

variable "account_id" {
  description = "AWS account ID — used to build the shared execution role's log-group ARNs and the constructed function ARNs."
  type        = string
}

variable "archive_bucket_name" {
  description = "Name of the archive bucket (Bucket 5) THIS MODULE CREATES. Computed in root locals so the deploy policy can be scoped to its ARN without a cycle, and overridable there because S3 bucket names are globally unique. It is the one bucket the browser has no relationship with at all: no CORS, absent from the CSP connect-src, and the portal role holds zero statements naming it."
  type        = string
}

variable "archive_retention_days" {
  description = "Days after creation at which EVERY object in the archive bucket expires. 2557 = 7 years. A CEILING, not a WORM floor — Object Lock is out of scope (it requires versioning, deferred by decision 2026-08-03, and in compliance mode would make the archive cleanup impossible)."
  type        = number
  default     = 2557
}

variable "deploy_role_arn" {
  description = "ARN of the GitHub Actions deploy role, excluded from the archive bucket policy's Deny. Without the exclusion the deploy role cannot HeadBucket, `tofu refresh` sees the bucket as deleted, and every plan proposes a destructive recreate (the recorded user-space-bucket lesson)."
  type        = string
  default     = ""
}

variable "execution_role_arn" {
  description = "ARN of THIS module's shared execution role, as a CONSTRUCTED STRING from root locals rather than the resource attribute. The bucket policy is a StringNotLike condition, which only needs the ARN string — and taking the resource attribute would make the policy depend on the role, which is fine, while taking it from root keeps ONE construction of the name shared with the user-space allowlist entry."
  type        = string
  default     = ""
}

variable "dlq_max_receive_count" {
  description = "Redrive maxReceiveCount on the FIFO request queue → DLQ (a poison request lands in the DLQ after this many failed deliveries, where the drain turns it into a user notification)."
  type        = number
  default     = 3
}

variable "admin_bucket_name" {
  description = "Name of the existing analytics admin bucket. The shared-spaces registry read for source authorization lives here, read-only. No bucket of this name is created by this module."
  type        = string
  default     = ""
}

variable "user_space_bucket_name" {
  description = "Name of the user-space bucket (Bucket 1). A personal source resolves here and its receipt is written here. Set as USER_SPACE_BUCKET on every verb; no S3 grant on it is issued at this stage."
  type        = string
  default     = ""
}

variable "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). A shared source resolves here and its receipt is written here. Set as SHARED_SPACE_BUCKET on every verb; no S3 grant on it is issued at this stage."
  type        = string
  default     = ""
}

variable "logs_queue_arn" {
  description = "ARN of the structured-logging queue — scopes the execution role's sqs:SendMessage for log events."
  type        = string
  default     = ""
}

variable "logs_queue_url" {
  description = "URL of the structured-logging queue, set as LOGS_QUEUE_URL on every verb Lambda. Optional BY CONSTRUCTION on the Lambda side (os.environ.get, never config._require), so a verb missing it logs to stdout rather than crashing the plane at cold start."
  type        = string
  default     = ""
}

variable "notifications_queue_arn" {
  description = "ARN of the notifications FIFO queue — scopes the shared execution role's sqs:SendMessage to that queue ONLY (the pre-verb failure notification, best-effort). Constructed string from root (known at plan time); empty keeps this module standalone."
  type        = string
  default     = ""
}

variable "notifications_queue_url" {
  description = "URL of the notifications FIFO queue — the verbs' NOTIFICATIONS_QUEUE_URL env (optional in cpcommon.config: unset makes every emit a logged no-op)."
  type        = string
  default     = ""
}
