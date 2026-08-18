# ── notifications module variables ────────────────────────────────
# Bounded-context module for the per-user notifications inbox WRITE side: a FIFO
# SQS queue that triggers a single notifications-writer Lambda directly (SQS
# event-source mapping — no Pipe, no Step Function). The writer is the only writer
# of each user's {username}/user_settings/notifications.json in the EXISTING
# user-space bucket (no new bucket).
#
# Standalone-deployable like module.analytics / module.shared_spaces: every
# cross-module value is a name/id passed from the root module, and cross-module
# ARNs are CONSTRUCTED STRINGS in locals.tf (known at plan time — architecture.md
# "unknown ARN in list" trap), so this module plans without other modules' outputs.

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (e.g. dat)."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-notifications-writer)."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to build the SQS / Lambda / log-group ARNs and the Cognito JWKS issuer in the writer policy + env."
  type        = string
}

variable "account_id" {
  description = "AWS account ID — used to build the Lambda and log-group ARNs."
  type        = string
}

variable "user_space_bucket_name" {
  description = "Name of the user-space bucket (Bucket 1). The writer reads/writes each user's {username}/user_settings/notifications.json here (env USER_SPACE_BUCKET + scoped in the writer policy). No new bucket is created."
  type        = string
}

variable "portal_role_name" {
  description = "Name of the shared portal role (SPEC-011, created in module.data) this module attaches the sqs:SendMessage inline policy to, by name — mirrors how the analytics / shared-spaces modules attach their portal policies."
  type        = string
}

variable "user_pool_id" {
  description = "Cognito User Pool ID — passed to the writer Lambda (env COGNITO_USER_POOL_ID) so it can verify caller ID tokens against the pool JWKS for user-originated actions (actor binding, FR-005)."
  type        = string
  default     = ""
}

variable "app_client_id" {
  description = "Cognito SPA app client ID — the ID-token audience the writer Lambda checks when verifying the caller's token (env COGNITO_APP_CLIENT_ID)."
  type        = string
  default     = ""
}

variable "notifications_max" {
  description = "Writer-side cap on the inbox size — after each action the document is capped to the most-recent N by timestamp (newest kept). Passed to the Lambda as env NOTIFICATIONS_MAX."
  type        = number
  default     = 200
}

variable "dlq_max_receive_count" {
  description = "redrive maxReceiveCount — a request that fails this many times (schema-invalid, forged token, etc.) moves from the request queue to the DLQ."
  type        = number
  default     = 3
}

# ── SPEC-137 structured logging ──────────────────────────────────────────────

variable "logs_queue_arn" {
  description = "Structured-logging queue ARN — the writer's ONLY sqs:SendMessage scope. The writer imports only `observability` from the cpcommon layer, so no cpcommon.config variable joins this pair."
  type        = string
}

variable "logs_queue_url" {
  description = <<-EOT
    Structured-logging queue URL, set as LOGS_QUEUE_URL on the writer.

    Optional BY CONSTRUCTION on the Lambda side: cpcommon.observability reads it with
    os.environ.get and never config._require, so a writer deployed without it logs to
    stdout instead of failing at cold start. Passed here so it is set in
    practice.
  EOT
  type        = string
}
