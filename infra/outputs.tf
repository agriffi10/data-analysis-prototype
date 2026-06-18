output "s3_static_assets_bucket_name" {
  description = "Name of the S3 bucket hosting the built SPA. Used by the deploy-app workflow."
  value       = module.app.static_assets_bucket_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID. Used by the deployment workflow to create cache invalidations."
  value       = module.app.cloudfront_distribution_id
}

output "cloudfront_domain" {
  description = "CloudFront domain for the portal. Set VITE_APP_URL to this value after the first deploy."
  value       = "https://${module.app.cloudfront_domain_name}"
}

output "github_actions_role_arn" {
  description = "IAM role ARN assumed by the GitHub Actions deployment workflows."
  value       = module.base.github_actions_role_arn
}

output "aws_region" {
  description = "AWS region where resources are deployed. Maps to VITE_AWS_REGION."
  value       = var.aws_region
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID. Set VITE_COGNITO_USER_POOL_ID to this value."
  value       = module.auth.user_pool_id
}

output "cognito_user_pool_client_id" {
  description = "Cognito SPA app client ID. Set VITE_COGNITO_USER_POOL_CLIENT_ID to this value."
  value       = module.auth.user_pool_client_id
}

output "cognito_domain" {
  description = "Cognito Hosted UI domain. Set VITE_COGNITO_DOMAIN to this value."
  value       = module.auth.user_pool_domain
}

output "s3_user_space_bucket_name" {
  description = "Name of the user-space S3 bucket (Bucket 1). Set VITE_S3_USER_SPACE_BUCKET to this value (consumed by the build starting SPEC-013)."
  value       = module.data.user_space_bucket_name
}

output "cognito_identity_pool_id" {
  description = "Cognito Identity Pool ID. Set VITE_COGNITO_IDENTITY_POOL_ID to this value (SPEC-011)."
  value       = module.auth.identity_pool_id
}

output "lambda_artifacts_bucket_name" {
  description = "Lambda deployment artifacts bucket (SPEC-012). The deploy-lambdas workflow uploads packages here before update-function-code."
  value       = module.lambda_artifacts.bucket_name
}

output "pre_signup_function_name" {
  description = "Name of the pre-signup validation Lambda (SPEC-012). The deploy-lambdas workflow targets this for update-function-code."
  value       = module.auth.pre_signup_function_name
}

output "athena_workgroup_name" {
  description = "Name of the shared Athena workgroup (SPEC-032). Set VITE_ATHENA_WORKGROUP to this value (consumed by the app starting SPEC-034)."
  value       = module.analytics.athena_workgroup_name
}

output "athena_admin_bucket_name" {
  description = "Name of the admin-only Athena results bucket (SPEC-032). Exported for ops; not consumed by the app."
  value       = module.analytics.athena_admin_bucket_name
}
