output "athena_workgroup_name" {
  description = "Name of the shared Athena workgroup. Feeds every ATHENA_WORKGROUP environment entry, the API function's included."
  value       = aws_athena_workgroup.portal.name
}

output "athena_admin_bucket_name" {
  description = "Name of the admin-only Athena results bucket (workgroup default output / future audit). Not consumed by the app; exported for ops."
  value       = aws_s3_bucket.athena_admin.id
}
