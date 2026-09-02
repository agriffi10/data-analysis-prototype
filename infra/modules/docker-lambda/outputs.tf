output "function_name" {
  description = "The deployed name. Consumed by permissions, event-source mappings and the root outputs CI reads, so nothing reconstructs it from a template."
  value       = aws_lambda_function.this.function_name
}

output "function_arn" {
  description = "The function ARN. Consumed by state-machine definitions and by every aws_lambda_permission — and the permission case is load-bearing rather than tidy: the ARN is COMPUTED, so it is unknown while the function is being replaced, which is what plans the permission for replacement alongside it. Binding a permission to the NAME instead leaves it undiffed while DeleteFunction takes the resource policy with it."
  value       = aws_lambda_function.this.arn
}

output "invoke_arn" {
  description = "The apigateway-form ARN an HTTP API integration takes. Not derivable from function_arn without rebuilding a string, which is the thing this module exists to stop."
  value       = aws_lambda_function.this.invoke_arn
}

output "log_group_name" {
  description = "The log group this module created, for a policy that has to grant against it."
  value       = aws_cloudwatch_log_group.this.name
}

output "log_group_arn" {
  description = "The log group's ARN, for the same reason."
  value       = aws_cloudwatch_log_group.this.arn
}
