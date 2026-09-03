# ── archive module outputs ──────────────────────────────────
# The execution-role ARN is exported FOR REFERENCE ONLY — root passes a CONSTRUCTED twin into
# BOTH the user-space bucket policy's allowlist and this bucket's own policy, because an
# unknown-at-plan ARN inside a list silently drops the change.

output "archive_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). The API enqueues archive requests here."
  value       = aws_sqs_queue.requests.url
}

output "archive_queue_arn" {
  description = "ARN of the FIFO request queue — the API execution role's sqs:SendMessage scope."
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

output "function_names" {
  description = "Every Lambda this module deploys, by deployed name. Aggregated at the root into `lambda_function_names`; the reasoning lives there rather than in fourteen copies of it."
  value       = [for function in module.functions : function.function_name]
}
