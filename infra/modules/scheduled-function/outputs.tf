output "function_name" {
  description = "The function's deployed name."
  value       = module.function.function_name
}

output "function_arn" {
  description = "The function's ARN."
  value       = module.function.function_arn
}

output "role_arn" {
  description = "The execution role's ARN."
  value       = aws_iam_role.this.arn
}

output "role_unique_id" {
  description = "The execution role's unique id, which a caller can compare against an S3 object's owner to admit only this function's writes."
  value       = aws_iam_role.this.unique_id
}

output "function_names" {
  description = "The function's deployed name as a one-item list, the shape every module the root aggregates into the fleet's list exports."
  value       = [module.function.function_name]
}
