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
  value       = "${aws_cognito_user_pool_domain.portal.domain}.auth.${var.aws_region}.amazoncognito.com"
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
  description = "ARN of the post-confirmation Lambda execution role (SPEC-033). Informational — module.analytics adds this role as a Lake Formation admin via a CONSTRUCTED ARN string (root locals), not this output, so the value is known at plan time (an unknown here broke the compact() in the LF admins list and silently dropped the grant)."
  value       = aws_iam_role.post_confirmation.arn
}
