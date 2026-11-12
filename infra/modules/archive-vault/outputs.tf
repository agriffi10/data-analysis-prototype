output "archive_bucket_name" {
  description = "Name of the archive bucket (Bucket 5). NOT wired into the SPA in any form: the browser has no relationship with this bucket, and the only route to archived bytes is a restore request through the archive plane."
  value       = aws_s3_bucket.archive.id
}

output "archive_bucket_arn" {
  description = "ARN of the archive bucket — for the deploy policy's own scoping and for ops."
  value       = aws_s3_bucket.archive.arn
}
