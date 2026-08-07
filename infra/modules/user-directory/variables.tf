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

variable "user_space_bucket_name" {
  description = "User-space bucket (Bucket 1) — the builder lists its top-level common prefixes and publishes the directory into its _directory/ prefix. Also the function's USER_SPACE_BUCKET, which is the ONE variable the builder actually reads."
  type        = string
}

variable "user_space_bucket_arn" {
  description = "User-space bucket ARN — the builder's ListBucket scope and, with the _directory/ prefix appended, its only PutObject scope. A constructed string from the root module, not module.data's output, so it is known at plan time and this module plans standalone."
  type        = string
}

variable "logs_queue_arn" {
  description = "Structured-logging queue ARN — the builder's only sqs:SendMessage scope (SPEC-146 FR-008)."
  type        = string
}

variable "logs_queue_url" {
  description = <<-EOT
    Structured-logging queue URL, set as LOGS_QUEUE_URL on the function.

    Optional BY CONSTRUCTION on the Lambda side: cpcommon.observability reads it with
    os.environ.get and never config._require, so a builder deployed without it logs to stdout
    instead of failing at cold start (PR #196). Passed here so it is set in practice.
  EOT
  type        = string
}

variable "user_pool_id" {
  description = "NOT used by the builder — the directory's source is S3 common prefixes, never Cognito (SPEC-146 FR-001). Required by the cpcommon layer's config, which resolves on first READ rather than at import (SPEC-156 FR-004) — so a missing value is no longer a cold-start crash (PR #196) but a failure on whichever branch reads it first. STILL SET IT: the union is what any code path in the layer may demand, and 'the function does not use it' is not a reason to remove it."
  type        = string
}

variable "app_client_id" {
  description = "The builder makes no Cognito call. See user_pool_id for why it is set anyway."
  type        = string
}

variable "shared_space_bucket_name" {
  description = "The builder never touches Bucket 2 — shared-space prefixes are spaces, not users. See user_pool_id for why it is set anyway."
  type        = string
}

variable "admin_bucket_name" {
  description = "Not read by the builder. See user_pool_id for why it is set anyway."
  type        = string
}

variable "athena_workgroup" {
  description = "The builder runs no queries. See user_pool_id for why it is set anyway."
  type        = string
}
