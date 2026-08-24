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

output "portal_role_unique_id" {
  description = "The portal role's IAM unique ID (AROA…). SQS stamps SenderId on every message, and for a ROLE it is {unique_id}:{session-name} (for a user it is a bare user id, no colon) — a system attribute a SendMessage cannot set, so it is the one attributable fact a queued message carries about who sent it. The notifications writer compares the role-id half against this value to refuse a `create` that came from browser credentials. The unique ID, never the name or the ARN — SenderId carries neither, and a comparison against the wrong one silently never matches."
  value       = aws_iam_role.portal.unique_id
}
