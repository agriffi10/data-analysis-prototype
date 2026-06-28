# ── notifications module outputs (SPEC-058) ──────────────────────────────────
# The integration surface for the read/UI specs and any trusted producer. The browser
# learns the queue URL to enqueue user-action messages (sqs:SendMessage granted to the
# portal role here); SPEC-059 wires the URL into the app as VITE_NOTIFICATIONS_QUEUE_URL.

output "notifications_queue_url" {
  description = "URL of the FIFO request queue (ends in .fifo). Maps to VITE_NOTIFICATIONS_QUEUE_URL in SPEC-059; the browser enqueues markRead/markAllRead here."
  value       = aws_sqs_queue.requests.url
}

output "notifications_queue_arn" {
  description = "ARN of the FIFO request queue — the portal-role + (future) trusted-producer sqs:SendMessage scope (FR-006; SPEC-061)."
  value       = aws_sqs_queue.requests.arn
}

output "notifications_writer_role_arn" {
  description = "ARN of the privileged notifications-writer role (the single writer of every user's notifications.json)."
  value       = aws_iam_role.writer.arn
}
