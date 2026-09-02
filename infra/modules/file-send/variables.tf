# ── file-send module variables ────────────────────────────────────
# ITS OWN PLANE, NOT A MODE OF TABLE SHARE: the two share an ALGORITHM (cpcommon.transfer) and
# nothing else, and folding them would put one queue and one DLQ under two unrelated features.
#
# Cross-module ARNs are CONSTRUCTED STRINGS from root locals, so they are known at plan time
# and this module plans standalone. README.md.

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

variable "user_pool_id" {
  description = "Cognito User Pool ID — carried as env COGNITO_USER_POOL_ID for the recipient-existence check (AdminGetUser/ListUsers), and used to build the pool ARN scoping that grant. It is NOT a cpcommon required variable: the planes stopped verifying tokens, so cpcommon reads it lazily through config.require and only the three planes that resolve a user set it."
  type        = string
  default     = ""
}

variable "admin_bucket_name" {
  description = "Name of the existing analytics admin bucket. The shared-spaces registry read for source authorization + recipient-space existence lives here. No bucket is created by this module."
  type        = string
  default     = ""
}

variable "user_space_bucket_name" {
  description = "Name of the user-space bucket (Bucket 1). A personal source resolves here, and a `user` recipient's inbox is written here. Set as USER_SPACE_BUCKET on every verb; no S3 grant on it is issued at this stage. No bucket is created by this module."
  type        = string
  default     = ""
}

variable "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). A shared source resolves here, and a `space` recipient's inbox is written here. Set as SHARED_SPACE_BUCKET on every verb; no S3 grant on it is issued at this stage. No bucket is created by this module."
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

variable "lambda_image_repository_url" {
  description = "Registry URI of the fleet's one container image, from module.lambda_image. Every function in this module runs that image and differs only by its command."
  type        = string
}

variable "lambda_image_tag" {
  description = "The commit sha this module's functions are CREATED from. Ignored after creation — CI re-points every function with update-function-code on each deploy — but it must be a tag the registry already holds, or CreateFunction fails."
  type        = string
}
