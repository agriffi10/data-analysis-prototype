variable "project_name" {
  description = "Short name used as a prefix for AWS resource names."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names and carried to the function as ENV_NAME."
  type        = string
}

variable "aws_region" {
  description = "Region for the HTTP API, the function and the regional custom domain."
  type        = string
}

variable "api_host" {
  description = "Hostname the API answers on, without scheme. Built at root from the domain variables and passed down — never derived here, so one place decides what the origin is."
  type        = string
}

variable "api_certificate_arn" {
  description = "Regional ACM certificate for api_host. Fed from the certificate VALIDATION resource, not the certificate itself: both carry the same ARN, but only the validation creates the edge that stops a clean rebuild attaching a PENDING_VALIDATION certificate."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone that answers for the parent domain, carrying this API's A-alias record."
  type        = string
}

variable "spa_origin" {
  description = "Origin of the container SPA, admitted by CORS. The container is where ported features are proved."
  type        = string
}

variable "app_url" {
  description = "Origin of the CloudFront-served portal, admitted by CORS beside spa_origin for as long as it is the rollback. Empty until the first CloudFront deploy, and omitted from the list when empty — the same ternary the Cognito callback list and both bucket CORS rules already use. It is removed at the cutover, when the container origin is the only one left."
  type        = string
  default     = ""
}

variable "logs_queue_url" {
  description = "FIFO queue the structured-logging layer writes spans to."
  type        = string
}

variable "logs_queue_arn" {
  description = "ARN of that queue, scoping the function's only non-logging grant."
  type        = string
}

variable "user_pool_id" {
  description = "Cognito User Pool id, carried as COGNITO_USER_POOL_ID. A cpcommon required variable: the layer resolves config lazily, so an unset one fails at first read rather than at import — the environment is complete anyway, so the spec that starts verifying tokens inherits no surprise."
  type        = string
}

variable "app_client_id" {
  description = "Cognito app client id, carried as COGNITO_APP_CLIENT_ID."
  type        = string
}

variable "admin_bucket" {
  description = "Admin bucket name, carried as ADMIN_BUCKET."
  type        = string
}

variable "user_space_bucket" {
  description = "User-space bucket name, carried as USER_SPACE_BUCKET."
  type        = string
}

variable "shared_space_bucket" {
  description = "Shared-space bucket name, carried as SHARED_SPACE_BUCKET."
  type        = string
}

variable "athena_workgroup" {
  description = "Athena workgroup name, carried as ATHENA_WORKGROUP."
  type        = string
}
