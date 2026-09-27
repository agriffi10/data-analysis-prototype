variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (e.g. dat)."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-feedback-writer)."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to build the log-group ARN in the writer policy."
  type        = string
}

variable "account_id" {
  description = "AWS account ID — used to build the log-group ARN."
  type        = string
}

variable "admin_bucket_name" {
  description = "Name of the admin bucket (the analytics module owns it). The writer reads and writes one object per day under feedback/year=YYYY/month=MM/day=DD/feedback_YYYY_MM_DD.json here (env ADMIN_BUCKET + scoped in the writer policy, prefix-scoped to feedback/). No new bucket is created, and no lifecycle rule expires this prefix."
  type        = string
}

variable "dlq_max_receive_count" {
  description = "redrive maxReceiveCount — a submission that fails this many times (a malformed message, an unreadable day object, a lost compare-and-swap race) moves from the request queue to the DLQ. That DLQ is deliberately undrained; see the module README."
  type        = number
  default     = 3
}

# ── Structured logging ────────────────────────────────────────────────────────

variable "logs_queue_arn" {
  description = "Structured-logging queue ARN — the writer's ONLY sqs:SendMessage scope. The writer imports only `observability` from `cpcommon`, so no cpcommon.config variable joins this pair."
  type        = string
}

variable "logs_queue_url" {
  description = <<-EOT
    Structured-logging queue URL, set as LOGS_QUEUE_URL on the writer.

    Optional BY CONSTRUCTION on the Lambda side: cpcommon.observability reads it with
    os.environ.get and never config._require, so a writer deployed without it logs to
    stdout instead of failing at cold start. Passed here so it is set in practice.
  EOT
  type        = string
}

variable "lambda_image_repository_url" {
  description = "Registry URI of the fleet's one container image, from module.lambda_image. Every function in this module runs that image and differs only by its command."
  type        = string
}

variable "lambda_image_tag" {
  description = "The commit sha this module's functions are CREATED from. Ignored after creation — CI re-points every function with update-function-code on each deploy — but it must be a tag the registry already holds, or CreateFunction fails."
  type        = string
}
