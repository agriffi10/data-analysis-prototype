# ── file-ops module variables ────────────────────────────────────
# Bounded-context module for the file-operations control plane: a DEDICATED FIFO SQS →
# EventBridge Pipe → Step Function pipeline running single-task verb Lambdas on ONE shared
# execution role. Mirrors the shared control-plane PATTERN (not its resources); decision
# record: infra/info/control-plane-shape.md.
#
# THE SEVENTH PLANE, AND THE ONE WHOSE ABSENCE IS FELT DAILY. Recursive folder copy, move
# and delete are the last bulk data operations this product performs in the BROWSER: one
# CopyObject per object in a sequential loop from the user's laptop, with a closed tab
# leaving the operation half-done and no record it ever started.
#
# This module is FOUNDATION + THE FRONT DOOR: the plumbing, the request contract, the
# per-space lock and validate-authorize. Nothing is listed, planned, copied or deleted, and
# the execution role holds no grant on either data bucket. Cross-module ARNs are
# CONSTRUCTED STRINGS (passed from root locals), never another module's output, so they are
# known at plan time and this module plans standalone.

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (e.g. dat)."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-file-ops-validate-authorize)."
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
  description = "Name of the shared portal role this module attaches the browser's sqs:SendMessage (file-ops queue only) inline policy to, by name. No cross-prefix S3 write is ever granted to a user — that the browser cannot write into another user's prefix is why this plane exists."
  type        = string
}

variable "user_pool_id" {
  description = "Cognito User Pool ID — passed to the verbs (env COGNITO_USER_POOL_ID) for offline ID-token verification against the pool's public JWKS. No IAM grant on the pool is issued: this plane verifies a token, it never looks a user up."
  type        = string
  default     = ""
}

variable "app_client_id" {
  description = "Cognito SPA app client ID — the ID-token audience validate-authorize checks (env COGNITO_APP_CLIENT_ID)."
  type        = string
  default     = ""
}

variable "admin_bucket_name" {
  description = "Name of the existing analytics admin bucket. Holds the shared-spaces registry (read, to authorize a shared space) and this plane's per-space locks. No bucket is created by this module."
  type        = string
  default     = ""
}

variable "user_space_bucket_name" {
  description = "Name of the user-space bucket (Bucket 1). A personal space resolves here. Set as USER_SPACE_BUCKET on every verb; NO S3 grant on it is issued at this stage, and a test asserts the rendered policy names no data bucket. No bucket is created by this module."
  type        = string
  default     = ""
}

variable "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). A shared space resolves here. Set as SHARED_SPACE_BUCKET on every verb; no S3 grant on it is issued at this stage. No bucket is created by this module."
  type        = string
  default     = ""
}

variable "logs_queue_arn" {
  description = "ARN of the structured-logging queue — scopes the execution role's sqs:SendMessage for log events."
  type        = string
  default     = ""
}

variable "logs_queue_url" {
  description = "URL of the structured-logging queue, set as LOGS_QUEUE_URL on every verb Lambda. Optional BY CONSTRUCTION on the Lambda side, so a verb missing it logs to stdout rather than crashing the plane at cold start."
  type        = string
  default     = ""
}

variable "notifications_queue_arn" {
  description = "ARN of the notifications FIFO queue — scopes the shared execution role's sqs:SendMessage to that queue ONLY (the pre-verb failure notification, best-effort). Constructed string from root (known at plan time); empty keeps this module standalone."
  type        = string
  default     = ""
}

variable "notifications_queue_url" {
  description = "URL of the notifications FIFO queue — the verbs' NOTIFICATIONS_QUEUE_URL env (optional: unset makes every emit a logged no-op)."
  type        = string
  default     = ""
}
