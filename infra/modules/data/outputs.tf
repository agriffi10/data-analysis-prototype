output "user_space_bucket_name" {
  description = "Name of the user-space S3 bucket (Bucket 1). Maps to VITE_S3_USER_SPACE_BUCKET."
  value       = aws_s3_bucket.user_space.id
}

output "user_space_bucket_arn" {
  description = "ARN of the user-space S3 bucket. Consumed by SPEC-011/013 for the portal role and bucket policy."
  value       = aws_s3_bucket.user_space.arn
}
