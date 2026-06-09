output "s3_static_assets_bucket_name" {
  description = "Name of the S3 bucket hosting the built SPA. Used by the SPEC-004 deployment workflow."
  value       = aws_s3_bucket.static_assets.bucket
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID. Used by the deployment workflow to create cache invalidations."
  value       = aws_cloudfront_distribution.portal.id
}

output "cloudfront_domain" {
  description = "CloudFront domain for the portal. Set VITE_APP_URL to this value after the first deploy."
  value       = "https://${aws_cloudfront_distribution.portal.domain_name}"
}

output "github_actions_role_arn" {
  description = "IAM role ARN assumed by the GitHub Actions deployment workflow (SPEC-004)."
  value       = aws_iam_role.github_actions_deploy.arn
}

output "aws_region" {
  description = "AWS region where resources are deployed. Maps to VITE_AWS_REGION."
  value       = var.aws_region
}
