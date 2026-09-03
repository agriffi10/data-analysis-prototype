output "bucket_name" {
  description = "Name of the Lambda deployment artifacts bucket. The deploy-lambdas workflow uploaded a zip per function here while the fleet was zip-packaged; nothing writes to it or reads it any more."
  value       = aws_s3_bucket.artifacts.bucket
}

output "bucket_arn" {
  description = "ARN of the Lambda deployment artifacts bucket."
  value       = aws_s3_bucket.artifacts.arn
}
