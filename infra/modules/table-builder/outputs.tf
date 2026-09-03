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
  description = "Name of the polars Lambda layer CI built and published while the fleet was zip-packaged (attached to infer-schema, because the artifact was too large to vendor into Terraform; the image installs polars once for the whole fleet instead). Nothing builds or publishes a layer any more — the name survives so the published versions can be found and destroyed, and it goes with the deploy-role wildcard it was shaped to match."
  value       = local.polars_layer_name
}

output "function_names" {
  description = "Every Lambda this module deploys, by deployed name. Aggregated at the root into `lambda_function_names`; the reasoning lives there rather than in fourteen copies of it."
  value       = [for function in module.functions : function.function_name]
}
