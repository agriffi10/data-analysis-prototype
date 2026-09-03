output "table_build_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The API enqueues create-table requests here."
  value       = aws_sqs_queue.requests.url
}

output "table_build_queue_arn" {
  description = "ARN of the FIFO request queue — the API execution role's sqs:SendMessage scope."
  value       = aws_sqs_queue.requests.arn
}

output "state_machine_arn" {
  description = "ARN of the table-builder Step Function state machine."
  value       = aws_sfn_state_machine.table_builder.arn
}

output "function_names" {
  description = "Every Lambda this module deploys, by deployed name. Aggregated at the root into `lambda_function_names`; the reasoning lives there rather than in fourteen copies of it."
  value       = [for function in module.functions : function.function_name]
}
