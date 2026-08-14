output "verification_role_arn" {
  description = "SPEC-186 FR-004: the read-only role a live check assumes. Consumed by modules/analytics, which owns the LF-Tag the catalog half of its access hangs off."
  value       = aws_iam_role.verification.arn
}

output "verification_role_name" {
  description = "The role's name, for the assume-role recipe in docs/testing/."
  value       = aws_iam_role.verification.name
}

output "trail_bucket_name" {
  description = "Where the archive plane's object-level events land. SPEC-170's negative assertion is read from here."
  value       = aws_s3_bucket.trail.id
}

output "trail_name" {
  description = "The trail, so a live check can confirm it is logging before trusting an empty result — a trail that is off reads exactly like a RestoreObject that never happened."
  value       = aws_cloudtrail.archive_audit.name
}
