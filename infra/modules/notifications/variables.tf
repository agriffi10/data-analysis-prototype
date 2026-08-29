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

variable "portal_role_unique_id" {
  description = "The portal role's IAM unique ID (AROA…), set on the writer as NOTIFICATIONS_UNTRUSTED_SENDER_ID. SQS stamps SenderId as {unique_id}:{session-name}; the writer refuses a `create` whose role-id half matches this, which is what makes trusted-producer-only true of the running system rather than only of the design. NO DEFAULT ON PURPOSE: a root that forgets to wire it must fail at plan, because the writer's own fail-closed would otherwise deploy a function that silently refuses every notification in the product."
  type        = string

  # A missing wire fails at plan (no default); a WRONG one would not. The role's ARN and its
  # name are the plausible mis-wires, and either would validate clean then never match at
  # runtime — which reads exactly like a control that works.
  validation {
    condition     = can(regex("^AROA[A-Z0-9]+$", var.portal_role_unique_id))
    error_message = "portal_role_unique_id must be an IAM role unique ID (AROA…) — not the role's name and not its ARN, neither of which SenderId carries."
  }
}

variable "user_pool_id" {
  description = "Cognito User Pool ID — passed to the writer Lambda (env COGNITO_USER_POOL_ID) so it can verify caller ID tokens against the pool JWKS for user-originated actions (actor binding)."
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

# ── Structured logging ────────────────────────────────────────────────────────

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
