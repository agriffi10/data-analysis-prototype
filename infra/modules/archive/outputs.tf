# ── archive module outputs ──────────────────────────────────
# The execution-role ARN is exported FOR REFERENCE ONLY — root passes a CONSTRUCTED twin into
# BOTH the user-space bucket policy's allowlist and this bucket's own policy, because an
# unknown-at-plan ARN inside a list silently drops the change.

output "archive_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The browser enqueues archive requests here. Maps to VITE_ARCHIVE_QUEUE_URL."
  value       = aws_sqs_queue.requests.url
}

output "archive_queue_arn" {
  description = "ARN of the FIFO request queue — the portal-role sqs:SendMessage scope."
  value       = aws_sqs_queue.requests.arn
}

output "archive_bucket_name" {
  description = "Name of the archive bucket (Bucket 5). NOT wired into the SPA in any form: the browser has no relationship with this bucket, and the only route to archived bytes is a restore request through this plane."
  value       = aws_s3_bucket.archive.id
}

output "archive_bucket_arn" {
  description = "ARN of the archive bucket — for the deploy policy's own scoping and for ops."
  value       = aws_s3_bucket.archive.arn
}

output "state_machine_arn" {
  description = "ARN of the archive Step Function state machine."
  value       = aws_sfn_state_machine.archive.arn
}

output "execution_role_arn" {
  description = "ARN of the ONE shared execution role every verb Lambda runs under. Reference/ops only — the user-space bucket-policy allowlist and this bucket's own policy both take a constructed-string twin from root locals."
  value       = aws_iam_role.execution.arn
}

output "arcommon_layer_name" {
  description = "Name of the archive-common (arcommon) Lambda layer CI builds + publishes. Named after the PLANE, not the Python package, so it matches the deploy role's *-archive-* layer wildcard. The version ARN is produced by deploy-lambdas.yml, not Terraform (CI-owned layer pattern)."
  value       = local.arcommon_layer_name
}
