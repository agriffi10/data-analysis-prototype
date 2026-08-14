variable "project_name" {
  description = "Resource name prefix, as {project_name}-{environment}-…"
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names."
  type        = string
}

variable "aws_region" {
  description = "The region every resource here lives in."
  type        = string
}

variable "account_id" {
  description = "This account's id, for the trail's bucket policy and the role's trust."
  type        = string
}

variable "trail_bucket_name" {
  description = "SPEC-186 FR-004: the bucket the archive trail delivers to. A bucket of its OWN, not the admin bucket — the admin bucket's lifecycle rule and its policy are written for portal artefacts, and an audit record that a plane's own role can reach is not an independent record."
  type        = string
}

variable "archive_bucket_name" {
  description = "SPEC-186 FR-004: the bucket whose object-level events the trail records. Named rather than passed as an ARN because the advanced event selector matches on the ARN prefix `{bucket}/`."
  type        = string
}

variable "glue_catalog_arn" {
  description = "SPEC-186 FR-004: the account's Glue catalog ARN, so the verification role's read grants are scoped to it rather than to `*`."
  type        = string
}

variable "trail_retention_days" {
  description = "How long trail objects live. 400 days: long enough that a live check run months after a deploy still has its record, short enough that this never becomes a storage line item."
  type        = number
  default     = 400
}
