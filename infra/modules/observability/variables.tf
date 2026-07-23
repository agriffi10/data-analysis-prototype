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

# ── The cpcommon layer's _require union ──────────────────────────────────────
# The sweep attaches the cpcommon layer, and that layer's config._require runs AT IMPORT for
# every attaching function — so a function missing ANY of these crashes at COLD START, with an
# error naming neither the layer nor the variable (the table-builder break, PR #196). The sweep
# uses none of them; they are here because the layer demands them.

variable "user_pool_id" {
  description = "Cognito User Pool ID. Unused by the sweep — required because cpcommon.config._require runs at import."
  type        = string
}

variable "app_client_id" {
  description = "Cognito app client ID. Unused by the sweep — required because cpcommon.config._require runs at import."
  type        = string
}

variable "user_space_bucket_name" {
  description = "User-space bucket name. Unused by the sweep (it is granted no access to it) — required because cpcommon.config._require runs at import."
  type        = string
}

variable "shared_space_bucket_name" {
  description = "Shared-space bucket name. Unused by the sweep (it is granted no access to it) — required because cpcommon.config._require runs at import."
  type        = string
}

variable "athena_workgroup" {
  description = "Athena workgroup. Unused by the sweep — required because cpcommon.config._require runs at import."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch retention for the sweep's OWN log group. Unrelated to logs/ in S3, which is retained indefinitely by decision (SPEC-127 FR-009)."
  type        = number
  default     = 14
}
