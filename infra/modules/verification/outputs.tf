output "verification_role_arn" {
  description = "The read-only role a live check assumes, or \"\" when no principal has been named (`verification_principal_arns`). Consumed by modules/analytics, whose compact() drops the empty string rather than granting Lake Formation DESCRIBE to a role that does not exist."
  value       = try(aws_iam_role.verification[0].arn, "")
}

output "verification_role_name" {
  description = "The role's name, for the assume-role recipe in docs/testing/. Empty when no principal has been named."
  value       = try(aws_iam_role.verification[0].name, "")
}

output "trail_bucket_name" {
  description = "Where the archive plane's object-level events land. The restore's negative assertion is read from here. UNCONDITIONAL — it needs no principal."
  value       = aws_s3_bucket.trail.id
}

output "trail_name" {
  description = "The trail, so a live check can confirm it is logging before trusting an empty result — a trail that is off reads exactly like a RestoreObject that never happened."
  value       = aws_cloudtrail.archive_audit.name
}
