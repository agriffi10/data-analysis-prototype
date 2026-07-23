variable "project_name" {
  description = "Project name prefix for all resource names."
  type        = string
}

variable "environment" {
  description = "Environment segment (prod)."
  type        = string
}

variable "aws_region" {
  description = "AWS region."
  type        = string
}

variable "account_id" {
  description = "AWS account id, for constructing ARNs at plan time."
  type        = string
}

variable "dlq_arns" {
  description = "The request-DLQ ARNs to drain — the drain's ONLY SQS read scope, and the DLQ_ARNS the scheduled sweep polls. Constructed strings from the root module, not other modules' outputs, so they are known at plan time (architecture.md 'unknown ARN in list')."
  type        = list(string)
}

variable "logs_queue_arn" {
  description = "Structured-logging queue ARN — the drain sends its events here (SPEC-133 FR-007)."
  type        = string
}

variable "logs_queue_url" {
  description = <<-EOT
    Structured-logging queue URL, set as LOGS_QUEUE_URL on the function.

    Optional BY CONSTRUCTION on the Lambda side: cpcommon.observability reads it with
    os.environ.get and never config._require, so a drain deployed without it logs to stdout
    instead of failing at cold start (PR #196). Passed here so it is set in practice.
  EOT
  type        = string
}

variable "notifications_queue_arn" {
  description = "SPEC-058 notifications FIFO queue ARN — the drain's ONLY sqs:SendMessage scope."
  type        = string
}

variable "notifications_queue_url" {
  description = "SPEC-058 notifications FIFO queue URL — the drain's NOTIFICATIONS_QUEUE_URL."
  type        = string
}

variable "user_pool_id" {
  description = "Cognito User Pool id — the JWKS issuer the drain verifies dead-lettered tokens against."
  type        = string
}

variable "app_client_id" {
  description = "Cognito app client id — the audience the drain verifies against."
  type        = string
}

variable "user_space_bucket_name" {
  description = "Required by the cpcommon layer's import-time config._require, not used by the drain. Every function attaching cpcommon needs the UNION of its required env or it crashes at COLD START (PR #196)."
  type        = string
}

variable "shared_space_bucket_name" {
  description = "Required by the cpcommon layer's import-time config._require (see user_space_bucket_name)."
  type        = string
}

variable "admin_bucket_name" {
  description = "Required by the cpcommon layer's import-time config._require (see user_space_bucket_name)."
  type        = string
}

variable "athena_workgroup" {
  description = "Required by the cpcommon layer's import-time config._require (see user_space_bucket_name). The drain runs no queries."
  type        = string
}
