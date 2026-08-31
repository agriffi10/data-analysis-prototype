variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment}."
  type        = string
}

variable "cognito_domain_prefix" {
  description = "Hosted UI domain prefix (must be globally unique). When empty, defaults to {project_name}-{environment}-portal."
  type        = string
  default     = ""
}

# ── Post-confirmation provisioning Lambda inputs ────────────────────────────

variable "aws_region" {
  description = "AWS region — used to scope the post-confirmation Lambda exec role's Glue ARNs."
  type        = string
}

variable "account_id" {
  description = "AWS account ID — used to build the Glue catalog/database ARNs in the post-confirmation Lambda exec role policy."
  type        = string
}

variable "portal_role_arn" {
  description = "ARN of the shared portal IAM role. The post-confirmation Lambda receives this via env var and targets it in the per-database Lake Formation grant."
  type        = string
}

# ── Shared-space membership slots ──────────────────────────────────────────────

variable "max_shared_memberships" {
  description = "Number of shared-space membership slots — the user pool gains custom:shared_space_1..N (mutable string) and the Identity Pool maps each to principal tag shared_space_1..N. Single source is the root variable of the same name."
  type        = number
  default     = 10
}

# ── Structured logging ────────────────────────────────────────────────────────
# Both triggers attach cpcommon for ONE import — `observability` — and emit under
# service="auth". No cpcommon.config variable joins them. README.md.

variable "logs_queue_arn" {
  description = "Structured-logging queue ARN — the ONLY sqs:SendMessage scope granted to either trigger's exec role. A CONSTRUCTED string from the root locals, not module.observability's output: module.observability consumes this module's user_pool_id, so a real reference here is a module cycle."
  type        = string
}

variable "logs_queue_url" {
  description = <<-EOT
    Structured-logging queue URL, set as LOGS_QUEUE_URL on both triggers.

    Optional BY CONSTRUCTION on the Lambda side: cpcommon.observability reads it with
    os.environ.get and never config._require, so a trigger deployed without it logs to
    stdout instead of failing at cold start. Passed here so it is set in
    practice. Constructed at the root for the cycle reason in logs_queue_arn.
  EOT
  type        = string
}

variable "spa_origin" {
  description = "Origin of the container SPA, and the only deployed entry in the app client's callback and logout lists now that the CloudFront one is retired. Built at root from the domain variables. Empty is tolerated because the list compacts, but under normal operation it is always set — an empty value leaves localhost as the only callback and no deployed sign-in can complete."
  type        = string
  default     = ""
}
