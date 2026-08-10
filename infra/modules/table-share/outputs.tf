# ── table-share module outputs (SPEC-088) ────────────────────────────────────
# Exported for later wiring: the browser learns the queue URL to enqueue share
# requests (sqs:SendMessage granted to the portal role in SPEC-089 →
# VITE_TABLE_SHARE_QUEUE_URL); the queue ARN scopes that grant; the state-machine
# ARN is for ops/observability; the execution-role ARN feeds the SPEC-092 LF-admin
# wiring (root passes a constructed twin — this output is for reference/ops).

output "table_share_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The browser enqueues share-table requests here (sqs:SendMessage, granted to the portal role in SPEC-089). Maps to VITE_TABLE_SHARE_QUEUE_URL."
  value       = aws_sqs_queue.requests.url
}

output "table_share_queue_arn" {
  description = "ARN of the FIFO request queue — the portal-role sqs:SendMessage scope (SPEC-089)."
  value       = aws_sqs_queue.requests.arn
}

output "state_machine_arn" {
  description = "ARN of the table-share Step Function state machine."
  value       = aws_sfn_state_machine.table_share.arn
}

output "execution_role_arn" {
  description = "ARN of the ONE shared execution role every verb Lambda runs under (LF-admin wiring lands in SPEC-092 via a constructed-string root local)."
  value       = aws_iam_role.execution.arn
}

output "tscommon_layer_name" {
  description = "Name of the table-share-common (tscommon) Lambda layer CI builds + publishes (attached to every verb that carries this plane's wording; copy-objects is deliberately without it since SPEC-160). The version ARN is produced by deploy-lambdas.yml, not Terraform (CI-owned layer pattern)."
  value       = local.tscommon_layer_name
}
