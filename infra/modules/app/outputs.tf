output "static_assets_bucket_name" {
  description = "Name of the S3 bucket hosting the built SPA."
  value       = aws_s3_bucket.static_assets.bucket
}

output "static_assets_bucket_arn" {
  description = "ARN of the static assets bucket. Consumed by the base module's deploy role policy."
  value       = aws_s3_bucket.static_assets.arn
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID. Used for cache invalidations."
  value       = aws_cloudfront_distribution.portal.id
}

output "cloudfront_domain_name" {
  description = "CloudFront domain name serving the portal."
  value       = aws_cloudfront_distribution.portal.domain_name
}
