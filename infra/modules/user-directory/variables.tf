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
  description = "Required by the cpcommon layer's import-time config._require, NOT used by the builder — the directory's source is S3 common prefixes, never Cognito (SPEC-146 FR-001). Every function attaching cpcommon needs the UNION of its required env or it crashes at COLD START (PR #196)."
  type        = string
}

variable "app_client_id" {
  description = "Required by the cpcommon layer's import-time config._require (see user_pool_id). The builder makes no Cognito call."
  type        = string
}

variable "shared_space_bucket_name" {
  description = "Required by the cpcommon layer's import-time config._require (see user_pool_id). The builder never touches Bucket 2 — shared-space prefixes are spaces, not users."
  type        = string
}

variable "admin_bucket_name" {
  description = "Required by the cpcommon layer's import-time config._require (see user_pool_id)."
  type        = string
}

variable "athena_workgroup" {
  description = "Required by the cpcommon layer's import-time config._require (see user_pool_id). The builder runs no queries."
  type        = string
}
