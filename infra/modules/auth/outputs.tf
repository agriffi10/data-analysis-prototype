output "user_pool_id" {
  description = "Cognito User Pool ID. Maps to VITE_COGNITO_USER_POOL_ID."
  value       = aws_cognito_user_pool.portal.id
}

output "user_pool_client_id" {
  description = "SPA app client ID. Maps to VITE_COGNITO_USER_POOL_CLIENT_ID."
  value       = aws_cognito_user_pool_client.spa.id
}

output "user_pool_domain" {
  description = "Fully-qualified Hosted UI domain. Maps to VITE_COGNITO_DOMAIN."
  value       = "${aws_cognito_user_pool_domain.portal.domain}.auth.${data.aws_region.current.name}.amazoncognito.com"
}

output "identity_pool_id" {
  description = "Cognito Identity Pool ID. Maps to VITE_COGNITO_IDENTITY_POOL_ID; consumed by the data module's roles attachment + portal role trust."
  value       = aws_cognito_identity_pool.portal.id
}

output "pre_signup_function_name" {
  description = "Name of the pre-signup validation Lambda (SPEC-012). The deploy-lambdas workflow targets this for update-function-code."
  value       = aws_lambda_function.pre_signup.function_name
}

output "post_confirmation_function_name" {
  description = "Name of the post-confirmation provisioning Lambda (SPEC-033). The deploy-lambdas workflow targets this for update-function-code."
  value       = aws_lambda_function.post_confirmation.function_name
}

output "post_confirmation_exec_role_arn" {
  description = "ARN of the post-confirmation Lambda execution role (SPEC-033). Consumed by module.analytics as lambda_provisioner_role_arn — added as a Lake Formation admin (SPEC-032 FR-004) so the Lambda can issue per-database grants."
  value       = aws_iam_role.post_confirmation.arn
}
