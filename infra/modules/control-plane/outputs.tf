output "queue_url" {
  description = "The FIFO request queue's URL, which the API enqueues to."
  value       = aws_sqs_queue.requests.url
}

output "queue_arn" {
  description = "The FIFO request queue's ARN, the scope of the API role's sqs:SendMessage."
  value       = aws_sqs_queue.requests.arn
}

output "dlq_arn" {
  description = "The plane's own DLQ, which the drain names the plane by."
  value       = aws_sqs_queue.requests_dlq.arn
}

output "state_machine_arn" {
  description = "The plane's state machine."
  value       = aws_sfn_state_machine.this.arn
}

output "execution_role_arn" {
  description = "The role every verb runs as."
  value       = aws_iam_role.execution.arn
}

output "function_names" {
  description = "Every verb's deployed name, aggregated at the root into the fleet's list."
  value       = [for function in module.functions : function.function_name]
}
