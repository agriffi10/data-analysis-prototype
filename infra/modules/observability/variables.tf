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
# The sweep attaches the cpcommon layer, and that layer's config requires all of these. Until
# SPEC-156 FR-004 it required them AT IMPORT, so a function missing one crashed at COLD START
# with an error naming neither the layer nor the variable (the table-builder break, PR #196);
# it resolves on FIRST READ now, so the failure lands on whichever branch reads it instead.
# The sweep uses none of them, and that is not a reason to remove one — the union is what any
# code path in the layer may demand.

variable "user_pool_id" {
  description = "Cognito User Pool ID. Unused by the sweep. Required by the cpcommon layer's config, which resolves on first READ rather than at import — so a missing value is no longer a cold-start crash but a failure on whichever branch reads it first. STILL SET IT: the union is what any code path in the layer may demand, and 'the function does not use it' is not a reason to remove it."
  type        = string
}

variable "app_client_id" {
  description = "Cognito app client ID. Unused by the sweep. See user_pool_id for why it is set even though this function never reads it."
  type        = string
}

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
