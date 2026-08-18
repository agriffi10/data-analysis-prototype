# ── file-send module variables ────────────────────────────────────
# Bounded-context module for the "send files to another person or space" control
# plane: a DEDICATED FIFO SQS → EventBridge Pipe → Step Function pipeline running
# single-task verb Lambdas on ONE shared execution role. Mirrors the table-share
# control-plane PATTERN (not its resources); decision record: docs/architecture.md
# (Control Planes -> Send Files).
#
# ITS OWN PLANE, NOT A MODE OF TABLE SHARE. The two features share an ALGORITHM
# (cpcommon.transfer) and nothing else — different request contract,
# different authorization question, different failure vocabulary. Folding them
# together would put one queue and one DLQ under two unrelated user features, and a
# malformed send would dead-letter someone's table share.
#
# Is FOUNDATION + THE FRONT DOOR: plumbing, the request contract and
# validate-authorize. Nothing is listed, planned or copied. Cross-module
# ARNs are CONSTRUCTED STRINGS (passed from root locals), never another module's
# output, so they are known at plan time (architecture.md "unknown ARN in list" trap)
# and this module plans standalone.

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (e.g. dat)."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-file-send-validate-authorize)."
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

variable "dlq_max_receive_count" {
  description = "Redrive maxReceiveCount on the FIFO request queue → DLQ (a poison request lands in the DLQ after this many failed deliveries, where the drain turns it into a user notification)."
  type        = number
  default     = 3
}

variable "portal_role_name" {
  description = "Name of the shared portal role this module attaches the browser's sqs:SendMessage (file-send queue only) inline policy to, by name — mirrors the table-builder/table-share/notifications modules. No cross-prefix S3 write is ever granted to a user."
  type        = string
}

variable "user_pool_id" {
  description = "Cognito User Pool ID — passed to validate-authorize (env COGNITO_USER_POOL_ID) for offline ID-token verification, and used to build the pool ARN scoping the execution role's recipient-existence check (AdminGetUser/ListUsers)."
  type        = string
  default     = ""
}

variable "app_client_id" {
  description = "Cognito SPA app client ID — the ID-token audience validate-authorize checks (env COGNITO_APP_CLIENT_ID)."
  type        = string
  default     = ""
}

variable "admin_bucket_name" {
  description = "Name of the existing analytics admin bucket. The shared-spaces registry read for source authorization + recipient-space existence lives here. No bucket is created by this module."
  type        = string
  default     = ""
}

variable "user_space_bucket_name" {
  description = "Name of the user-space bucket (Bucket 1). A personal source resolves here, and a `user` recipient's inbox is written here by SPEC-166. Set as USER_SPACE_BUCKET on every verb; no S3 grant on it is issued at this stage. No bucket is created by this module."
  type        = string
  default     = ""
}

variable "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). A shared source resolves here, and a `space` recipient's inbox is written here by SPEC-166. Set as SHARED_SPACE_BUCKET on every verb; no S3 grant on it is issued at this stage. No bucket is created by this module."
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
  description = "URL of the notifications FIFO queue — the verbs' NOTIFICATIONS_QUEUE_URL env (optional in fscommon.config: unset makes every emit a logged no-op)."
  type        = string
  default     = ""
}
