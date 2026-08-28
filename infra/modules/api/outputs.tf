# No api_origin or api_host output — both are built at ROOT and passed DOWN. README.md.

output "api_id" {
  description = "HTTP API id — names the API in live checks and in the access-log group."
  value       = aws_apigatewayv2_api.api.id
}

output "api_execution_arn" {
  description = "Execution ARN of the HTTP API, scoping the function's invoke permission."
  value       = aws_apigatewayv2_api.api.execution_arn
}

output "api_function_name" {
  description = "Name of the placeholder function, for the deploy matrix and live invocation checks."
  value       = aws_lambda_function.api.function_name
}

output "api_endpoint_target" {
  description = "Regional target the alias record points at — read back in verification to prove the record resolves to this API rather than to a stale domain."
  value       = aws_apigatewayv2_domain_name.api.domain_name_configuration[0].target_domain_name
}

output "api_execution_role_arn" {
  description = "ARN of this function's execution role. Consumed by the portal role's trust policy, and it is a REAL reference rather than a constructed string on purpose: IAM validates a trust policy's Principal and refuses an ARN naming a role that does not exist yet, so the dependency edge is what makes a from-scratch apply order the two correctly."
  value       = aws_iam_role.api.arn
}
