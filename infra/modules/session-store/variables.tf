variable "project_name" {
  description = "Short name used as a prefix for AWS resource names."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used in resource names."
  type        = string
}

variable "account_id" {
  description = "This account's id, the only principal the key's policy names. Passed from root rather than read here, because a module behind depends_on defers its data sources to apply."
  type        = string
}

variable "table_name" {
  description = "The session table's name. Set at root, which builds the table's ARN for the task role from the same string; the deploy role's grant matches <project>-*-sessions."
  type        = string
}
