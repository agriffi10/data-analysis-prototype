# The alias the deploy role's grant is written against. The table's name comes from root, which
# also builds the table's ARN for the task role from the same string.
locals {
  key_alias = "alias/${var.project_name}-${var.environment}-session"
}
