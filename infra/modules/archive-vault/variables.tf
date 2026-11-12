variable "archive_bucket_name" {
  description = "Name of the archive bucket (Bucket 5) this module creates. Computed in root locals so the deploy policy can be scoped to its ARN without a cycle, and overridable there because S3 bucket names are globally unique. It is the one bucket the browser has no relationship with at all: no CORS, absent from the CSP connect-src, and the portal role holds zero statements naming it."
  type        = string
}

variable "archive_retention_days" {
  description = "Days after creation at which EVERY object in the archive bucket expires. 2557 = 7 years. A CEILING, not a WORM floor — Object Lock is out of scope (it requires versioning, deferred by decision 2026-08-03, and in compliance mode would make the archive cleanup impossible)."
  type        = number
  default     = 2557
}

variable "deploy_role_arn" {
  description = "ARN of the GitHub Actions deploy role, excluded from the archive bucket policy's Deny. Without the exclusion the deploy role cannot HeadBucket, `tofu refresh` sees the bucket as deleted, and every plan proposes a destructive recreate (the recorded user-space-bucket lesson)."
  type        = string
  default     = ""
}

variable "execution_role_arn" {
  description = "ARN of the archive plane's shared execution role, as a CONSTRUCTED STRING from root locals rather than the resource attribute. The bucket policy is a StringNotLike condition, which only needs the ARN string — and taking the resource attribute would make the policy depend on the role, which is fine, while taking it from root keeps ONE construction of the name shared with the user-space allowlist entry."
  type        = string
  default     = ""
}

variable "account_id" {
  description = "AWS account ID — used to build the shared execution role's log-group ARNs and the constructed function ARNs."
  type        = string
}
