variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names as {project_name}-{environment}."
  type        = string
}

variable "app_url" {
  description = "Public URL of the deployed app (e.g. the CloudFront domain). Added to the User Pool Client callback/logout URLs alongside localhost. When empty, only localhost is configured."
  type        = string
  default     = ""
}

variable "cognito_domain_prefix" {
  description = "Hosted UI domain prefix (must be globally unique). When empty, defaults to {project_name}-{environment}-portal."
  type        = string
  default     = ""
}
