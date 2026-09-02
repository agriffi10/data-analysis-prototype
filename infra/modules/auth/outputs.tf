output "user_pool_id" {
  description = "Cognito User Pool ID."
  value       = aws_cognito_user_pool.portal.id
}

output "user_pool_client_id" {
  description = "SPA app client ID."
  value       = aws_cognito_user_pool_client.spa.id
}

output "user_pool_domain" {
  description = "Fully-qualified Hosted UI domain."
  value       = "${aws_cognito_user_pool_domain.portal.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "pre_signup_function_name" {
  description = "Name of the pre-signup validation Lambda. The deploy-lambdas workflow targets this for update-function-code."
  value       = module.pre_signup.function_name
}

output "post_confirmation_function_name" {
  description = "Name of the post-confirmation provisioning Lambda. The deploy-lambdas workflow targets this for update-function-code."
  value       = module.post_confirmation.function_name
}

output "post_confirmation_exec_role_arn" {
  description = "ARN of the post-confirmation Lambda execution role. Informational — module.analytics adds this role as a Lake Formation admin via a CONSTRUCTED ARN string (root locals), not this output, so the value is known at plan time (an unknown here broke the compact() in the LF admins list and silently dropped the grant)."
  value       = aws_iam_role.post_confirmation.arn
}
