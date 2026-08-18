# ── data-quality module outputs ───────────────────────────────────
# Exported for later wiring: the browser learns the queue URL to enqueue checks
# (sqs:SendMessage granted to the portal role → VITE_DATA_QUALITY_QUEUE_URL);
# the queue ARN scopes that grant; the state-machine ARN is for ops/observability; the
# execution role ARN is what goes on the analytics Lake Formation admins list.

output "data_quality_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The browser enqueues check-data-quality requests here (sqs:SendMessage, granted to the portal role). Maps to VITE_DATA_QUALITY_QUEUE_URL."
  value       = aws_sqs_queue.requests.url
}

output "data_quality_queue_arn" {
  description = "ARN of the FIFO request queue — the portal-role sqs:SendMessage scope."
  value       = aws_sqs_queue.requests.arn
}

output "state_machine_arn" {
  description = "ARN of the data-quality Step Function state machine."
  value       = aws_sfn_state_machine.data_quality.arn
}


output "dqcommon_layer_name" {
  description = "Name of the dqcommon Lambda layer CI builds + publishes (attached to all nine verbs alongside cpcommon). The version ARN is produced by deploy-lambdas.yml, not Terraform (CI owns the layer artifact)."
  value       = local.dqcommon_layer_name
}

output "polars_layer_name" {
  description = "Name of the data-quality polars Lambda layer CI builds + publishes (attached to inspect-source ONLY — it must read Parquet footers because Athena needs an explicit column list and does not auto-detect a Parquet schema)."
  value       = local.polars_layer_name
}
