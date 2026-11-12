variable "project_name" {
  description = "Project name prefix for all resource names."
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g. prod), used in resource names."
  type        = string
}
