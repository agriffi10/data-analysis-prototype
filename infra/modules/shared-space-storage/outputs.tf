output "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). Maps to a VITE_* variable."
  value       = aws_s3_bucket.shared_space.id
}

output "shared_space_bucket_arn" {
  description = "ARN of the shared-space bucket."
  value       = aws_s3_bucket.shared_space.arn
}
