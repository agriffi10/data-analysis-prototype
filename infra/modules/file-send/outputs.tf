# ── file-send module outputs ──────────────────────────────────────
# The browser learns the queue URL to enqueue send requests (sqs:SendMessage granted
# to the portal role above → VITE_FILE_SEND_QUEUE_URL); the queue ARN scopes that
# grant; the state-machine ARN is for ops/observability. The execution-role ARN is
# exported for reference only — root threads a CONSTRUCTED twin into the user-space
# bucket policy's allowlist, because an unknown-at-plan ARN inside a list silently
# drops the change (architecture.md's "unknown ARN in list" trap).

output "file_send_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The browser enqueues send-files requests here. Maps to VITE_FILE_SEND_QUEUE_URL."
  value       = aws_sqs_queue.requests.url
}

output "file_send_queue_arn" {
  description = "ARN of the FIFO request queue — the portal-role sqs:SendMessage scope."
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
  description = "Name of the file-send-common (fscommon) Lambda layer CI builds + publishes. Named after the PLANE, not the Python package, so it matches the deploy role's *-file-send-* layer wildcard. The version ARN is produced by deploy-lambdas.yml, not Terraform (CI-owned layer pattern)."
  value       = local.fscommon_layer_name
}
