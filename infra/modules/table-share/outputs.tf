

output "table_share_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The API enqueues share-table requests here."
  value       = aws_sqs_queue.requests.url
}

output "table_share_queue_arn" {
  description = "ARN of the FIFO request queue — the API execution role's sqs:SendMessage scope."
  value       = aws_sqs_queue.requests.arn
}

output "state_machine_arn" {
  description = "ARN of the table-share Step Function state machine."
  value       = aws_sfn_state_machine.table_share.arn
}

output "execution_role_arn" {
  description = "ARN of the ONE shared execution role every verb Lambda runs under (LF-admin wiring goes through a constructed-string root local)."
  value       = aws_iam_role.execution.arn
}

output "tscommon_layer_name" {
  description = "Name of the table-share-common (tscommon) Lambda layer CI builds + publishes (attached to every verb that carries this plane's wording; copy-objects is deliberately without it). The version ARN is produced by deploy-lambdas.yml, not Terraform (CI-owned layer pattern)."
  value       = local.tscommon_layer_name
}
