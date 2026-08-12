# ── archive module variables (SPEC-168) ──────────────────────────────────────
# Bounded-context module for the "put it away" control plane: a DEDICATED FIFO SQS →
# EventBridge Pipe → Step Function pipeline running single-task verb Lambdas on ONE
# shared execution role, plus the archive bucket itself. Mirrors the file-send
# control-plane PATTERN (not its resources); decision record: docs/architecture.md
# (Control Planes -> Archive).
#
# ONE PLANE SERVES BOTH ARCHIVE AND RESTORE, branching on `mode` in the request. That
# mirrors SPEC-143's create/refresh branch on the table-builder machine rather than
# standing up a sixth module: the two verbs share the bucket, the execution role, the
# key layout and the receipt, and a restore is meaningless without the archive that
# produced it.
#
# SPEC-168 is FOUNDATION + THE VAULT + THE FRONT DOOR: the bucket, the plumbing, the
# request contract and validate-authorize. Nothing is listed, copied or deleted
# (SPEC-169), and nothing about restore exists yet (SPEC-170/171). Cross-module ARNs
# are CONSTRUCTED STRINGS (passed from root locals), never another module's output, so
# they are known at plan time (architecture.md "unknown ARN in list" trap) and this
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
  description = "SPEC-168 FR-001: name of the archive bucket (Bucket 5) THIS MODULE CREATES. Computed in root locals so the deploy policy can be scoped to its ARN without a cycle, and overridable there because S3 bucket names are globally unique. It is the one bucket the browser has no relationship with at all: no CORS, absent from the CSP connect-src, and the portal role holds zero statements naming it."
  type        = string
}

variable "archive_retention_days" {
  description = "SPEC-168 FR-001: days after creation at which EVERY object in the archive bucket expires. 2557 = 7 years. A CEILING, not a WORM floor — Object Lock is out of scope (it requires versioning, deferred by decision 2026-08-03, and in compliance mode would make SPEC-171's archive cleanup impossible)."
  type        = number
  default     = 2557
}

variable "deploy_role_arn" {
  description = "SPEC-168 FR-001: ARN of the GitHub Actions deploy role, excluded from the archive bucket policy's Deny. Without the exclusion the deploy role cannot HeadBucket, `tofu refresh` sees the bucket as deleted, and every plan proposes a destructive recreate (the recorded user-space-bucket lesson)."
  type        = string
  default     = ""
}

variable "execution_role_arn" {
  description = "SPEC-168 FR-001: ARN of THIS module's shared execution role, as a CONSTRUCTED STRING from root locals rather than the resource attribute. The bucket policy is a StringNotLike condition, which only needs the ARN string — and taking the resource attribute would make the policy depend on the role, which is fine, while taking it from root keeps ONE construction of the name shared with the user-space allowlist entry."
  type        = string
  default     = ""
}

variable "dlq_max_receive_count" {
  description = "Redrive maxReceiveCount on the FIFO request queue → DLQ (a poison request lands in the DLQ after this many failed deliveries, where SPEC-126's drain turns it into a user notification)."
  type        = number
  default     = 3
}

variable "portal_role_name" {
  description = "SPEC-168 FR-007: name of the shared portal role (SPEC-011) this module attaches the browser's sqs:SendMessage (archive queue only) inline policy to, by name — mirrors the file-send/table-share/notifications modules. THE BROWSER'S ONLY POSITIVE ARCHIVE PRIVILEGE. It is never granted anything on the archive bucket."
  type        = string
}

variable "user_pool_id" {
  description = "SPEC-168 FR-005: Cognito User Pool ID — passed to validate-authorize (env COGNITO_USER_POOL_ID) for offline ID-token verification."
  type        = string
  default     = ""
}

variable "app_client_id" {
  description = "SPEC-168 FR-005: Cognito SPA app client ID — the ID-token audience validate-authorize checks (env COGNITO_APP_CLIENT_ID)."
  type        = string
  default     = ""
}

variable "admin_bucket_name" {
  description = "SPEC-168 FR-005: name of the existing analytics admin bucket (SPEC-032). The shared-spaces registry read for source authorization lives here, read-only. No bucket of this name is created by this module."
  type        = string
  default     = ""
}

variable "user_space_bucket_name" {
  description = "SPEC-168: name of the user-space bucket (Bucket 1, SPEC-013). A personal source resolves here and its receipt is written here by SPEC-169. Set as USER_SPACE_BUCKET on every verb; no S3 grant on it is issued at this stage."
  type        = string
  default     = ""
}

variable "shared_space_bucket_name" {
  description = "SPEC-168: name of the shared-space bucket (Bucket 2, SPEC-050). A shared source resolves here and its receipt is written here by SPEC-169. Set as SHARED_SPACE_BUCKET on every verb; no S3 grant on it is issued at this stage."
  type        = string
  default     = ""
}

variable "logs_queue_arn" {
  description = "SPEC-136 parity: ARN of the structured-logging queue — scopes the execution role's sqs:SendMessage for log events."
  type        = string
  default     = ""
}

variable "logs_queue_url" {
  description = "SPEC-136 parity: URL of the structured-logging queue, set as LOGS_QUEUE_URL on every verb Lambda. Optional BY CONSTRUCTION on the Lambda side (os.environ.get, never config._require), so a verb missing it logs to stdout rather than crashing the plane at cold start (PR #196)."
  type        = string
  default     = ""
}

variable "notifications_queue_arn" {
  description = "SPEC-152: ARN of the SPEC-058 notifications FIFO queue — scopes the shared execution role's sqs:SendMessage to that queue ONLY (the pre-verb failure notification, best-effort). Constructed string from root (known at plan time); empty keeps this module standalone."
  type        = string
  default     = ""
}

variable "notifications_queue_url" {
  description = "SPEC-152: URL of the SPEC-058 notifications FIFO queue — the verbs' NOTIFICATIONS_QUEUE_URL env (optional in cpcommon.config: unset makes every emit a logged no-op)."
  type        = string
  default     = ""
}
