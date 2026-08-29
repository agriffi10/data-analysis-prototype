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

output "polars_layer_name" {
  description = "Name of the polars Lambda layer CI builds + publishes (attached to infer-schema). The version ARN is produced by deploy-lambdas.yml, not Terraform (the layer artifact is too large to vendor — same CI-owned pattern as shared-space-common)."
  value       = local.polars_layer_name
}
