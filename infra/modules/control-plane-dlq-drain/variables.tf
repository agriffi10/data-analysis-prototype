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
  description = "The request-DLQ ARNs to drain — the drain's ONLY SQS read scope, and the DLQ_ARNS the scheduled sweep polls. Constructed strings from the root module, not other modules' outputs, so they are known at plan time (infra/info/deploy-role-iam.md)."
  type        = list(string)
}

variable "logs_queue_arn" {
  description = "Structured-logging queue ARN — the drain sends its events here."
  type        = string
}

variable "logs_queue_url" {
  description = <<-EOT
    Structured-logging queue URL, set as LOGS_QUEUE_URL on the function.

    Optional BY CONSTRUCTION on the Lambda side: cpcommon.observability reads it with
    os.environ.get and never config._require, so a drain deployed without it logs to stdout
    instead of failing at cold start. Passed here so it is set in practice.
  EOT
  type        = string
}

variable "notifications_queue_arn" {
  description = "notifications FIFO queue ARN — the drain's ONLY sqs:SendMessage scope."
  type        = string
}

variable "notifications_queue_url" {
  description = "notifications FIFO queue URL — the drain's NOTIFICATIONS_QUEUE_URL."
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
  description = "Not used by the drain. Required by the cpcommon layer's config, which resolves on first READ rather than at import — so a missing value is no longer a cold-start crash but a failure on whichever branch reads it first. STILL SET IT: the union is what any code path in the layer may demand, and 'the function does not use it' is not a reason to remove it."
  type        = string
}

variable "shared_space_bucket_name" {
  description = "Not used by the drain. See user_space_bucket_name for why it is set anyway."
  type        = string
}

variable "admin_bucket_name" {
  description = "Not used by the drain. See user_space_bucket_name for why it is set anyway."
  type        = string
}

variable "athena_workgroup" {
  description = "The drain runs no queries. See user_space_bucket_name for why it is set anyway."
  type        = string
}
