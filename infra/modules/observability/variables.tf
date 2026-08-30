variable "project_name" {
  description = "Project name prefix for all resource names."
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g. prod), used in resource names and stamped on every log event as `env`."
  type        = string
}

variable "aws_region" {
  description = "AWS region."
  type        = string
}

variable "admin_bucket_name" {
  description = "Athena admin bucket. The sweep writes NDJSON under logs/ and touches nothing else in it."
  type        = string
}

variable "admin_bucket_arn" {
  description = "ARN of the Athena admin bucket, for the sweep's prefix-scoped s3:PutObject grant."
  type        = string
}

# ── The cpcommon layer's required union ──────────────────────────────────────
# The sweep reads none of these. That is not a reason to remove one. See README.md.

variable "user_space_bucket_name" {
  description = "User-space bucket name. Unused by the sweep (it is granted no access to it). See user_pool_id for why it is set even though this function never reads it."
  type        = string
}

variable "shared_space_bucket_name" {
  description = "Shared-space bucket name. Unused by the sweep (it is granted no access to it). See user_pool_id for why it is set even though this function never reads it."
  type        = string
}

variable "athena_workgroup" {
  description = "Athena workgroup. Unused by the sweep. See user_pool_id for why it is set even though this function never reads it."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch retention for the sweep's OWN log group. Unrelated to logs/ in S3, which is retained indefinitely by decision."
  type        = number
  default     = 14
}
