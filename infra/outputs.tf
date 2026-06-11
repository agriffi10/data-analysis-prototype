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
