# ── results-conversion module variables ──────────────────────────────────
# Bounded-context module for the results-conversion control plane: a DEDICATED FIFO SQS →
# EventBridge Pipe → Standard Step Function pipeline running single-task verb Lambdas on ONE
# shared execution role. Mirrors the shared control-plane PATTERN (not its resources).
#
# THE EIGHTH PLANE. It takes a finished Athena execution and writes its result set into a space
# the actor may write to, in the format they chose. Five verbs: validate-authorize,
# describe-results, convert, notify and notify-failure. Only convert reads bytes, and it is the
# only one with a write grant. Cross-module ARNs are CONSTRUCTED STRINGS (passed from
# root locals), never another module's output, so they are known at plan time and this module
# plans standalone.

variable "project_name" {
  description = "Short name used as a prefix for AWS resource names (e.g. dat)."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment} (e.g. dat-prod-results-conversion-validate-authorize)."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to build the SQS / Pipes / Step Functions / Lambda / log-group / Athena ARNs in the module's policies."
  type        = string
}

variable "account_id" {
  description = "AWS account ID — used to build the shared execution role's log-group ARNs and the constructed workgroup and execution ARNs."
  type        = string
}

variable "dlq_max_receive_count" {
  description = "Redrive maxReceiveCount on the FIFO request queue → DLQ (a poison request lands in the DLQ after this many failed deliveries, where the drain turns it into a user notification)."
  type        = number
  default     = 3
}

variable "admin_bucket_name" {
  description = "Name of the existing analytics admin bucket. Holds the shared-spaces registry, read to authorize a shared destination. No bucket is created by this module."
  type        = string
  default     = ""
}

variable "user_space_bucket_name" {
  description = "Name of the user-space bucket (Bucket 1). A personal destination resolves here, and every result object this plane reads sits under a user's own results folder in it. Set as USER_SPACE_BUCKET on every verb. No bucket is created by this module."
  type        = string
  default     = ""
}

variable "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). A shared destination resolves here. Set as SHARED_SPACE_BUCKET on every verb; no S3 grant on it is issued at this stage. No bucket is created by this module."
  type        = string
  default     = ""
}

variable "athena_workgroup" {
  description = "The SHARED portal Athena workgroup every execution this plane inspects ran in. Scopes the execution role's read-only Athena grant; the plane starts no query of its own."
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
  description = "ARN of the notifications FIFO queue — scopes the shared execution role's sqs:SendMessage to that queue ONLY (every refusal and the pre-verb failure notification). Constructed string from root (known at plan time); empty keeps this module standalone."
  type        = string
  default     = ""
}

variable "notifications_queue_url" {
  description = "URL of the notifications FIFO queue — the verbs' NOTIFICATIONS_QUEUE_URL env (optional: unset makes every emit a logged no-op)."
  type        = string
  default     = ""
}

variable "lambda_image_repository_url" {
  description = "Registry URI of the fleet's one container image, from module.lambda_image. Every function in this module runs that image and differs only by its command."
  type        = string
}

variable "lambda_image_tag" {
  description = "The commit sha this module's functions are CREATED from. Ignored after creation — CI re-points every function with update-function-code on each deploy — but it must be a tag the registry already holds, or CreateFunction fails."
  type        = string
}
