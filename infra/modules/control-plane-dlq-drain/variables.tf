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
  description = "The request-DLQ ARNs to drain — the drain's ONLY SQS read scope. Constructed strings from the root module, not other modules' outputs, so they are known at plan time (architecture.md 'unknown ARN in list')."
  type        = list(string)
}

variable "dlq_queue_names" {
  description = "The same queues by name, in the same order as dlq_arns — the event-source mappings key off these so the map is stable across applies."
  type        = list(string)
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
