output "bucket_name" {
  description = "Name of the Lambda deployment artifacts bucket. The deploy-lambdas workflow uploads packages here."
  value       = aws_s3_bucket.artifacts.bucket
}

output "bucket_arn" {
  description = "ARN of the Lambda deployment artifacts bucket."
  value       = aws_s3_bucket.artifacts.arn
}
