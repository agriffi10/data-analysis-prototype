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
