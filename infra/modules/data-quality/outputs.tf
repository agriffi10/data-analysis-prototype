
output "data_quality_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The API enqueues check-data-quality requests here."
  value       = aws_sqs_queue.requests.url
}

output "data_quality_queue_arn" {
  description = "ARN of the FIFO request queue — the API execution role's sqs:SendMessage scope."
  value       = aws_sqs_queue.requests.arn
}

output "state_machine_arn" {
  description = "ARN of the data-quality Step Function state machine."
  value       = aws_sfn_state_machine.data_quality.arn
}

output "function_names" {
  description = "Every Lambda this module deploys, by deployed name. Aggregated at the root into `lambda_function_names`; the reasoning lives there rather than in fourteen copies of it."
  value       = [for function in module.functions : function.function_name]
}
