# ── shared-spaces module outputs ──────────────────────────────────
# Exported for later app wiring (VITE_* in SPEC-056+) and ops. The browser learns
# the queue URL to enqueue requests (sqs:SendMessage granted in SPEC-056); the
# bucket name maps to a VITE_* once shared-space file ops land.

output "shared_space_bucket_name" {
  description = "Name of the shared-space bucket (Bucket 2). Maps to a VITE_* in SPEC-057."
  value       = aws_s3_bucket.shared_space.id
}

output "shared_space_bucket_arn" {
  description = "ARN of the shared-space bucket."
  value       = aws_s3_bucket.shared_space.arn
}

output "request_queue_url" {
  description = "URL of the FIFO request queue. The browser enqueues control-plane requests here (sqs:SendMessage, granted to the portal role in SPEC-056). Maps to VITE_SHARED_SPACE_QUEUE_URL."
  value       = aws_sqs_queue.requests.url
}

output "request_queue_arn" {
  description = "ARN of the FIFO request queue — the portal-role sqs:SendMessage scope."
  value       = aws_sqs_queue.requests.arn
}

output "orchestrator_role_arn" {
  description = "ARN of the privileged orchestrator role (Step Function + Lambda). Added as a Lake Formation admin in SPEC-056."
  value       = aws_iam_role.orchestrator.arn
}

output "state_machine_arn" {
  description = "ARN of the orchestrator Step Function state machine."
  value       = aws_sfn_state_machine.orchestrator.arn
}
