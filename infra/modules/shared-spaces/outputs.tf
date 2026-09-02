
output "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). Maps to a VITE_* variable."
  value       = aws_s3_bucket.shared_space.id
}

output "shared_space_bucket_arn" {
  description = "ARN of the shared-space bucket."
  value       = aws_s3_bucket.shared_space.arn
}

output "request_queue_url" {
  description = "URL of the FIFO request queue. The API enqueues control-plane requests here."
  value       = aws_sqs_queue.requests.url
}

output "request_queue_arn" {
  description = "ARN of the FIFO request queue — the API execution role's sqs:SendMessage scope."
  value       = aws_sqs_queue.requests.arn
}

output "orchestrator_role_arn" {
  description = "ARN of the privileged orchestrator role (Step Function + Lambda). Added as a Lake Formation admin."
  value       = aws_iam_role.orchestrator.arn
}

output "state_machine_arn" {
  description = "ARN of the orchestrator Step Function state machine."
  value       = aws_sfn_state_machine.orchestrator.arn
}

output "function_names" {
  description = "Every Lambda this module deploys, by deployed name. Aggregated at the root into `lambda_function_names`; the reasoning lives there rather than in fourteen copies of it."
  value = concat(
    [for function in module.functions : function.function_name],
    [module.transfer_reader.function_name],
  )
}
