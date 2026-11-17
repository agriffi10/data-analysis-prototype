variable "account_id" {
  description = "This account's id. The delegated policy's only principal is its root; the named policy lets that root read the key's metadata and nothing else, and binds the task role's statements to it with kms:CallerAccount. Passed from root rather than read here, because a module behind depends_on defers its data sources to apply."
  type        = string
}

variable "aws_region" {
  description = "The region, for the named policy's kms:ViaService condition. Passed from root for the same reason as account_id."
  type        = string
}

variable "table_name" {
  description = "The session table's name. Set at root, which builds the table's ARN for the task role from the same string; the deploy role's grant matches <project>-*-sessions."
  type        = string
}

variable "key_alias" {
  description = "The key's alias, built at root; the deploy role's grant matches alias/<project>-*-session. The key's description and Name tag are built from it, so two stores' keys are told apart."
  type        = string

  validation {
    condition     = startswith(var.key_alias, "alias/")
    error_message = "key_alias must start with alias/."
  }
}

variable "named_principals" {
  description = "The roles the key's policy names, or null for a key that delegates to the account's IAM. Set for the deployed store: the deploy role administers the key and uses it through DynamoDB, and the web task role uses it for this table alone."
  type = object({
    deploy_role_arn = string
    task_role_arn   = string
  })
  default = null
}
