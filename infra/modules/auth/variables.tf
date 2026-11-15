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
  description = "Number of shared-space membership slots — the user pool gains custom:shared_space_1..N (mutable string), and the API reads each as the value of session tag shared_space_1..N. Single source is the root variable of the same name."
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
  description = "Origin of the SPA, on either side of the web tier's switch, and the only deployed entry in the app client's callback and logout lists. Built at root from the domain variables. Empty is tolerated because the list compacts, but under normal operation it is always set — an empty value leaves localhost as the only callback and no deployed sign-in can complete."
  type        = string
  default     = ""
}

variable "lambda_image_repository_url" {
  description = "Registry URI of the fleet's one container image, from module.lambda_image. Every function in this module runs that image and differs only by its command."
  type        = string
}

variable "lambda_image_tag" {
  description = "The commit sha this module's functions are CREATED from. Ignored after creation — CI re-points every function with update-function-code on each deploy — but it must be a tag the registry already holds, or CreateFunction fails."
  type        = string
}

variable "client_secret_parameter_name" {
  description = "The SSM parameter the server client's secret is written to. Named at root, which also builds its ARN for the task's execution role from the same string, so the two cannot disagree."
  type        = string
}

variable "dev_origin" {
  description = "The origin `npm run dev` serves on. The dev client's one callback and one sign-out URL are built from it, and no other client names it."
  type        = string
}

variable "dev_session_parameter_name" {
  description = "The SSM parameter holding every variable a local portal server needs, the dev client's secret included. Named at root beside the server secret's, under the path the deploy role's grant admits."
  type        = string
}

variable "dev_session_environment" {
  description = "What a local server reads, built at root from the same locals as the task definition's environment, with the dev origin as PORTAL_ORIGIN. The dev client's id and secret are added here, where the client is; no other value may be."
  type        = map(string)

  validation {
    condition     = !contains(keys(var.dev_session_environment), "OIDC_CLIENT_ID") && !contains(keys(var.dev_session_environment), "OIDC_CLIENT_SECRET")
    error_message = "dev_session_environment may not name the client; the module adds the dev client's own id and secret."
  }
}
