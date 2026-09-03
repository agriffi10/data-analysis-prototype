# ── file-send module outputs ──────────────────────────────────────
# The execution-role ARN is exported FOR REFERENCE ONLY — root threads a CONSTRUCTED twin into
# the user-space bucket policy's allowlist, because an unknown-at-plan ARN inside a list
# silently drops the change.

output "file_send_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The API enqueues send-files requests here."
  value       = aws_sqs_queue.requests.url
}

output "file_send_queue_arn" {
  description = "ARN of the FIFO request queue — the API execution role's sqs:SendMessage scope."
  value       = aws_sqs_queue.requests.arn
}

output "state_machine_arn" {
  description = "ARN of the file-send Step Function state machine."
  value       = aws_sfn_state_machine.file_send.arn
}

output "execution_role_arn" {
  description = "ARN of the ONE shared execution role every verb Lambda runs under. Reference/ops only — the user-space bucket-policy allowlist takes a constructed-string twin from root locals."
  value       = aws_iam_role.execution.arn
}

output "fscommon_layer_name" {
  description = "Name of the file-send-common (fscommon) Lambda layer CI built and published while the fleet was zip-packaged. Named after the PLANE, not the Python package, so it matches the deploy role's *-file-send-* layer wildcard. Nothing builds or publishes a layer any more — the name survives so the published versions can be found and destroyed, and it goes with the deploy-role wildcard it was shaped to match."
  value       = local.fscommon_layer_name
}

output "function_names" {
  description = "Every Lambda this module deploys, by deployed name. Aggregated at the root into `lambda_function_names`; the reasoning lives there rather than in fourteen copies of it."
  value       = [for function in module.functions : function.function_name]
}
