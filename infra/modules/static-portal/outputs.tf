output "bucket_name" {
  description = "The bucket the built SPA is synced to."
  value       = aws_s3_bucket.portal.bucket
}

output "distribution_id" {
  description = "The distribution serving the portal."
  value       = aws_cloudfront_distribution.portal.id
}
