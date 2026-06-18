output "athena_workgroup_name" {
  description = "Name of the shared Athena workgroup. Maps to VITE_ATHENA_WORKGROUP (consumed by the app starting SPEC-034)."
  value       = aws_athena_workgroup.portal.name
}

output "athena_admin_bucket_name" {
  description = "Name of the admin-only Athena results bucket (workgroup default output / future audit). Not consumed by the app; exported for ops."
  value       = aws_s3_bucket.athena_admin.id
}

output "lf_admin_role_arn" {
  description = "ARN of the Lake Formation admin role assumable by the account root user (console 'Switch role'). Carries LF + Glue catalog admin permissions for manual catalog inspection/management."
  value       = aws_iam_role.lf_admin.arn
}
