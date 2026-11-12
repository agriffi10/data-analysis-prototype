output "queue_url" {
  description = "The request queue's URL."
  value       = aws_sqs_queue.requests.url
}

output "queue_arn" {
  description = "The request queue's ARN, the sqs:SendMessage scope for whoever writes to it."
  value       = aws_sqs_queue.requests.arn
}

output "role_arn" {
  description = "The writer's execution role's ARN."
  value       = aws_iam_role.this.arn
}

output "function_name" {
  description = "The writer's deployed name."
  value       = module.function.function_name
}

output "function_arn" {
  description = "The writer's ARN."
  value       = module.function.function_arn
}

output "function_names" {
  description = "The writer's deployed name as a one-item list, the shape every module the root aggregates into the fleet's list exports."
  value       = [module.function.function_name]
}
