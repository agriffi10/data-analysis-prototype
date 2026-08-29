# ── file-ops module outputs ──────────────────────────────────────
# The execution-role ARN is exported FOR REFERENCE ONLY — root threads a CONSTRUCTED twin into
# the user-space bucket policy's allowlist, because an unknown-at-plan ARN inside a list
# silently drops the change.

output "file_ops_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The API enqueues copy/move/delete requests here."
  value       = aws_sqs_queue.requests.url
}

output "file_ops_queue_arn" {
  description = "ARN of the FIFO request queue — the API execution role's sqs:SendMessage scope."
  value       = aws_sqs_queue.requests.arn
}

output "state_machine_arn" {
  description = "ARN of the file-ops Step Function state machine."
  value       = aws_sfn_state_machine.file_ops.arn
}

output "execution_role_arn" {
  description = "ARN of the ONE shared execution role every verb Lambda runs under. Reference/ops only — the user-space bucket-policy allowlist takes a constructed-string twin from root locals."
  value       = aws_iam_role.execution.arn
}

output "focommon_layer_name" {
  description = "Name of the file-ops-common (focommon) Lambda layer CI builds + publishes. Named after the PLANE, not the Python package, so it matches the deploy role's *-file-ops-* layer wildcard. The version ARN is produced by deploy-lambdas.yml, not Terraform (CI-owned layer pattern)."
  value       = local.focommon_layer_name
}
