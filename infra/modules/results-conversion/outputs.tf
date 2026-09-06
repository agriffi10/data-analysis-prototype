# ── results-conversion module outputs ──────────────────────────────────────

output "results_conversion_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The API enqueues conversion requests here."
  value       = aws_sqs_queue.requests.url
}

output "results_conversion_queue_arn" {
  description = "ARN of the FIFO request queue — the API execution role's sqs:SendMessage scope."
  value       = aws_sqs_queue.requests.arn
}

output "state_machine_arn" {
  description = "ARN of the results-conversion Step Function state machine."
  value       = aws_sfn_state_machine.results_conversion.arn
}

output "execution_role_arn" {
  description = "ARN of the ONE shared execution role every verb Lambda runs under. Reference/ops only."
  value       = aws_iam_role.execution.arn
}

output "function_names" {
  description = "Every Lambda this module deploys, by deployed name. Aggregated at the root into `lambda_function_names`."
  value       = [for function in module.functions : function.function_name]
}
