output "user_space_bucket_name" {
  description = "Name of the user-space S3 bucket (Bucket 1). Maps to VITE_S3_USER_SPACE_BUCKET."
  value       = aws_s3_bucket.user_space.id
}

output "user_space_bucket_arn" {
  description = "ARN of the user-space S3 bucket. Consumed by the portal role and the bucket policy."
  value       = aws_s3_bucket.user_space.arn
}

output "iam_role_arn" {
  description = "ARN of the shared portal IAM role. The app never consumes this — role binding is Identity Pool config; the data module attaches the permission policy."
  value       = aws_iam_role.portal.arn
}
