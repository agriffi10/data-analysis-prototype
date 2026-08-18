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
  description = "The bucket the archive trail delivers to. A bucket of its OWN, not the admin bucket — the admin bucket's lifecycle rule and its policy are written for portal artefacts, and an audit record that a plane's own role can reach is not an independent record."
  type        = string
}

variable "archive_bucket_name" {
  description = "The bucket whose object-level events the trail records. Named rather than passed as an ARN because the advanced event selector matches on the ARN prefix `{bucket}/`."
  type        = string
}


variable "trail_retention_days" {
  description = "How long trail objects live. 400 days: long enough that a live check run months after a deploy still has its record, short enough that this never becomes a storage line item."
  type        = number
  default     = 400
}

variable "verification_principal_arns" {
  description = "The IAM principals allowed to assume the read-only verification role — operator identities, so they travel as the TF_VAR_verification_principal_arns repo variable and not in the repo. NOT a local terraform.tfvars: see iam.tf, a local apply plans to destroy the data buckets this account's human identities cannot read. EMPTY BY DEFAULT, and the role is then not created at all: a role nobody has named is a role nobody needs, and delegating to the account root instead was rejected by the plan scan (CKV_AWS_61) for the right reason — naming the principal is a scopable alternative, which is exactly what the accept list is NOT for. The trail is unconditional and needs no principal."
  type        = list(string)
  default     = []
}
